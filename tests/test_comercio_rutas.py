import pytest

from modules.comercio import timing
from modules.comercio.engine import ahora, candidatos, rutas
from modules.comercio.engine.ahora import Carga
from modules.comercio.engine.calculo import Curva
from tests.mercado_de_prueba import (
    AHORA,
    base_vacia,
    compra,
    estacion,
    perfil,
    sistema,
    vende,
    vende_y_compra,
)

ORIGEN = (0.0, 0.0, 0.0)
CURVA = Curva()


@pytest.fixture
def base():
    conexion = base_vacia()
    yield conexion
    conexion.close()


def cargar(base, p):
    return candidatos.cargar(base, p, ORIGEN, AHORA)


def un_salto(base, **cambios):
    p = perfil(**cambios)
    return rutas.un_salto(cargar(base, p), p, CURVA, timing.POR_DEFECTO)


def test_un_salto_calcula_los_pasos_de_la_seccion_7_2(base):
    estacion(base, 1, sistema(base, 10, 0), ls=100)
    estacion(base, 2, sistema(base, 20, 30), ls=1000)
    vende(base, 1, "gold", 9000, stock=500)
    compra(base, 2, "gold", 10_000, demanda=80)
    [tramo] = un_salto(base, capacidad=100, rango=20.0)
    assert tramo.ganancia_tonelada == 1000
    assert tramo.toneladas == 80
    assert tramo.ganancia_viaje == 80_000
    assert tramo.saltos == 2
    assert tramo.distancia_ly == pytest.approx(30)
    assert tramo.segundos == pytest.approx(timing.POR_DEFECTO.tramo(2, 1000, planetaria=False))
    assert tramo.ganancia_hora == pytest.approx(80_000 * 3600 / tramo.segundos)
    assert tramo.confianza == 1.0
    assert tramo.puntuacion == tramo.ganancia_hora


def test_sin_ganancia_o_en_la_misma_estacion_no_hay_ruta(base):
    estacion(base, 1, sistema(base, 10, 0))
    estacion(base, 2, sistema(base, 20, 10))
    vende_y_compra(base, 1, "gold", 9000, 12_000)
    compra(base, 2, "gold", 9000)
    assert un_salto(base) == []


def test_sin_creditos_para_una_tonelada_no_hay_ruta(base):
    estacion(base, 1, sistema(base, 10, 0))
    estacion(base, 2, sistema(base, 20, 10))
    vende(base, 1, "gold", 9000)
    compra(base, 2, "gold", 12_000)
    assert un_salto(base, creditos=8999) == []
    assert un_salto(base, creditos=18_000)[0].toneladas == 2


def test_el_mas_cercano_gana_si_paga_casi_lo_mismo(base):
    estacion(base, 1, sistema(base, 10, 0))
    estacion(base, 2, sistema(base, 20, 5))
    estacion(base, 3, sistema(base, 30, 45))
    vende(base, 1, "gold", 9000)
    compra(base, 2, "gold", 10_000)
    compra(base, 3, "gold", 10_100)
    rutas_ = un_salto(base)
    assert [r.venta.estacion.market_id for r in rutas_] == [2, 3]
    por_viaje = un_salto(base, orden="ganancia_viaje")
    assert por_viaje[0].venta.estacion.market_id == 3


def test_un_dato_viejo_baja_la_puntuacion_pero_no_la_ganancia_por_hora(base):
    estacion(base, 1, sistema(base, 10, 0))
    estacion(base, 2, sistema(base, 20, 5))
    vende(base, 1, "gold", 9000, horas=0.5)
    compra(base, 2, "gold", 10_000, horas=12.5)
    [tramo] = un_salto(base)
    assert tramo.confianza == pytest.approx(0.75)
    assert tramo.puntuacion == pytest.approx(tramo.ganancia_hora * 0.75)


def test_el_bucle_exige_ganancia_en_los_dos_sentidos(base):
    for market_id, x in ((1, 0), (2, 10), (3, 20)):
        estacion(base, market_id, sistema(base, market_id * 10, x))
    vende(base, 1, "gold", 9000)
    compra(base, 2, "gold", 10_000)
    compra(base, 3, "gold", 10_000)
    vende(base, 2, "silver", 4000)
    compra(base, 1, "silver", 4500)
    [bucle] = rutas.bucle(cargar(base, perfil()), perfil(), CURVA, timing.POR_DEFECTO)
    assert bucle.ida.compra.mercancia == "gold"
    assert bucle.vuelta.compra.mercancia == "silver"
    assert {bucle.ida.compra.estacion.market_id, bucle.vuelta.compra.estacion.market_id} == {1, 2}
    assert bucle.ganancia_viaje == 100 * 1000 + 100 * 500
    assert bucle.segundos == pytest.approx(bucle.ida.segundos + bucle.vuelta.segundos)


