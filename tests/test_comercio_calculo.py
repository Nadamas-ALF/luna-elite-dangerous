import math

import pytest

from modules.comercio import timing
from modules.comercio.engine import calculo
from modules.comercio.engine.calculo import Curva


@pytest.mark.parametrize(
    ("capacidad", "stock", "demanda", "creditos", "precio", "esperado"),
    [
        (100, 500, 500, None, 1000, 100),  # manda la bodega
        (100, 40, 500, None, 1000, 40),  # manda el stock
        (100, 500, 25, None, 1000, 25),  # manda la demanda
        (100, 500, 500, 30_500, 1000, 30),  # mandan los créditos, redondeando hacia abajo
        (100, 500, 500, 0, 1000, 0),
    ],
)
def test_toneladas_es_el_minimo_de_los_cuatro_limites(
    capacidad, stock, demanda, creditos, precio, esperado
):
    assert calculo.toneladas(capacidad, stock, demanda, creditos, precio) == esperado


@pytest.mark.parametrize(
    ("distancia", "rango", "esperado"),
    [(0.0, 20.0, 0), (0.1, 20.0, 1), (20.0, 20.0, 1), (20.01, 20.0, 2), (95.0, 32.03, 3)],
)
def test_saltos_redondea_hacia_arriba(distancia, rango, esperado):
    assert calculo.saltos(distancia, rango) == esperado


def test_por_hora():
    assert calculo.por_hora(1_000_000, 1800) == 2_000_000


@pytest.mark.parametrize(
    ("horas", "esperado"), [(0, 1.0), (1, 1.0), (12.5, 0.75), (24, 0.5), (500, 0.5)]
)
def test_la_confianza_baja_en_linea_recta_de_1_h_a_24_h(horas, esperado):
    assert calculo.confianza(horas, Curva()) == pytest.approx(esperado)


@pytest.mark.parametrize(
    "valores", [{"horas_plena": 5, "horas_minima": 5}, {"minimo": 0}, {"minimo": 1.5}]
)
def test_una_curva_sin_sentido_se_rechaza(valores):
    with pytest.raises(ValueError, match="confianza|minimo"):
        Curva(**valores)


def test_el_supercrucero_sigue_el_ajuste_de_los_journals():
    assert timing.supercrucero(0) == pytest.approx(110)
    assert timing.supercrucero(100) == pytest.approx(110 + 32 * math.log(2))
    assert timing.supercrucero(5000) > timing.supercrucero(1000) > timing.supercrucero(100)


def test_un_tramo_suma_saltos_supercrucero_atraque_y_comercio():
    orbital = timing.tramo(3, 0, planetaria=False)
    assert orbital == pytest.approx(3 * 50 + 110 + 90 + 60)
    assert timing.tramo(3, 0, planetaria=True) - orbital == pytest.approx(90)
