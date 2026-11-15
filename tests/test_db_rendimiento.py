import sqlite3
from dataclasses import replace

import pytest

from core.db import comandante, esquema
from core.journal.sesiones import Bloque


@pytest.fixture
def conexion():
    conexion = sqlite3.connect(":memory:")
    conexion.execute("PRAGMA foreign_keys = ON")
    esquema.migrar(conexion)
    comandante.registrar_comandante(conexion, "F1", "CMDR Prueba", "2026-11-10T00:00:00Z")
    yield conexion
    conexion.close()


def bloque(inicio: str, fin: str, **cambios) -> Bloque:
    datos = {
        "fid": "F1",
        "inicio": f"2026-11-10T{inicio}Z",
        "fin": f"2026-11-10T{fin}Z",
        "partida": "2026-11-10T10:00:00Z",
        "pausa_previa": None,
        "saldo_inicio": 0,
        "saldo_fin": 0,
    }
    return Bloque(**{**datos, **cambios})


def guardadas(conexion) -> list[tuple]:
    return conexion.execute("SELECT inicio, fin, saltos FROM sessions ORDER BY inicio").fetchall()


def test_el_bloque_abierto_se_actualiza_sin_duplicarse(conexion):
    comandante.guardar_bloques(conexion, [bloque("10:00:00", "10:05:00")])
    comandante.guardar_bloques(conexion, [bloque("10:00:00", "10:30:00", saltos=4)])

    assert guardadas(conexion) == [("2026-11-10T10:00:00Z", "2026-11-10T10:30:00Z", 4)]


def test_un_bloque_recortado_dentro_de_uno_guardado_se_descarta(conexion):
    entero = bloque("10:00:00", "12:00:00", saltos=10)
    comandante.guardar_bloques(conexion, [entero])

    comandante.guardar_bloques(conexion, [bloque("11:00:00", "12:00:00", saltos=3)])

    assert guardadas(conexion) == [("2026-11-10T10:00:00Z", "2026-11-10T12:00:00Z", 10)]


def test_un_bloque_entero_sustituye_al_recortado_que_tenia_dentro(conexion):
    comandante.guardar_bloques(conexion, [bloque("11:00:00", "12:00:00", saltos=3)])

    comandante.guardar_bloques(conexion, [bloque("10:00:00", "12:00:00", saltos=10)])

    assert guardadas(conexion) == [("2026-11-10T10:00:00Z", "2026-11-10T12:00:00Z", 10)]


def test_los_bloques_seguidos_de_una_partida_se_guardan_todos(conexion):
    primero = bloque("10:00:00", "10:30:00", cerrado=True)
    segundo = replace(bloque("12:00:00", "12:10:00"), pausa_previa=5400.0)

    comandante.guardar_bloques(conexion, [primero, segundo])

    assert [inicio for inicio, _, _ in guardadas(conexion)] == [
        "2026-11-10T10:00:00Z",
        "2026-11-10T12:00:00Z",
    ]