def test_la_vuelta_se_busca_entre_todas_las_mercancias_no_solo_las_mejores(base, monkeypatch):
    monkeypatch.setattr(rutas, "K_POR_MERCANCIA", 1)
    for market_id, x in ((1, 0), (2, 10), (3, 0.1)):
        estacion(base, market_id, sistema(base, market_id * 10, x))
    vende(base, 1, "gold", 9000)
    compra(base, 2, "gold", 10_000)
    # La plata de 2 no es la más barata: con K = 1 solo se empareja la de 3.
    vende(base, 2, "silver", 4000)
    vende(base, 3, "silver", 3000)
    compra(base, 1, "silver", 4500)
    bucles = rutas.bucle(cargar(base, perfil()), perfil(), CURVA, timing.POR_DEFECTO)
    assert any(b.vuelta.compra.estacion.market_id == 2 for b in bucles)


def test_una_pareja_aparece_una_sola_vez_en_los_bucles(base):
    estacion(base, 1, sistema(base, 10, 0))
    estacion(base, 2, sistema(base, 20, 10))
    vende(base, 1, "gold", 9000)
    compra(base, 2, "gold", 10_000)
    vende(base, 2, "silver", 4000)
    compra(base, 1, "silver", 4500)
    assert len(rutas.bucle(cargar(base, perfil()), perfil(), CURVA, timing.POR_DEFECTO)) == 1


def test_desde_aqui_empareja_el_mercado_actual_con_los_compradores_del_radio(base):
    estacion(base, 1, sistema(base, 10, 0), plataforma=None)  # donde estás
    estacion(base, 2, sistema(base, 20, 10))
    vende_y_compra(base, 1, "gold", 9000, 11_000)
    compra(base, 2, "gold", 10_000)
    p = perfil()
    ofertas = candidatos.ofertas_de_la_estacion(base, 1, p, AHORA)
    [tramo] = ahora.desde_aqui(cargar(base, p), ofertas, p, CURVA, timing.POR_DEFECTO)
    assert tramo.venta.estacion.market_id == 2


def test_vender_carga_ordena_por_ingreso_y_da_la_ganancia_solo_si_se_sabe_lo_pagado(base):
    estacion(base, 2, sistema(base, 20, 10))
    estacion(base, 3, sistema(base, 30, 15))
    compra(base, 2, "gold", 10_000, demanda=50)
    compra(base, 3, "gold", 9_500)
    compra(base, 2, "silver", 5000)
    p = perfil()
    carga = [Carga("gold", 100, 9000), Carga("silver", 10, None), Carga("tea", 5, None)]
    ventas = ahora.vender_carga(cargar(base, p), carga, ORIGEN, p, CURVA, timing.POR_DEFECTO)
    oro = ventas["gold"]
    assert [v.venta.estacion.market_id for v in oro] == [3, 2]
    assert oro[0].toneladas == 100
    assert oro[0].ingreso == 950_000
    assert oro[0].ganancia == 50_000
    assert oro[1].toneladas == 50
    assert ventas["silver"][0].ganancia is None
    assert ventas["tea"] == []


def test_tramos_con_una_estacion_la_toman_como_compra_y_como_venta(base):
    estacion(base, 1, sistema(base, 10, 0))
    estacion(base, 2, sistema(base, 20, 5))
    estacion(base, 3, sistema(base, 30, 8))
    vende(base, 1, "gold", 9000)
    compra(base, 2, "gold", 10_000)
    vende(base, 3, "silver", 4000)
    compra(base, 1, "silver", 4500)
    p = perfil()
    cargados = cargar(base, p)

    tramos = rutas.tramos_con(cargados, 1, p, CURVA, timing.POR_DEFECTO)

    assert sorted((t.compra.estacion.market_id, t.venta.estacion.market_id) for t in tramos) == [
        (1, 2),
        (3, 1),
    ]
    assert rutas.tramos_con(cargados, 2, p, CURVA, timing.POR_DEFECTO)[0].compra.mercancia == "gold"


def test_tramos_con_una_estacion_no_recorta_a_los_mejores(base):
    estacion(base, 1, sistema(base, 10, 0))
    vende(base, 1, "gold", 9000)
    for n in range(2, 2 + rutas.K_POR_MERCANCIA + 5):
        estacion(base, n, sistema(base, 10 * n, 1 + n * 0.1))
        compra(base, n, "gold", 9_100 + n)
    p = perfil()

    tramos = rutas.tramos_con(cargar(base, p), 1, p, CURVA, timing.POR_DEFECTO)

    assert len(tramos) == rutas.K_POR_MERCANCIA + 5


def test_bucles_con_una_estacion(base):
    estacion(base, 1, sistema(base, 10, 0))
    estacion(base, 2, sistema(base, 20, 5))
    estacion(base, 3, sistema(base, 30, 8))
    vende(base, 1, "gold", 9000)
    compra(base, 2, "gold", 10_000)
    vende(base, 2, "silver", 4000)
    compra(base, 1, "silver", 4500)
    compra(base, 3, "gold", 9500)
    p = perfil()

    bucles = rutas.bucles_con(cargar(base, p), 1, p, CURVA, timing.POR_DEFECTO)

    puntas = [(b.ida.venta.estacion.market_id, b.vuelta.compra.estacion.market_id) for b in bucles]
    assert puntas == [(2, 2)]
