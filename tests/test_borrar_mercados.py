"""Borrar los datos de mercado (prefase 8, bloque 7): solo la zona reconstruible."""

import json
import sqlite3
import time

import pytest

from core.config import ajustes
from core.db import espacio, esquema, retencion
from core.db.escritor import abrir_lectura
from core.db.mercado import Estacion, Sistema, guardar_de_red
from core.esfera import Esfera
from core.spansh import cambio
from tests.test_datos import Montaje

MARCA = "2026-11-16T12:00:00Z"
MERCADOS = 40


@pytest.fixture
def m(tmp_path):
    montaje = Montaje(tmp_path)
    yield montaje
    if montaje.gestor:
        montaje.gestor.cancelar()
        montaje.gestor.detener()
    montaje.escritor.detener()


def sembrar_mercados(conexion: sqlite3.Connection, cantidad: int = MERCADOS) -> None:
    for i in range(1, cantidad + 1):
        conexion.execute(
            "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, actualizado, "
            "fuente) VALUES (?, ?, ?, 0, 0, ?, ?, 'spansh')",
            (i, f"S{i}", float(i), float(i), MARCA),
        )
        conexion.execute(
            "INSERT INTO stations (market_id, system_address, nombre, categoria, planetaria, "
            "actualizado) VALUES (?, ?, ?, 'orbital', 0, ?)",
            (i, i, f"E{i}", MARCA),
        )
        conexion.execute(
            "INSERT INTO market_prices VALUES (?, 'gold', 0, 9000, 5, 100, 0, 3, 'eddn', ?)",
            (i, MARCA),
        )


def sembrar_comandante(conexion: sqlite3.Connection) -> None:
    conexion.execute("INSERT INTO commanders VALUES ('F1', 'Jose', ?)", (MARCA,))
    conexion.execute(
        "INSERT INTO trades (fid, marca, market_id, commodity, venta, cantidad, estacion, sistema,"
        " precio, total) VALUES ('F1', ?, 3, 'gold', 1, 10, 'E3', 'S3', 9000, 90000)",
        (MARCA,),
    )
    conexion.execute(
        "INSERT INTO pinned_routes (clave, cerrada, paradas, creada) VALUES ('a|b', 1, '[]', ?)",
        (MARCA,),
    )
    conexion.execute(
        "INSERT INTO alert_rules VALUES (1, 1, 1000, 1000, 50, 24, 30, 20)",
    )


def filas(conexion: sqlite3.Connection, tabla: str) -> int:
    return conexion.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]  # noqa: S608


def tablas_del_comandante(conexion: sqlite3.Connection) -> dict[str, int]:
    """Todas las tablas menos las tres de mercado y las de catálogo."""
    nombres = [
        n
        for (n,) in conexion.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        if n not in {"systems", "stations", "market_prices", "commodities"}
    ]
    return {n: filas(conexion, n) for n in nombres}


@pytest.fixture
def base():
    conexion = sqlite3.connect(":memory:", isolation_level=None)
    conexion.execute("PRAGMA foreign_keys = ON")
    esquema.migrar(conexion)
    yield conexion
    conexion.close()


def vaciar(base, lote):
    llamadas = 0
    while retencion.borrar_mercados(base, lote):
        llamadas += 1
        assert llamadas < 1000
    return llamadas


def test_vacia_los_mercados_por_lotes_y_no_toca_nada_del_comandante(base):
    sembrar_mercados(base)
    sembrar_comandante(base)
    antes = tablas_del_comandante(base)
    assert antes["pinned_routes"] == 1
    llamadas = vaciar(base, lote=7)
    assert llamadas > 1  # de verdad fue por lotes
    for tabla in ("systems", "stations", "market_prices"):
        assert filas(base, tabla) == 0
    assert tablas_del_comandante(base) == antes
    assert base.execute("PRAGMA foreign_key_check").fetchall() == []


def test_un_lote_no_borra_mas_estaciones_de_las_que_se_le_piden(base):
    sembrar_mercados(base)
    assert retencion.borrar_mercados(base, lote=5) is True
    assert filas(base, "stations") == MERCADOS - 5
    assert filas(base, "systems") == MERCADOS  # los sistemas esperan a que no queden estaciones


def test_vaciar_una_base_vacia_no_pide_otra_vuelta(base):
    assert retencion.borrar_mercados(base) is False


def test_el_borrado_conserva_el_sistema_del_centro_sin_sus_estaciones(base):
    """Sin él no se podría revisar la esfera por su nombre hasta volver a verlo (E-37)."""
    sembrar_mercados(base)
    while retencion.borrar_mercados(base, 7, conservar="s3"):
        pass
    assert base.execute("SELECT nombre FROM systems").fetchall() == [("S3",)]
    assert filas(base, "stations") == 0


