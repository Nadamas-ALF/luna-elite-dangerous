import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.config import ajustes
from core.db import espacio, retencion
from core.db.escritor import Escritor, abrir_lectura
from core.esfera import Esfera, EsferaViva
from core.mantenimiento import Mantenimiento

AHORA = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)
SOL = Esfera("Sol", (0.0, 0.0, 0.0), 100.0)


@pytest.fixture
def escritor(tmp_path):
    activo = Escritor(tmp_path / "luna.db")
    activo.iniciar()
    yield activo
    activo.detener()


def sembrar(escritor, x: float, observado: str = "2026-11-13T11:00:00Z") -> None:
    def trabajo(conexion):
        conexion.execute(
            "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, "
            "actualizado) VALUES (10, 'S', ?, 0, 0, 0, ?)",
            (x, observado),
        )
        conexion.execute(
            "INSERT INTO stations VALUES (1, 10, 'E', 'orbital', 'L', 5, 0, ?)", (observado,)
        )
        conexion.execute(
            "INSERT INTO market_prices VALUES (1, 'gold', 0, 9000, 0, 100, 0, 3, 'eddn', ?)",
            (observado,),
        )

    escritor.encolar(trabajo)


def precios(ruta: Path) -> int:
    conexion = abrir_lectura(ruta)
    try:
        return conexion.execute("SELECT count(*) FROM market_prices").fetchone()[0]
    finally:
        conexion.close()


def montar(escritor, tmp_path, esfera=SOL, intervalo=3600.0) -> Mantenimiento:
    return Mantenimiento(
        escritor, EsferaViva(esfera), tmp_path / "config.json", intervalo, lambda: AHORA
    )


def test_la_esfera_viva_reparte_el_cambio_a_quien_la_consulta():
    viva = EsferaViva(SOL)
    assert viva.contiene((50.0, 0.0, 0.0))
    viva.cambiar(Esfera("Lejos", (1000.0, 0.0, 0.0), 10.0))
    assert not viva.contiene((50.0, 0.0, 0.0))
    assert viva.distancia((1000.0, 3.0, 4.0)) == pytest.approx(5.0)
    assert viva.actual.nombre == "Lejos"


def test_limpiar_encola_la_limpieza_con_la_esfera_vigente(escritor, tmp_path):
    sembrar(escritor, x=500.0)
    manto = montar(escritor, tmp_path)
    manto.limpiar()
    escritor.detener()
    assert precios(tmp_path / "luna.db") == 0


def test_dentro_de_la_esfera_no_borra(escritor, tmp_path):
    sembrar(escritor, x=50.0)
    montar(escritor, tmp_path).limpiar()
    escritor.detener()
    assert precios(tmp_path / "luna.db") == 1


def test_usa_los_dias_de_retencion_del_usuario(escritor, tmp_path):
    (tmp_path / "config.json").write_text('{"retencion": {"antiguedad_maxima_dias": 0.01}}')
    sembrar(escritor, x=50.0)
    montar(escritor, tmp_path).limpiar()
    escritor.detener()
    assert precios(tmp_path / "luna.db") == 0


def test_al_arrancar_limpia_y_recalcula_las_distancias(escritor, tmp_path):
    sembrar(escritor, x=500.0)
    manto = montar(escritor, tmp_path, intervalo=0.05)
    manto.iniciar()
    hecho = threading.Event()
    escritor.encolar(lambda c: None, lambda _: hecho.set())
    assert hecho.wait(5)
    manto.detener()
    escritor.detener()
    assert precios(tmp_path / "luna.db") == 0


def test_repite_la_limpieza_con_el_intervalo(escritor, tmp_path):
    manto = montar(escritor, tmp_path, intervalo=0.05)
    llamadas = []
    original = manto.limpiar
    manto.limpiar = lambda: (llamadas.append(1), original())
    manto.iniciar()
    for _ in range(100):
        if len(llamadas) >= 2:
            break
        threading.Event().wait(0.05)
    manto.detener()
    assert len(llamadas) >= 2


def test_detener_corta_la_espera(escritor, tmp_path):
    manto = montar(escritor, tmp_path, intervalo=3600.0)
    manto.iniciar()
    manto.detener()
    assert not manto._hilo.is_alive()


