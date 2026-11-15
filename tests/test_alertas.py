import io
import sqlite3
import threading
import time
import wave
from dataclasses import asdict, replace
from datetime import timedelta

import pytest

from core import events
from core.db import esquema
from core.db.escritor import Escritor, abrir_lectura
from core.state.estado import Estacion, Estado, NaveActual
from modules.comercio import alerts, sonido
from modules.comercio.alerts import Reglas
from modules.comercio.engine.perfil import Perfil
from tests.mercado_de_prueba import AHORA, compra, estacion, sistema, vende

ESPERA = 5.0
AQUI = Estado(
    legacy=False,
    fid="F1",
    sistema="S1",
    posicion=(0.0, 0.0, 0.0),
    nave=NaveActual(
        ship_id=7,
        simbolo="python",
        nombre="",
        ident="",
        capacidad_carga=100,
        capacidad_combustible=32.0,
        datos=None,
    ),
)
# Oro: compra a 9 000 en la 1 y venta a 30 000 en la 2: 21 000 Cr/t.
ACTIVADAS = Reglas(
    activadas=True,
    ganancia_tonelada_min=20_000,
    ganancia_hora_min=1_000_000,
    distancia_max_ly=30.0,
    antiguedad_max_h=24.0,
)


def esperar(condicion, segundos: float = ESPERA) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.02)
    return False


def perfil_de_la_nave() -> dict:
    datos = asdict(Perfil(capacidad=100, rango=20.0, plataforma="L", creditos=None, origen="S1"))
    return {campo: list(v) if isinstance(v, tuple) else v for campo, v in datos.items()}


@pytest.fixture
def base(tmp_path):
    ruta = tmp_path / "luna.db"
    conexion = sqlite3.connect(ruta, isolation_level=None)
    esquema.migrar(conexion)
    sistema(conexion, 1, 0.0)
    sistema(conexion, 2, 10.0)
    sistema(conexion, 3, 80.0)
    estacion(conexion, 101, 1)
    estacion(conexion, 202, 2)
    estacion(conexion, 303, 3)
    vende(conexion, 101, "gold", 9_000)
    compra(conexion, 202, "gold", 30_000)
    alerts.guardar_reglas(conexion, ACTIVADAS)
    conexion.close()
    return ruta


@pytest.fixture
def escritor(base):
    escritor = Escritor(base)
    escritor.iniciar()
    yield escritor
    escritor.detener()


class Timbre:
    def __init__(self) -> None:
        self.veces = 0

    def __call__(self) -> None:
        self.veces += 1


def montar(base, escritor, tmp_path, estado=AQUI, reloj=lambda: AHORA, bus=None):
    timbre = Timbre()
    alertas = alerts.Alertas(
        bus or events.Bus(),
        lambda: estado,
        perfil_de_la_nave,
        tmp_path / "config.json",
        base,
        escritor,
        timbre,
        reloj=reloj,
    )
    return alertas, timbre


def guardados(base) -> list[dict]:
    conexion = abrir_lectura(base)
    try:
        return alerts.avisos(conexion)
    finally:
        conexion.close()


def cambiar_reglas(base, reglas: Reglas) -> None:
    conexion = sqlite3.connect(base, isolation_level=None)
    alerts.guardar_reglas(conexion, reglas)
    conexion.close()


def test_un_mercado_que_pasa_los_umbrales_avisa_una_vez_y_suena(base, escritor, tmp_path):
    alertas, timbre = montar(base, escritor, tmp_path)

    nuevos = alertas.evaluar({202})
    assert [a.clave for a in nuevos] == ["un_salto:101:202:gold"]
    assert timbre.veces == 1
    assert esperar(lambda: len(guardados(base)) == 1)
    aviso = guardados(base)[0]
    assert (aviso["modo"], aviso["ruta"]["compra"]["market_id"]) == ("un_salto", 101)

    assert alertas.evaluar({202, 101}) == []
    assert timbre.veces == 1


def test_la_misma_ruta_vuelve_a_avisar_si_mejora_mas_de_lo_pedido(base, escritor, tmp_path):
    alertas, _ = montar(base, escritor, tmp_path)
    alertas.evaluar({202})
    conexion = sqlite3.connect(base, isolation_level=None)
    conexion.execute("UPDATE market_prices SET sell_price = 31_000 WHERE market_id = 202")
    assert alertas.evaluar({202}) == []  # 1 000 Cr/t más es menos de un 10 % por hora

    conexion.execute("UPDATE market_prices SET sell_price = 40_000 WHERE market_id = 202")
    conexion.close()
    assert len(alertas.evaluar({202})) == 1


def test_pasado_el_plazo_la_misma_ruta_vuelve_a_avisar(base, escritor, tmp_path):
    momento = {"ahora": AHORA}
    alertas, _ = montar(base, escritor, tmp_path, reloj=lambda: momento["ahora"])
    alertas.evaluar({202})

    momento["ahora"] = AHORA + timedelta(minutes=29)
    assert alertas.evaluar({202}) == []
    momento["ahora"] = AHORA + timedelta(minutes=30)
    assert len(alertas.evaluar({202})) == 1


