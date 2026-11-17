"""Aviso de ruta mejor y destino al portapapeles (prefase 8, bloque 5).

La aceptación reproduce `bucle_comercio.log` evento a evento: el bucle real entre Antonelli
Arsenal y Beregovoi Colony, con un trato mucho mejor en una tercera estación junto a Antonelli.
"""

import json
import sqlite3
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core import events
from core.config import ajustes
from core.db import comandante, esquema
from core.db.escritor import Escritor
from core.journal import comercio
from core.state.estado import Estacion, Estado, aplicar
from modules.comercio import alerts
from modules.comercio.alerts import Despegue
from tests.bucle_de_prueba import BUCLE
from tests.mercado_de_prueba import compra, estacion, sistema, vende
from tests.test_alertas import Timbre, esperar, guardados, perfil_de_la_nave

ANTONELLI, BEREGOVOI, COBALTO = 4299403779, 3228387328, 777
FIN_DEL_BUCLE = datetime(2026, 11, 10, 8, 30, 0, tzinfo=UTC)
FID = "F0000001"
EVENTOS = [json.loads(linea) for linea in BUCLE.read_text(encoding="utf-8").splitlines()]


def crear_base(archivo: Path, precio_del_oro: int = 40_000) -> Path:
    conexion = sqlite3.connect(archivo, isolation_level=None)
    esquema.migrar(conexion)
    sistema(conexion, 1, 120.59375, 32.5625, -31.59375, nombre="HIP 45301")
    sistema(conexion, 2, 59.15625, 20.6875, -37.90625, nombre="Orishpucho")
    sistema(conexion, 3, 130.59375, 32.5625, -31.59375, nombre="Cobalto")
    estacion(conexion, ANTONELLI, 1)
    estacion(conexion, BEREGOVOI, 2)
    estacion(conexion, COBALTO, 3)
    # El bucle que haces: bauxita a Beregovoi y titanio de vuelta.
    vende(conexion, ANTONELLI, "bauxite", 400)
    compra(conexion, BEREGOVOI, "bauxite", 2_000)
    vende(conexion, BEREGOVOI, "titanium", 800)
    compra(conexion, ANTONELLI, "titanium", 1_500)
    # Lo que sale de Antonelli y gana mucho más.
    vende(conexion, ANTONELLI, "gold", 1_000)
    compra(conexion, COBALTO, "gold", precio_del_oro)
    conexion.close()
    return archivo


@pytest.fixture
def base(tmp_path):
    return crear_base(tmp_path / "luna.db")


@pytest.fixture
def escritor(base):
    hilo = Escritor(base)
    hilo.iniciar()
    yield hilo
    hilo.detener()


class Repeticion:
    """El journal reproducido evento a evento; el estado y los tramos van por delante."""

    def __init__(self, base: Path, escritor: Escritor, config: Path) -> None:
        self.estado = Estado()
        self.libro = comercio.Libro()
        self.ahora = datetime(2026, 11, 10, 3, 41, 24, tzinfo=UTC)
        self.escritor = escritor
        self.conexion = sqlite3.connect(base, isolation_level=None)
        self.timbre = Timbre()
        self.alertas = alerts.Alertas(
            events.Bus(),
            lambda: self.estado,
            perfil_de_la_nave,
            config,
            base,
            escritor,
            self.timbre,
            reloj=lambda: self.ahora,
        )
        self.base = base

    def correr(self) -> None:
        comandante.registrar_comandante(self.conexion, FID, "CMDR Prueba", "2026-11-10")
        for evento in EVENTOS:
            self.estado = aplicar(self.estado, evento)
            self.ahora = datetime.fromisoformat(evento["timestamp"])
            self.libro, tramo = comercio.anotar(self.libro, self.estado, evento)
            if tramo:
                comandante.guardar_tramos(self.conexion, [(FID, tramo)])
            if evento["event"] == "Docked":
                self.alertas.evaluar({evento["MarketID"]})
        self.conexion.close()

    def avisos_de_ruta_mejor(self) -> list[dict]:
        hecho = time.monotonic() + 5
        espera = []
        self.escritor.encolar(lambda _: None, lambda _: espera.append(1))
        while not espera and time.monotonic() < hecho:
            time.sleep(0.02)
        return [a for a in guardados(self.base) if "mejor_que" in a["ruta"]]