def test_cambiar_la_esfera_y_aplicar_borra_lo_que_queda_fuera(escritor, tmp_path):
    sembrar(escritor, x=50.0)
    viva = EsferaViva(SOL)
    manto = Mantenimiento(escritor, viva, tmp_path / "config.json", 3600.0, lambda: AHORA)
    viva.cambiar(Esfera("Otro", (900.0, 0.0, 0.0), 10.0))
    manto.aplicar_esfera()
    escritor.detener()
    assert precios(tmp_path / "luna.db") == 0


def test_ajustes_de_retencion_por_defecto(tmp_path):
    config = tmp_path / "config.json"
    assert ajustes.dias_de_mercados_visitados(config) == 3.0
    assert ajustes.antiguedad_maxima_de_precios(config) == 30.0


@pytest.mark.parametrize("valor", [0, -1, "3", True, None, 1e9, float("inf")], ids=repr)
def test_los_dias_invalidos_caen_al_valor_por_defecto(tmp_path, valor):
    config = tmp_path / "config.json"
    texto = json.dumps({"retencion": {"visitados_dias": valor}}).replace("Infinity", "1e999")
    config.write_text(texto)
    assert ajustes.dias_de_mercados_visitados(config) == 3.0


def test_guardar_la_esfera_se_lee_igual_y_conserva_el_resto(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"eddn": {"activado": false}}')
    nueva = Esfera("Colonia", (-9530.5, -910.28, 19808.1), 250.0)
    assert ajustes.guardar_esfera(config, nueva)
    assert ajustes.esfera(config) == nueva
    assert ajustes.eddn_activado(config) is False


def test_la_limpieza_encadena_lotes_hasta_terminar(escritor, tmp_path, monkeypatch):
    monkeypatch.setattr(retencion, "LOTE_DE_MERCADOS", 2)
    monkeypatch.setattr(retencion.limpiar, "__defaults__", (2,))
    monkeypatch.setattr(retencion.aplicar_esfera, "__defaults__", (2,))

    def sembrar_muchos(conexion):
        conexion.execute(
            "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, actualizado) "
            "VALUES (10, 'S', 5, 0, 0, 5, '2026-11-13T00:00:00Z')"
        )
        for market_id in range(1, 8):
            conexion.execute(
                "INSERT INTO stations (market_id, system_address, nombre, categoria, planetaria, "
                "actualizado) VALUES (?, 10, 'E', 'orbital', 0, '2020-01-01T00:00:00Z')",
                (market_id,),
            )
            conexion.execute(
                "INSERT INTO market_prices VALUES (?, 'gold', 0, 9, 0, 5, 0, 3, 'spansh', "
                "'2020-01-01T00:00:00Z')",
                (market_id,),
            )

    escritor.encolar(sembrar_muchos)
    montar(escritor, tmp_path).limpiar()
    for _ in range(100):
        if precios(tmp_path / "luna.db") == 0:
            break
        time.sleep(0.05)
    escritor.detener()
    assert precios(tmp_path / "luna.db") == 0


def sembrar_caducados(escritor, cuantos: int) -> None:
    def trabajo(conexion):
        conexion.execute(
            "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, actualizado) "
            "VALUES (10, 'S', 5, 0, 0, 5, '2026-11-13T00:00:00Z')"
        )
        for market_id in range(1, cuantos + 1):
            conexion.execute(
                "INSERT INTO stations (market_id, system_address, nombre, categoria, planetaria, "
                "actualizado) VALUES (?, 10, 'E', 'orbital', 0, '2020-01-01T00:00:00Z')",
                (market_id,),
            )
            conexion.executemany(
                "INSERT INTO market_prices VALUES (?, ?, 0, 9, 0, 5, 0, 3, 'spansh', "
                "'2020-01-01T00:00:00Z')",
                [(market_id, f"mercancia{i}") for i in range(40)],
            )

    escritor.encolar(trabajo)