@pytest.mark.parametrize(
    "cambio",
    [
        {"activadas": False},
        {"ganancia_tonelada_min": 21_001},
        {"ganancia_hora_min": 10_000_000_000},
        {"distancia_max_ly": 5.0},
        {"antiguedad_max_h": 0.1},
    ],
)
def test_lo_que_no_pasa_las_reglas_no_avisa(base, escritor, tmp_path, cambio):
    cambiar_reglas(base, replace(ACTIVADAS, **cambio))
    alertas, timbre = montar(base, escritor, tmp_path)

    assert alertas.evaluar({202}) == []
    assert timbre.veces == 0


def test_un_mercado_fuera_de_la_distancia_no_se_evalua(base, escritor, tmp_path):
    conexion = sqlite3.connect(base, isolation_level=None)
    compra(conexion, 303, "gold", 60_000)
    conexion.close()
    alertas, _ = montar(base, escritor, tmp_path)

    assert alertas.evaluar({303}) == []


@pytest.mark.parametrize(
    "estado",
    [
        replace(AQUI, legacy=True),
        replace(AQUI, posicion=None),
        replace(AQUI, fid=None),
    ],
)
def test_sin_posicion_comandante_o_con_legacy_no_hay_alertas(base, escritor, tmp_path, estado):
    alertas, _ = montar(base, escritor, tmp_path, estado=estado)

    assert alertas.evaluar({202}) == []


def test_un_bucle_que_pasa_los_umbrales_avisa_como_bucle(base, escritor, tmp_path):
    conexion = sqlite3.connect(base, isolation_level=None)
    vende(conexion, 202, "silver", 4_000)
    compra(conexion, 101, "silver", 30_000)
    conexion.close()
    alertas, _ = montar(base, escritor, tmp_path)

    claves = {a.clave for a in alertas.evaluar({202})}

    assert "bucle:101:202" in claves


def test_el_hilo_agrupa_los_avisos_del_bus_y_avisa_una_sola_vez(base, escritor, tmp_path):
    bus = events.Bus()
    alertas, timbre = montar(base, escritor, tmp_path, bus=bus)
    alertas.iniciar()
    try:
        bus.publicar(events.MERCADO_ACTUALIZADO, 202)
        bus.publicar(events.MERCADO_ACTUALIZADO, 202)
        bus.publicar(events.ATRACADO, Estacion(nombre="E101", tipo="Coriolis", market_id=101))
        assert esperar(lambda: len(guardados(base)) == 1)
        time.sleep(alerts.AGRUPAR_SEGUNDOS + 0.5)
        assert len(guardados(base)) == 1
        assert timbre.veces == 1
    finally:
        alertas.detener()


def test_el_manejador_del_bus_no_espera_a_la_evaluacion(base, escritor, tmp_path):
    """E-06: el aviso llega en el hilo escritor; el manejador solo encola."""
    bus = events.Bus()
    alertas, _ = montar(base, escritor, tmp_path, bus=bus)
    alertas.iniciar()
    try:
        inicio = time.monotonic()
        bus.publicar(events.MERCADO_ACTUALIZADO, 202)
        assert time.monotonic() - inicio < 0.05
    finally:
        alertas.detener()


def test_tras_reiniciar_lo_ya_avisado_no_se_repite(base, escritor, tmp_path):
    primero, _ = montar(base, escritor, tmp_path)
    primero.evaluar({202})
    assert esperar(lambda: len(guardados(base)) == 1)

    segundo, timbre = montar(base, escritor, tmp_path)
    segundo.iniciar()
    try:
        segundo._cola.put(202)
        time.sleep(alerts.AGRUPAR_SEGUNDOS + 0.5)
    finally:
        segundo.detener()
    assert len(guardados(base)) == 1
    assert timbre.veces == 0


def test_las_reglas_se_guardan_y_se_leen_igual(base):
    conexion = sqlite3.connect(base, isolation_level=None)
    alerts.guardar_reglas(conexion, replace(ACTIVADAS, mejora_pct=25.0))

    assert alerts.leer_reglas(conexion) == replace(ACTIVADAS, mejora_pct=25.0)


def test_sin_reglas_guardadas_estan_desactivadas():
    conexion = sqlite3.connect(":memory:")
    esquema.migrar(conexion)

    assert alerts.leer_reglas(conexion) == Reglas()
    assert not Reglas().activadas


def test_unas_reglas_validas_desde_la_interfaz():
    datos = asdict(ACTIVADAS)

    assert alerts.reglas_desde_dict(datos) == ACTIVADAS
    assert alerts.reglas_desde_dict({**datos, "ganancia_hora_min": 5e6}).ganancia_hora_min == 5e6


