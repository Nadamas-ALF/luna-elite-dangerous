import math
import sqlite3

import pytest

from core.db import esquema
from core.journal import tiempos as tramos
from modules.comercio import timing
from modules.comercio.timing import Tiempos, Valor

FID = "F0000001"


@pytest.fixture
def conexion():
    conexion = sqlite3.connect(":memory:", isolation_level=None)
    esquema.migrar(conexion)
    conexion.execute("INSERT INTO commanders VALUES (?, 'CMDR Prueba', '2026-11-14')", (FID,))
    yield conexion
    conexion.close()


def guardar(conexion, tramo, segundos, ship_id=14, distancia_ls=None, fid=FID):
    for i, valor in enumerate(segundos):
        conexion.execute(
            "INSERT INTO timing_samples VALUES (?, ?, ?, ?, ?, ?)",
            (
                fid,
                ship_id,
                tramo,
                f"2026-11-14T10:{i // 60:02d}:{i % 60:02d}Z",
                valor,
                distancia_ls,
            ),
        )


def test_el_supercrucero_por_defecto_sigue_el_ajuste_de_los_journals():
    assert timing.supercrucero_por_defecto(0) == pytest.approx(110)
    assert timing.supercrucero_por_defecto(100) == pytest.approx(110 + 32 * math.log(2))


def test_un_tramo_es_salida_mas_los_saltos_que_quedan_supercrucero_atraque_y_comercio():
    orbital = timing.POR_DEFECTO.tramo(3, 0, planetaria=False)

    assert orbital == pytest.approx(100 + 2 * 60 + 110 + 90 + 60)
    assert timing.POR_DEFECTO.tramo(3, 0, planetaria=True) - orbital == pytest.approx(90)


def test_en_el_mismo_sistema_no_hay_salida_ni_saltos():
    assert timing.POR_DEFECTO.tramo(0, 0, planetaria=False) == pytest.approx(110 + 90 + 60)


def test_las_partes_suman_el_tramo_y_dicen_de_donde_salen():
    calibrados = Tiempos(salto=Valor(40.0, timing.FUENTE_NAVE, 34))

    partes = calibrados.partes(4, 1000, planetaria=True)

    assert sum(s for s, _ in partes.values()) == pytest.approx(calibrados.tramo(4, 1000, True))
    assert partes["saltos"] == (120.0, Valor(40.0, timing.FUENTE_NAVE, 34))
    assert partes["atraque"][1] == Valor(timing.APROXIMACION_PLANETARIA)


def test_limpiar_quita_lo_que_pasa_de_tres_veces_la_mediana():
    assert timing.limpiar([10, 20, 30, 91]) == [10, 20, 30]
    assert timing.limpiar([]) == []


def test_la_nave_manda_si_tiene_diez_muestras_limpias():
    nave = [50.0] * 10
    comandante = [70.0] * 30

    assert timing.calibrar(nave, comandante, Valor(60.0)) == Valor(50.0, timing.FUENTE_NAVE, 10)


def test_con_menos_de_diez_en_la_nave_se_usa_el_comandante():
    # Diez muestras de la nave, pero una es una ausencia: quedan nueve limpias.
    nave = [50.0] * 9 + [5000.0]

    valor = timing.calibrar(nave, [70.0] * 12, Valor(60.0))

    assert valor == Valor(70.0, timing.FUENTE_COMANDANTE, 12)


def test_sin_muestras_suficientes_queda_el_valor_por_defecto():
    assert timing.calibrar([50.0] * 3, [50.0] * 9, Valor(60.0)) == Valor(60.0)


def test_cargar_aplica_la_jerarquia_por_tramo(conexion):
    guardar(conexion, tramos.SALTO, [40.0] * 12)
    guardar(conexion, tramos.COMERCIO, [200.0] * 6)
    guardar(conexion, tramos.COMERCIO, [300.0] * 6, ship_id=7)

    calibrados = timing.cargar(conexion, FID, 14)

    assert calibrados.salto == Valor(40.0, timing.FUENTE_NAVE, 12)
    # Seis de esta nave no bastan; las doce del comandante sí.
    assert calibrados.comercio == Valor(250.0, timing.FUENTE_COMANDANTE, 12)
    assert calibrados.salida == Valor(timing.SALIDA)


def test_el_supercrucero_se_calibra_con_un_factor_sobre_la_curva(conexion):
    # Doce llegadas a 100 ls que tardan el doble de lo que dice la curva por defecto.
    guardar(
        conexion,
        tramos.SUPERCRUCERO,
        [2 * timing.supercrucero_por_defecto(100)] * 12,
        distancia_ls=100,
    )

    calibrados = timing.cargar(conexion, FID, 14)

    assert calibrados.supercrucero == Valor(pytest.approx(2.0), timing.FUENTE_NAVE, 12)
    assert calibrados.partes(1, 5000, False)["supercrucero"][0] == pytest.approx(
        2 * timing.supercrucero_por_defecto(5000)
    )


def test_las_muestras_de_otro_comandante_no_cuentan(conexion):
    conexion.execute("INSERT INTO commanders VALUES ('F2', 'Otro', '2026-11-14')")
    guardar(conexion, tramos.SALTO, [40.0] * 12, fid="F2")

    assert timing.cargar(conexion, FID, 14) == timing.POR_DEFECTO


def test_sin_comandante_son_los_de_por_defecto(conexion):
    assert timing.cargar(conexion, None, None) is timing.POR_DEFECTO
