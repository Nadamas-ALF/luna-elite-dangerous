"""Varias paradas y Circuito (fase 8): el haz contra la fuerza bruta y sus reglas."""

import itertools
import math
import random

import pytest

from modules.comercio import timing
from modules.comercio.engine import cadenas, candidatos, rutas
from modules.comercio.engine.cadenas import Cadena, Limite
from modules.comercio.engine.calculo import Curva
from modules.comercio.engine.candidatos import BusquedaCancelada
from modules.comercio.engine.tramo import CLAVES
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
REFERENCIAS = {"gold": 9000, "silver": 4000, "iron": 2000, "tin": 1000, "lead": 300}
INFINITO = math.inf


@pytest.fixture
def base():
    conexion = base_vacia()
    yield conexion
    conexion.close()


@pytest.fixture
def haz_ancho(monkeypatch):
    """Un haz que cubre todos los caminos: lo que se prueba es la mecánica, no la heurística."""
    monkeypatch.setattr(cadenas, "ANCHO", 10**6)
    monkeypatch.setattr(cadenas, "VECINOS", 10**6)
    monkeypatch.setattr(cadenas, "POR_SALIDA", 10**6)
    monkeypatch.setattr(rutas, "K_POR_MERCANCIA", 10**6)


def cargar(base, p):
    return candidatos.cargar(base, p, ORIGEN, AHORA)


def limite(**cambios) -> Limite:
    return Limite(**{"fin": INFINITO, **cambios})


def varias_paradas(base, paradas, lim=None, **cambios):
    p = perfil(**cambios)
    return cadenas.cadena(cargar(base, p), p, CURVA, timing.POR_DEFECTO, paradas, lim or limite())


def circuitos(base, paradas, lim=None, **cambios):
    p = perfil(**cambios)
    return cadenas.circuito(cargar(base, p), p, CURVA, timing.POR_DEFECTO, paradas, lim or limite())


def base_al_azar(semilla: int, estaciones: int = 10):
    azar = random.Random(semilla)  # noqa: S311 - datos de prueba repetibles, no criptografía
    conexion = base_vacia()
    for market_id in range(1, estaciones + 1):
        direccion = sistema(conexion, market_id * 10, azar.uniform(0, 40), azar.uniform(0, 40))
        estacion(conexion, market_id, direccion, ls=azar.uniform(50, 2000))
        for mercancia in azar.sample(sorted(REFERENCIAS), 3):
            precio = int(REFERENCIAS[mercancia] * azar.uniform(0.7, 1.1))
            elegido = azar.choice(("vende", "compra", "ambas"))
            if elegido == "vende":
                vende(conexion, market_id, mercancia, precio, stock=azar.randrange(100, 500))
            elif elegido == "compra":
                compra(conexion, market_id, mercancia, precio, demanda=azar.randrange(100, 500))
            else:
                vende_y_compra(conexion, market_id, mercancia, precio, int(precio * 1.15))
    return conexion


def por_fuerza_bruta(base, p, paradas: int, *, cerrada: bool) -> list[Cadena]:
    """Todas las secuencias de `paradas` estaciones distintas con cada tramo en `mejor_entre`."""
    c = cargar(base, p)
    todas = sorted(set(c.ofertas_de) | set(c.demandas_de))
    encontradas = []
    for secuencia in itertools.permutations(todas, paradas):
        pares = list(zip(secuencia, secuencia[1:], strict=False))
        if cerrada:
            pares.append((secuencia[-1], secuencia[0]))
        tramos = [rutas.mejor_entre(c, a, b, p, CURVA, timing.POR_DEFECTO) for a, b in pares]
        if all(t is not None for t in tramos):
            encontradas.append(Cadena(tuple(tramos), cerrada=cerrada))
    return encontradas


def mejor_clave(resultados: list[Cadena], orden: str) -> tuple:
    return min(CLAVES[orden](r) for r in resultados)


@pytest.mark.parametrize("semilla", range(20))
@pytest.mark.parametrize("paradas", [3, 4])
def test_varias_paradas_igualan_a_la_fuerza_bruta(semilla, paradas, haz_ancho):
    base = base_al_azar(semilla, estaciones=10 + semilla % 3)
    p = perfil()
    esperadas = por_fuerza_bruta(base, p, paradas, cerrada=False)
    obtenidas, cortada = varias_paradas(base, paradas)
    assert not cortada
    assert bool(obtenidas) == bool(esperadas)
    if esperadas:
        assert mejor_clave(obtenidas, "ganancia_hora") == pytest.approx(
            mejor_clave(esperadas, "ganancia_hora")
        )