def test_tras_limpiar_el_espacio_vuelve_al_disco(escritor, tmp_path):
    ruta = tmp_path / "luna.db"
    sembrar_caducados(escritor, 1500)
    escritor.encolar(lambda c: None, lambda _: None)
    montar(escritor, tmp_path).limpiar()
    escritor.encolar(lambda c: c.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall())
    for _ in range(300):
        conexion = abrir_lectura(ruta)
        try:
            libres = conexion.execute("PRAGMA freelist_count").fetchone()[0]
            filas = conexion.execute("SELECT count(*) FROM market_prices").fetchone()[0]
        finally:
            conexion.close()
        if filas == 0 and libres <= espacio.UMBRAL_DE_PAGINAS:
            break
        time.sleep(0.05)
    escritor.detener()
    assert filas == 0
    assert libres <= espacio.UMBRAL_DE_PAGINAS


def test_devolver_espacio_no_entra_en_bucle_si_no_libera_nada(escritor, tmp_path, monkeypatch):
    llamadas = []

    def sin_efecto(conexion, paginas=espacio.LOTE_DE_PAGINAS):
        llamadas.append(1)
        return 5000, 5000

    monkeypatch.setattr(espacio, "devolver", sin_efecto)
    montar(escritor, tmp_path)._devolver_espacio()
    escritor.encolar(lambda c: None)
    time.sleep(0.3)
    escritor.detener()
    assert llamadas == [1]


def sembrar_a(escritor, *distancias: float) -> None:
    """Sistemas de Spansh con un mercado reciente, a las distancias dadas del Sol."""

    def trabajo(conexion):
        for i, x in enumerate(distancias, start=1):
            conexion.execute(
                "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, "
                "actualizado, fuente) VALUES (?, ?, ?, 0, 0, ?, '2026-11-13T00:00:00Z', 'spansh')",
                (i, f"S{i}", x, x),
            )
            conexion.execute(
                "INSERT INTO stations (market_id, system_address, nombre, categoria, planetaria, "
                "actualizado) VALUES (?, ?, 'E', 'orbital', 0, '2026-11-13T00:00:00Z')",
                (i, i),
            )
            conexion.execute(
                "INSERT INTO market_prices VALUES (?, 'gold', 0, 9, 0, 5, 0, 3, 'spansh', "
                "'2026-11-13T00:00:00Z')",
                (i,),
            )

    escritor.encolar(trabajo)


def sistemas(ruta: Path) -> list[str]:
    conexion = abrir_lectura(ruta)
    try:
        return [n for (n,) in conexion.execute("SELECT nombre FROM systems ORDER BY nombre")]
    finally:
        conexion.close()


def esperar_a_que_acabe(escritor, ruta, nombres: list[str]) -> None:
    for _ in range(100):
        escritor.encolar(lambda c: None)
        time.sleep(0.05)
        if sistemas(ruta) == nombres:
            return


def test_con_config_ilegible_no_se_limpia_nada(escritor, tmp_path):
    """El caso real: esfera de 1000 ly, y config.json cerrado o roto en el arranque."""
    ajustes.guardar_esfera(tmp_path / "config.json", Esfera("Sol", (0.0, 0.0, 0.0), 1000.0))
    sembrar_a(escritor, 50.0, 400.0, 900.0)
    (tmp_path / "config.json").write_text('{"esfera": {"radio": 1000,, }', encoding="utf-8")
    viva = EsferaViva(ajustes.esfera(tmp_path / "config.json"), fiable=False)
    assert viva.actual.radio == 100.0

    manto = Mantenimiento(escritor, viva, tmp_path / "config.json", 3600.0, lambda: AHORA)
    manto.aplicar_esfera()
    manto.limpiar()
    escritor.encolar(lambda c: None)
    time.sleep(0.5)
    escritor.detener()

    assert sistemas(tmp_path / "luna.db") == ["S1", "S2", "S3"]