def test_el_borrado_conserva_el_catalogo_de_mercancias(base):
    base.execute("INSERT INTO commodities (simbolo, nombre_en) VALUES ('gold', 'Gold')")
    antes = filas(base, "commodities")
    sembrar_mercados(base)
    vaciar(base, lote=10)
    assert filas(base, "commodities") == antes


def esperar_fin(m, tiempo=15.0):
    limite = time.monotonic() + tiempo
    while time.monotonic() < limite:
        if not m.datos.espacio()["borrando"]:
            m.escritor.encolar(lambda c: None)  # tras la cola, el espacio devuelto ya está hecho
            return
        time.sleep(0.01)
    pytest.fail("el borrado no terminó")


def sembrar_en_el_escritor(m, trabajo):
    hecho = []
    m.escritor.encolar(trabajo, hecho.append)
    limite = time.monotonic() + 15
    while not hecho and time.monotonic() < limite:
        time.sleep(0.01)
    assert hecho


def leer(m, consulta):
    conexion = abrir_lectura(m.base)
    try:
        return conexion.execute(consulta).fetchall()
    finally:
        conexion.close()


def test_borrar_deja_la_base_integra_sin_mercados_y_con_el_comandante_intacto(m):
    sembrar_en_el_escritor(m, lambda c: (sembrar_mercados(c, 200), sembrar_comandante(c)))
    antes = leer(m, "SELECT * FROM pinned_routes")
    assert m.datos.borrar_mercados() == {"ok": True}
    esperar_fin(m)
    assert leer(m, "SELECT count(*) FROM stations") == [(0,)]
    assert leer(m, "SELECT count(*) FROM systems") == [(0,)]
    assert leer(m, "SELECT count(*) FROM market_prices") == [(0,)]
    assert leer(m, "SELECT * FROM pinned_routes") == antes
    assert leer(m, "SELECT count(*) FROM trades") == [(1,)]
    assert leer(m, "PRAGMA integrity_check") == [("ok",)]
    assert leer(m, "PRAGMA foreign_key_check") == []


def test_el_archivo_encoge_tras_borrar(m):
    # Precios con relleno para que la base pese de verdad.
    def sembrar(c):
        sembrar_mercados(c, 3000)
        c.execute("UPDATE stations SET nombre = nombre || printf('%.300c', 'x')")

    sembrar_en_el_escritor(m, sembrar)
    grande = m.datos.espacio()["base"]
    assert m.datos.borrar_mercados() == {"ok": True}
    esperar_fin(m)
    limite = time.monotonic() + 15
    while time.monotonic() < limite and m.datos.espacio()["base"] >= grande * 0.5:
        time.sleep(0.05)
    assert m.datos.espacio()["base"] < grande * 0.5


def test_eddn_vuelve_a_llenar_la_base_sin_reiniciar(m):
    sistema = Sistema(77, "Lugar", (1.0, 2.0, 3.0), 3.7)
    estacion = Estacion(770, "Puerto", "orbital", "L", 100.0, False)
    sembrar_en_el_escritor(m, lambda c: sembrar_mercados(c, 5))
    m.datos.borrar_mercados()
    esperar_fin(m)
    # Lo mismo que hace la ingesta con un sistema que sigue en su caché tras el borrado.
    sembrar_en_el_escritor(
        m, lambda c: guardar_de_red(c, sistema, estacion, (), "eddn", MARCA)
    )
    assert leer(m, "SELECT market_id FROM stations") == [(770,)]
    assert leer(m, "SELECT nombre FROM systems") == [("Lugar",)]


def test_olvida_la_ultima_descarga_y_ya_no_se_da_por_cubierta_la_esfera(m):
    m.datos.aplicar_esfera("Sol", 100, True)
    m.gestor._hilo.join(15)
    assert m.datos.spansh()["ultima"] is not None
    assert m.datos.proponer_esfera("Sol", 50)["descarga_necesaria"] is False
    assert m.datos.borrar_mercados() == {"ok": True}
    esperar_fin(m)
    assert m.datos.spansh()["ultima"] is None
    assert ajustes.ultima_descarga(m.config) is None
    assert m.datos.proponer_esfera("Sol", 50)["descarga_necesaria"] is True