@pytest.mark.parametrize("semilla", range(20))
def test_circuitos_de_hasta_cuatro_igualan_a_la_fuerza_bruta(semilla, haz_ancho):
    base = base_al_azar(semilla, estaciones=10 + semilla % 3)
    p = perfil()
    esperadas = [c for n in (3, 4) for c in por_fuerza_bruta(base, p, n, cerrada=True)]
    obtenidas, cortada = circuitos(base, 4)
    assert not cortada
    assert bool(obtenidas) == bool(esperadas)
    if esperadas:
        assert mejor_clave(obtenidas, "ganancia_hora") == pytest.approx(
            mejor_clave(esperadas, "ganancia_hora")
        )


def test_la_fuerza_bruta_encuentra_rutas_en_la_mayoria_de_las_bases(haz_ancho):
    con_rutas = sum(bool(varias_paradas(base_al_azar(semilla), 3)[0]) for semilla in range(20))
    assert con_rutas >= 10


@pytest.mark.parametrize("orden", ["ganancia_viaje", "ganancia_tonelada", "distancia"])
def test_las_otras_ordenes_usan_la_suma_de_los_tramos(orden, haz_ancho):
    for semilla in range(8):
        base = base_al_azar(semilla)
        esperadas = por_fuerza_bruta(base, perfil(orden=orden), 3, cerrada=False)
        obtenidas, _ = varias_paradas(base, 3, orden=orden)
        assert bool(obtenidas) == bool(esperadas)
        if esperadas:
            assert mejor_clave(obtenidas, orden) == pytest.approx(mejor_clave(esperadas, orden))
            primera = obtenidas[0]
            assert primera.ganancia_viaje == sum(t.ganancia_viaje for t in primera.tramos)
            assert primera.distancia_ly == pytest.approx(
                sum(t.distancia_ly for t in primera.tramos)
            )


@pytest.mark.parametrize("paradas", [3, 4, 5])
def test_las_abiertas_tienen_exactamente_las_paradas_pedidas_y_ninguna_repite(paradas):
    base = base_al_azar(2, estaciones=12)
    obtenidas, _ = varias_paradas(base, paradas)
    assert obtenidas
    for ruta in obtenidas:
        assert not ruta.cerrada
        assert len(ruta.tramos) == paradas - 1
        assert len(ruta.estaciones) == paradas
        assert len(set(ruta.estaciones)) == paradas


def test_los_circuitos_son_de_tres_a_las_paradas_pedidas_y_ninguno_repite():
    base = base_al_azar(2, estaciones=12)
    obtenidos, _ = circuitos(base, 5)
    assert obtenidos
    for ruta in obtenidos:
        assert ruta.cerrada
        assert 3 <= len(ruta.estaciones) <= 5
        assert len(set(ruta.estaciones)) == len(ruta.estaciones)
        assert len(ruta.tramos) == len(ruta.estaciones)
        assert ruta.tramos[-1].venta.estacion.market_id == ruta.estaciones[0]


def tres_estaciones_en_triangulo(base):
    """1→2→3→1 con oro, plata y hierro; el sentido contrario con estaño, cobre y plomo."""
    for market_id, x in ((1, 0), (2, 10), (3, 20)):
        estacion(base, market_id, sistema(base, market_id * 10, x))
    vende(base, 1, "gold", 9000)
    compra(base, 2, "gold", 10_000)
    vende(base, 2, "silver", 4000)
    compra(base, 3, "silver", 4500)
    vende(base, 3, "iron", 2000)
    compra(base, 1, "iron", 2500)
    vende(base, 1, "tin", 1000)
    compra(base, 3, "tin", 1200)
    vende(base, 3, "copper", 500)
    compra(base, 2, "copper", 700)
    vende(base, 2, "lead", 300)
    compra(base, 1, "lead", 400)


def test_un_circuito_sale_una_vez_aunque_se_encuentre_desde_sus_tres_estaciones(base):
    tres_estaciones_en_triangulo(base)
    obtenidos, _ = circuitos(base, 3)
    claves = {cadenas._clave_de_ciclo(c.estaciones) for c in obtenidos}
    assert len(obtenidos) == len(claves) == 2