def test_en_un_bucle_con_una_ruta_mejor_cerca_avisa_una_sola_vez(base, escritor, tmp_path):
    repeticion = Repeticion(base, escritor, tmp_path / "config.json")

    repeticion.correr()
    avisos = repeticion.avisos_de_ruta_mejor()

    assert len(avisos) == 1
    [aviso] = avisos
    assert aviso["modo"] == "un_salto"
    assert aviso["ruta"]["compra"]["market_id"] == ANTONELLI
    assert aviso["ruta"]["venta"]["market_id"] == COBALTO
    mejor_que = aviso["ruta"]["mejor_que"]
    assert aviso["ganancia_hora"] > mejor_que["por_hora_hoy"] * 1.2
    assert mejor_que["por_hora_real"] > 0
    assert [p["estacion"] for p in mejor_que["paradas"]] == [
        "Antonelli Arsenal",
        "Beregovoi Colony",
    ] or {p["estacion"] for p in mejor_que["paradas"]} == {"Antonelli Arsenal", "Beregovoi Colony"}
    assert esperar(lambda: repeticion.timbre.veces == 1)


def test_con_el_interruptor_apagado_no_avisa_nunca(base, escritor, tmp_path):
    config = tmp_path / "config.json"
    ajustes.guardar_ruta_en_curso(config, False, 20.0, False)
    repeticion = Repeticion(base, escritor, config)

    repeticion.correr()

    assert repeticion.avisos_de_ruta_mejor() == []
    assert repeticion.timbre.veces == 0


def test_un_margen_que_la_mejora_no_alcanza_no_avisa(base, escritor, tmp_path):
    primera = Repeticion(base, escritor, tmp_path / "config.json")
    primera.correr()
    [aviso] = primera.avisos_de_ruta_mejor()
    hoy = aviso["ruta"]["mejor_que"]["por_hora_hoy"]
    # La ganancia del trato nuevo crece en línea con su precio de venta: el doble de lo tuyo,
    # que con el margen máximo (1 000 %) no es una mejora suficiente.
    precio = 1_000 + round(39_000 * 2 * hoy / aviso["ganancia_hora"])

    otra = crear_base(tmp_path / "otra.db", precio_del_oro=precio)
    otro_escritor = Escritor(otra)
    otro_escritor.iniciar()
    try:
        config = tmp_path / "otra.json"
        ajustes.guardar_ruta_en_curso(config, True, 1_000.0, False)
        repeticion = Repeticion(otra, otro_escritor, config)
        repeticion.correr()

        assert repeticion.avisos_de_ruta_mejor() == []
    finally:
        otro_escritor.detener()


def test_sin_ninguna_ruta_en_curso_no_hay_con_que_comparar(base, escritor, tmp_path):
    repeticion = Repeticion(base, escritor, tmp_path / "config.json")
    repeticion.estado = replace(
        aplicar(Estado(), EVENTOS[1]), posicion=(120.59375, 32.5625, -31.59375)
    )
    repeticion.estado = replace(
        repeticion.estado,
        estacion=Estacion(nombre="Antonelli Arsenal", market_id=ANTONELLI, tipo="Coriolis"),
        sistema="HIP 45301",
    )

    assert repeticion.alertas.evaluar({ANTONELLI}) == []


def test_pasadas_doce_horas_la_misma_ruta_mejor_vuelve_a_avisar(base, escritor, tmp_path):
    repeticion = Repeticion(base, escritor, tmp_path / "config.json")
    repeticion.correr()
    ultimo = repeticion.estado
    repeticion.conexion = sqlite3.connect(base, isolation_level=None)

    repeticion.estado = ultimo
    repeticion.ahora = repeticion.ahora + alerts.VENTANA_MEJOR + timedelta(minutes=1)
    # El tramo más reciente tiene que seguir dentro de la pausa de sesión para haber ruta en curso.
    repeticion.conexion.execute(
        "UPDATE trade_legs SET llegada = ?", (repeticion.ahora.strftime("%Y-%m-%dT%H:%M:%SZ"),)
    )
    repeticion.conexion.close()

    nuevos = repeticion.alertas.evaluar({ANTONELLI})

    assert [a.clave.startswith(alerts.PREFIJO_MEJOR) for a in nuevos] == [True]


