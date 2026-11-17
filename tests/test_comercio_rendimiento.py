"""Objetivo de la sección 7.3: un salto y bucle A↔B en menos de 2 s.

La base sintética imita lo que da la base real con el perfil por defecto (50 ly,
24 h): unas 10 000 estaciones en el radio, 1 500 con mercado reciente y unos
30 000 precios (medido el 2026-11-13: 9 574 estaciones y 28 491 precios).
"""

import random
import time

import pytest

from core.config import ajustes
from modules.comercio import timing
from modules.comercio.engine import cadenas, candidatos, rutas
from modules.comercio.engine.calculo import Curva
from tests.mercado_de_prueba import AHORA, base_vacia, hace, perfil

ESTACIONES = 10_000
CON_MERCADO = 1_500
MERCANCIAS = [f"m{n}" for n in range(120)]
PRECIOS_POR_MERCADO = 20
LIMITE = 2.0
LIMITE_VARIAS_PARADAS = 10.0


@pytest.fixture(scope="module")
def base():
    azar = random.Random(5)  # noqa: S311 - datos de prueba repetibles, no criptografía
    conexion = base_vacia()
    sistemas = [
        (n, f"S{n}", *(azar.uniform(-35, 35) for _ in range(3)), 0, hace(0)) for n in range(4_000)
    ]
    conexion.executemany(
        "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, actualizado) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        sistemas,
    )
    conexion.executemany(
        "INSERT INTO stations VALUES (?, ?, ?, 'orbital', 'L', ?, 0, ?)",
        [
            (m, azar.randrange(4_000), f"E{m}", azar.uniform(10, 4000), hace(0))
            for m in range(ESTACIONES)
        ],
    )
    conexion.executemany(
        "INSERT INTO market_prices VALUES (?, ?, ?, ?, ?, ?, -1, -1, 'spansh', ?)",
        [fila for m in range(CON_MERCADO) for fila in _mercado(azar, m)],
    )
    yield conexion
    conexion.close()


def _mercado(azar: random.Random, market_id: int) -> list[tuple]:
    observado = hace(azar.uniform(0, 23))
    filas = []
    for mercancia in azar.sample(MERCANCIAS, PRECIOS_POR_MERCADO):
        referencia = 1000 + MERCANCIAS.index(mercancia) * 100
        cantidad = azar.randrange(1, 20_000)
        if azar.random() < 0.4:
            compra, venta, stock, demanda = int(referencia * azar.uniform(0.7, 1)), 0, cantidad, 0
        else:
            compra, venta, stock, demanda = 0, int(referencia * azar.uniform(0.9, 1.4)), 0, cantidad
        filas.append((market_id, mercancia, compra, venta, stock, demanda, observado))
    return filas


@pytest.mark.parametrize("modo", [rutas.un_salto, rutas.bucle], ids=["un_salto", "bucle"])
def test_un_salto_y_bucle_responden_en_menos_de_2_s(base, modo):
    p = perfil(capacidad=720, rango=25.0, distancia_max_ly=50)
    inicio = time.perf_counter()
    resultado = modo(
        candidatos.cargar(base, p, (0.0, 0.0, 0.0), AHORA), p, Curva(), timing.POR_DEFECTO
    )
    duracion = time.perf_counter() - inicio
    assert resultado, "la base sintética tiene que dar rutas"
    assert duracion < LIMITE, f"{duracion:.2f} s"


@pytest.mark.parametrize("modo", [cadenas.cadena, cadenas.circuito], ids=["cadena", "circuito"])
def test_seis_paradas_responden_en_menos_de_10_s_y_sin_cortar_con_el_limite_por_defecto(base, modo):
    p = perfil(capacidad=720, rango=25.0, distancia_max_ly=50)
    inicio = time.perf_counter()
    cargados = candidatos.cargar(base, p, (0.0, 0.0, 0.0), AHORA)
    limite = cadenas.Limite(time.monotonic() + ajustes.LIMITE_BUSQUEDA_S_POR_DEFECTO)
    resultados, cortada = modo(cargados, p, Curva(), timing.POR_DEFECTO, 6, limite)
    duracion = time.perf_counter() - inicio
    assert resultados, "la base sintética tiene que dar rutas"
    assert not cortada
    assert duracion < LIMITE_VARIAS_PARADAS, f"{duracion:.2f} s"