def test_el_sentido_contrario_es_otro_resultado_con_otras_mercancias(base):
    tres_estaciones_en_triangulo(base)
    obtenidos, _ = circuitos(base, 3)
    mercancias = [{t.compra.mercancia for t in c.tramos} for c in obtenidos]
    assert {"gold", "silver", "iron"} in mercancias
    assert {"tin", "copper", "lead"} in mercancias


def test_un_circuito_de_tres_mejor_que_cualquier_bucle_sale_el_primero(base):
    tres_estaciones_en_triangulo(base)
    p = perfil()
    mejor_bucle = max(
        b.puntuacion for b in rutas.bucle(cargar(base, p), p, CURVA, timing.POR_DEFECTO)
    )
    obtenidos, _ = circuitos(base, 3)
    assert len(obtenidos[0].estaciones) == 3
    assert obtenidos[0].puntuacion > mejor_bucle
    assert {t.compra.mercancia for t in obtenidos[0].tramos} == {"gold", "silver", "iron"}


def test_cada_tramo_es_el_mejor_entre_sus_dos_estaciones():
    base = base_al_azar(4, estaciones=12)
    p = perfil()
    c = cargar(base, p)
    abiertas, _ = varias_paradas(base, 4)
    ciclos, _ = circuitos(base, 4)
    assert abiertas
    assert ciclos
    for ruta in (*abiertas, *ciclos):
        for tramo in ruta.tramos:
            origen, destino = tramo.compra.estacion.market_id, tramo.venta.estacion.market_id
            assert tramo == rutas.mejor_entre(c, origen, destino, p, CURVA, timing.POR_DEFECTO)


def test_las_estaciones_encadenan_cada_venta_con_la_compra_siguiente():
    base = base_al_azar(6, estaciones=12)
    for ruta in varias_paradas(base, 4)[0]:
        for anterior, siguiente in zip(ruta.tramos, ruta.tramos[1:], strict=False):
            assert anterior.venta.estacion.market_id == siguiente.compra.estacion.market_id


def test_sin_tiempo_se_devuelve_lo_que_haya_marcado_como_cortado_y_solo_rutas_validas():
    base = base_al_azar(2, estaciones=12)
    for modo in (varias_paradas, circuitos):
        resultados, cortada = modo(base, 4, limite(fin=0.0, reloj=lambda: 1.0))
        assert cortada
        for ruta in resultados:
            assert len(set(ruta.estaciones)) == len(ruta.estaciones)
        if modo is varias_paradas:
            assert all(len(r.estaciones) == 4 for r in resultados)


def test_si_el_tiempo_se_acaba_a_mitad_una_cadena_se_completa_con_la_cache():
    base = base_al_azar(2, estaciones=12)
    llamadas = iter(range(10**6))
    # El reloj marca «a tiempo» las primeras veces y después ya se pasó.
    lim = limite(fin=50.0, reloj=lambda: float(next(llamadas)))
    resultados, cortada = varias_paradas(base, 5, lim)
    assert cortada
    assert all(len(r.estaciones) == 5 and len(set(r.estaciones)) == 5 for r in resultados)


def test_un_circuito_cortado_devuelve_los_ciclos_que_alcanzo_a_cerrar():
    base = base_al_azar(2, estaciones=12)
    llamadas = iter(range(10**6))
    lim = limite(fin=40.0, reloj=lambda: float(next(llamadas)))
    resultados, cortada = circuitos(base, 6, lim)
    assert cortada
    assert all(r.cerrada for r in resultados)


def test_el_tiempo_agotado_no_se_recupera_si_el_reloj_retrocede():
    marcas = iter([5.0, 0.0])
    lim = limite(fin=3.0, reloj=lambda: next(marcas))
    assert lim.agotado()
    assert lim.agotado()


def test_con_la_busqueda_cancelada_se_lanza_la_excepcion(base):
    tres_estaciones_en_triangulo(base)
    lim = limite()
    lim.parar.set()
    with pytest.raises(BusquedaCancelada):
        varias_paradas(base, 3, lim)
    with pytest.raises(BusquedaCancelada):
        circuitos(base, 3, lim)


def test_sin_rutas_las_dos_busquedas_devuelven_listas_vacias(base):
    estacion(base, 1, sistema(base, 10, 0))
    vende(base, 1, "gold", 9000)
    assert varias_paradas(base, 4) == ([], False)
    assert circuitos(base, 4) == ([], False)