@pytest.mark.parametrize(
    ("cambio", "campo"),
    [
        ({"activadas": 1}, "activadas"),
        ({"ganancia_tonelada_min": -1}, "ganancia_tonelada_min"),
        ({"ganancia_tonelada_min": 10.5}, "ganancia_tonelada_min"),
        ({"ganancia_hora_min": "mucho"}, "ganancia_hora_min"),
        ({"distancia_max_ly": 0}, "distancia_max_ly"),
        ({"distancia_max_ly": float("nan")}, "distancia_max_ly"),
        ({"antiguedad_max_h": 10**400}, "antiguedad_max_h"),
        ({"repetir_min": 0.5}, "repetir_min"),
        ({"mejora_pct": True}, "mejora_pct"),
        ({"otra": 1}, "otra"),
    ],
)
def test_una_regla_invalida_se_rechaza_nombrandola(cambio, campo):
    with pytest.raises(alerts.ReglaInvalida) as error:
        alerts.reglas_desde_dict({**asdict(ACTIVADAS), **cambio})
    assert error.value.campo == campo


def test_falta_un_campo_o_no_es_un_diccionario():
    datos = asdict(ACTIVADAS)
    del datos["mejora_pct"]
    with pytest.raises(alerts.ReglaInvalida):
        alerts.reglas_desde_dict(datos)
    with pytest.raises(alerts.ReglaInvalida):
        alerts.reglas_desde_dict([])


def wav(muestras: list[int]) -> bytes:
    salida = io.BytesIO()
    with wave.open(salida, "wb") as destino:
        destino.setnchannels(1)
        destino.setsampwidth(2)
        destino.setframerate(8000)
        destino.writeframes(b"".join(m.to_bytes(2, "little", signed=True) for m in muestras))
    return salida.getvalue()


def muestras_de(datos: bytes) -> list[int]:
    with wave.open(io.BytesIO(datos), "rb") as entrada:
        crudo = entrada.readframes(entrada.getnframes())
    pares = (crudo[i : i + 2] for i in range(0, len(crudo), 2))
    return [int.from_bytes(par, "little", signed=True) for par in pares]


def test_el_volumen_escala_las_muestras():
    original = wav([1000, -2000, 32_767])

    assert muestras_de(sonido.con_volumen(original, 50)) == [500, -1000, 16_383]
    assert muestras_de(sonido.con_volumen(original, 0)) == [0, 0, 0]
    assert muestras_de(sonido.con_volumen(original, 100)) == [1000, -2000, 32_767]


def test_el_sonido_suena_en_su_hilo_con_el_volumen_de_la_configuracion(tmp_path):
    from core.config import ajustes

    archivo = tmp_path / "alerta.wav"
    archivo.write_bytes(wav([1000]))
    config = tmp_path / "config.json"
    oido: list[list[int]] = []
    sonado = threading.Event()

    def reproducir(datos: bytes) -> None:
        oido.append(muestras_de(datos))
        sonado.set()

    reproductor = sonido.Sonido(config, archivo, reproducir)
    reproductor.iniciar()
    try:
        ajustes.guardar_sonido(config, False, 50)
        reproductor.alerta()
        time.sleep(0.2)
        assert oido == []

        ajustes.guardar_sonido(config, True, 50)
        reproductor.alerta()
        assert sonado.wait(ESPERA)
        assert oido == [[500]]
    finally:
        reproductor.detener()


def test_el_wav_de_la_aplicacion_se_puede_escalar():
    from core import recursos

    datos = recursos.ruta("data", "alerta.wav").read_bytes()

    assert len(muestras_de(sonido.con_volumen(datos, 70))) > 1000


def test_la_lista_de_avisos_no_pasa_del_ultimo_id_leido(base, escritor, tmp_path):
    """R3: un aviso que entra entre leer el último id y la lista queda para la siguiente."""
    conexion = sqlite3.connect(base, isolation_level=None)
    for n in range(3):
        aviso = alerts.Aviso(f"c{n}", "un_salto", "2026-11-13T12:00:00Z", 1.0, {})
        alerts.guardar_aviso(conexion, aviso)

    assert [a["id"] for a in alerts.avisos(conexion, 0, 2)] == [2, 1]
    assert [a["id"] for a in alerts.avisos(conexion, 2, alerts.ultimo_id(conexion))] == [3]
    assert [a["id"] for a in alerts.avisos(conexion)] == [3, 2, 1]


def test_sin_perfil_de_nave_el_registro_lo_dice_una_vez(base, escritor, tmp_path, caplog):
    """R5: con EDDN llega una tanda cada 2 s; el motivo se anota una sola vez."""
    alertas = alerts.Alertas(
        events.Bus(),
        lambda: AQUI,
        lambda: {**perfil_de_la_nave(), "capacidad": None},
        tmp_path / "config.json",
        base,
        escritor,
        Timbre(),
        reloj=lambda: AHORA,
    )
    with caplog.at_level("INFO", logger="luna.alertas"):
        for _ in range(3):
            assert alertas.evaluar({202}) == []

    assert sum("perfil de la nave" in r.getMessage() for r in caplog.records) == 1