def preparar_despegue(base, escritor, tmp_path, portapapeles: bool):
    """La base con los 14 tramos reales y un hilo de alertas que copia con una función falsa."""
    conexion = sqlite3.connect(base, isolation_level=None)
    from tests.bucle_de_prueba import guardar_el_bucle

    guardar_el_bucle(conexion)
    conexion.close()
    config = tmp_path / "config.json"
    ajustes.guardar_ruta_en_curso(config, False, 20.0, portapapeles)
    copiados: list[str] = []
    estado = replace(Estado(), fid=FID, legacy=False, sistema="HIP 45301", posicion=(0.0, 0.0, 0.0))
    ahora = {"valor": FIN_DEL_BUCLE}
    bus = events.Bus()
    alertas = alerts.Alertas(
        bus,
        lambda: estado,
        perfil_de_la_nave,
        config,
        base,
        escritor,
        Timbre(),
        reloj=lambda: ahora["valor"],
        copiar=lambda texto: copiados.append(texto) or True,
    )
    return alertas, bus, copiados, ahora


def despegar_de(bus: events.Bus, market_id: int) -> None:
    estacion = Estacion(nombre="X", market_id=market_id, tipo="Coriolis")
    bus.publicar(events.ATRACADO, estacion)
    bus.publicar(events.DESATRACADO, estacion)


def test_al_despegar_se_copia_el_sistema_de_la_parada_siguiente(base, escritor, tmp_path):
    alertas, bus, copiados, _ = preparar_despegue(base, escritor, tmp_path, portapapeles=True)
    alertas.iniciar()
    try:
        despegar_de(bus, ANTONELLI)

        assert esperar(lambda: copiados == ["Orishpucho"], segundos=1.5)
    finally:
        alertas.detener()


def test_el_primer_despegue_tras_arrancar_atracado_tambien_copia(base, escritor, tmp_path):
    """LUNA arrancó con el comandante atracado: no hubo ATRACADO antes del despegue (E-30)."""
    alertas, bus, copiados, _ = preparar_despegue(base, escritor, tmp_path, portapapeles=True)
    alertas.iniciar()
    try:
        bus.publicar(
            events.DESATRACADO, Estacion(nombre="X", market_id=ANTONELLI, tipo="Coriolis")
        )

        assert esperar(lambda: copiados == ["Orishpucho"], segundos=1.5)
    finally:
        alertas.detener()


def test_sin_la_opcion_no_se_copia_nada(base, escritor, tmp_path):
    alertas, bus, copiados, _ = preparar_despegue(base, escritor, tmp_path, portapapeles=False)
    alertas.iniciar()
    try:
        despegar_de(bus, ANTONELLI)
        time.sleep(0.4)

        assert copiados == []
    finally:
        alertas.detener()


def test_un_despegue_de_mas_de_60_segundos_no_se_copia(base, escritor, tmp_path):
    alertas, _, copiados, ahora = preparar_despegue(base, escritor, tmp_path, portapapeles=True)
    viejo = Despegue(ANTONELLI, FIN_DEL_BUCLE - timedelta(seconds=61))

    alertas._copiar_destino(viejo)

    assert copiados == []
    alertas._copiar_destino(Despegue(ANTONELLI, FIN_DEL_BUCLE - timedelta(seconds=59)))
    assert copiados == ["Orishpucho"]
    assert ahora["valor"] == FIN_DEL_BUCLE


def test_de_una_estacion_que_no_es_de_la_ruta_no_se_copia(base, escritor, tmp_path):
    alertas, _, copiados, _ = preparar_despegue(base, escritor, tmp_path, portapapeles=True)

    alertas._copiar_destino(Despegue(COBALTO, FIN_DEL_BUCLE))

    assert copiados == []


def test_si_el_portapapeles_falla_no_se_rompe_el_hilo(base, escritor, tmp_path, caplog):
    alertas, _, _, _ = preparar_despegue(base, escritor, tmp_path, portapapeles=True)
    alertas._copiar = lambda _: False

    alertas._copiar_destino(Despegue(ANTONELLI, FIN_DEL_BUCLE))

    assert "Orishpucho" not in caplog.text