def test_cuando_el_config_vuelve_a_leerse_se_usa_la_esfera_del_usuario(escritor, tmp_path):
    config = tmp_path / "config.json"
    ajustes.guardar_esfera(config, Esfera("Sol", (0.0, 0.0, 0.0), 1000.0))
    sembrar_a(escritor, 50.0, 400.0, 900.0, 1500.0)
    config.write_text("{roto", encoding="utf-8")
    viva = EsferaViva(Esfera("Sol", (0.0, 0.0, 0.0), 100.0), fiable=False)
    manto = Mantenimiento(escritor, viva, config, 3600.0, lambda: AHORA)

    manto.aplicar_esfera()
    assert sistemas(tmp_path / "luna.db") != ["S1"]

    ajustes.guardar_esfera(config, Esfera("Sol", (0.0, 0.0, 0.0), 1000.0))
    manto.aplicar_esfera()
    esperar_a_que_acabe(escritor, tmp_path / "luna.db", ["S1", "S2", "S3"])
    escritor.detener()

    assert viva.actual.radio == 1000.0
    assert viva.fiable
    assert sistemas(tmp_path / "luna.db") == ["S1", "S2", "S3"]


def test_un_config_cerrado_por_otro_programa_tampoco_limpia(escritor, tmp_path, monkeypatch):
    sembrar_a(escritor, 50.0, 900.0)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")

    def cerrado(_):
        raise PermissionError

    monkeypatch.setattr(ajustes.archivo, "leer", cerrado)
    manto = montar(escritor, tmp_path)
    manto.limpiar()
    escritor.encolar(lambda c: None)
    time.sleep(0.4)
    escritor.detener()
    assert sistemas(tmp_path / "luna.db") == ["S1", "S2"]


def test_sin_config_la_primera_vez_si_se_limpia_con_los_valores_por_defecto(escritor, tmp_path):
    sembrar_a(escritor, 50.0, 900.0)
    montar(escritor, tmp_path).aplicar_esfera()
    esperar_a_que_acabe(escritor, tmp_path / "luna.db", ["S1"])
    escritor.detener()
    assert sistemas(tmp_path / "luna.db") == ["S1"]


def test_los_plazos_ilegibles_no_borran_precios_que_el_usuario_quiso_conservar(escritor, tmp_path):
    config = tmp_path / "config.json"
    ajustes.guardar_retencion(config, 3.0, 90.0)

    def precio_de_hace_60_dias(conexion):
        conexion.execute(
            "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, actualizado, "
            "fuente) VALUES (1, 'S1', 5, 0, 0, 5, '2026-09-14T00:00:00Z', 'spansh')"
        )
        conexion.execute(
            "INSERT INTO stations (market_id, system_address, nombre, categoria, planetaria, "
            "actualizado) VALUES (1, 1, 'E', 'orbital', 0, '2026-09-14T00:00:00Z')"
        )
        conexion.execute(
            "INSERT INTO market_prices VALUES (1, 'gold', 0, 9, 0, 5, 0, 3, 'spansh', "
            "'2026-09-14T00:00:00Z')"
        )

    escritor.encolar(precio_de_hace_60_dias)
    config.write_text("no es json", encoding="utf-8")
    montar(escritor, tmp_path).limpiar()
    escritor.encolar(lambda c: None)
    time.sleep(0.4)
    escritor.detener()
    assert precios(tmp_path / "luna.db") == 1


def test_la_esfera_viva_nace_fiable_y_cambiarla_la_hace_fiable():
    assert EsferaViva(SOL).fiable
    viva = EsferaViva(SOL, fiable=False)
    assert not viva.fiable
    viva.cambiar(Esfera("Otro", (1.0, 0.0, 0.0), 5.0))
    assert viva.fiable


@pytest.mark.parametrize(
    ("contenido", "esperado"),
    [
        (None, True),
        ("{}", True),
        ('{"esfera": {"radio": 5}}', True),
        ("{roto", False),
        ("[]", False),
    ],
)
def test_configuracion_legible_distingue_ausente_de_ilegible(tmp_path, contenido, esperado):
    config = tmp_path / "config.json"
    if contenido is not None:
        config.write_text(contenido, encoding="utf-8")
    assert ajustes.configuracion_legible(config) is esperado


def test_configuracion_legible_es_falso_si_el_archivo_esta_cerrado(tmp_path, monkeypatch):
    def cerrado(_):
        raise PermissionError

    monkeypatch.setattr(ajustes.archivo, "leer", cerrado)
    assert ajustes.configuracion_legible(tmp_path / "config.json") is False