def test_el_resto_de_la_configuracion_sobrevive_al_borrado(m):
    m.datos.guardar_retencion(5, 20)
    m.datos.aplicar_esfera("Sol", 100, True)
    m.gestor._hilo.join(15)
    m.datos.borrar_mercados()
    esperar_fin(m)
    datos = json.loads(m.config.read_text(encoding="utf-8"))
    assert "spansh" not in datos
    assert datos["retencion"]["visitados_dias"] == 5
    assert datos["esfera"]["radio"] == 100


def test_no_se_borra_con_una_descarga_en_marcha(m):
    m.gestor._fase = "descargando"
    assert m.datos.borrar_mercados() == {"error": "ocupado"}
    assert ajustes.ultima_descarga(m.config) is None  # no se tocó nada


def test_sin_base_no_hay_nada_que_borrar(tmp_path):
    montaje = Montaje(tmp_path, con_gestor=False, con_base=False)
    try:
        assert montaje.datos.borrar_mercados() == {"error": "sin_base"}
    finally:
        montaje.escritor.detener()


def test_si_no_se_puede_guardar_la_configuracion_no_se_borra_nada(m, monkeypatch):
    sembrar_en_el_escritor(m, lambda c: sembrar_mercados(c, 5))
    m.datos.aplicar_esfera("Sol", 100, True)
    m.gestor._hilo.join(15)
    monkeypatch.setattr(ajustes, "olvidar_ultima_descarga", lambda _: False)
    assert m.datos.borrar_mercados() == {"error": "no_guardado"}
    assert leer(m, "SELECT count(*) FROM stations")[0][0] >= 5


def test_un_borrado_en_marcha_impide_cambiar_la_esfera_y_otro_borrado(m):
    m.mantenimiento._borrado = "borrando"
    assert m.datos.borrar_mercados() == {"error": "ocupado"}
    assert m.datos.aplicar_esfera("Sol", 50, False) == {"error": "ocupado"}
    assert m.datos.reanudar() == {"error": "ocupado"}
    assert m.datos.proponer_esfera("Sol", 50)["ocupado"] is True


def test_el_espacio_cuenta_la_base_y_las_descargas(m):
    (m.datos._carpeta).mkdir(parents=True, exist_ok=True)
    (m.datos._carpeta / "pendiente.part").write_bytes(b"x" * 1234)
    espacio = m.datos.espacio()
    assert espacio["descargas"] == 1234
    assert espacio["base"] > 0
    assert espacio["libre"] > 0
    assert espacio["borrando"] is False
    assert espacio["borrado_fallido"] is False


def test_un_borrado_que_falla_se_dice_y_se_puede_repetir(m, monkeypatch):
    def roto(conexion, lote=0):
        raise sqlite3.OperationalError("disco")

    monkeypatch.setattr(retencion, "borrar_mercados", roto)
    assert m.datos.borrar_mercados() == {"ok": True}
    limite = time.monotonic() + 10
    while time.monotonic() < limite and not m.datos.espacio()["borrado_fallido"]:
        time.sleep(0.01)
    assert m.datos.espacio()["borrado_fallido"] is True
    assert m.datos.espacio()["borrando"] is False
    monkeypatch.undo()
    assert m.datos.borrar_mercados() == {"ok": True}
    esperar_fin(m)


def test_la_cadena_de_una_limpieza_no_da_el_borrado_por_terminado(m):
    m.mantenimiento._borrado = "borrando"
    m.mantenimiento._seguir_devolviendo((10, 0))
    m.escritor.encolar(lambda c: None)
    time.sleep(0.3)
    assert m.datos.espacio()["borrando"] is True


def test_un_fallo_al_vaciar_el_wal_no_se_presenta_como_terminado(m, monkeypatch):
    def roto(conexion):
        raise sqlite3.OperationalError("bloqueado")

    monkeypatch.setattr(espacio, "truncar_wal", roto)
    assert m.datos.borrar_mercados() == {"ok": True}
    limite = time.monotonic() + 10
    while time.monotonic() < limite and not m.datos.espacio()["borrado_fallido"]:
        time.sleep(0.01)
    assert m.datos.espacio()["borrado_fallido"] is True
    assert m.datos.espacio()["borrando"] is False


def test_tras_borrar_se_puede_revisar_la_esfera_por_el_nombre_de_su_centro(m):
    m.esfera.cambiar(Esfera("S5", (5.0, 0.0, 0.0), 50.0))
    sembrar_en_el_escritor(m, lambda c: sembrar_mercados(c, 20))
    assert m.datos.borrar_mercados() == {"ok": True}
    esperar_fin(m)

    assert leer(m, "SELECT count(*) FROM stations") == [(0,)]
    assert cambio.resolver_centro(m.base, "S5").centro == (5.0, 0.0, 0.0)

