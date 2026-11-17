import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from core.db import esquema
from modules.comercio import en_curso, fijadas, timing
from modules.comercio.en_curso import Leg
from modules.comercio.engine import candidatos, rutas
from modules.comercio.engine.calculo import Curva
from tests.bucle_de_prueba import guardar_el_bucle
from tests.mercado_de_prueba import AHORA, base_vacia, compra, estacion, perfil, sistema, vende

FIN_DEL_BUCLE = datetime(2026, 11, 10, 8, 22, 6, tzinfo=UTC)
PAUSA = 3.0
FORMATO = "%Y-%m-%dT%H:%M:%SZ"
ANTONELLI, BEREGOVOI = 4299403779, 3228387328


def leg(origen, destino, llegada="2026-11-10T08:00:00Z", ganancia=1_000, segundos=600.0, m="oro"):
    return Leg(
        llegada,
        llegada,
        origen,
        f"E{origen}",
        f"S{origen}",
        destino,
        f"E{destino}",
        f"S{destino}",
        ganancia,
        segundos,
        m,
    )


def encadenados(tramos):
    """Cada tramo sale cuando llega el anterior, y el último llega a las 08:00."""
    fin = datetime(2026, 11, 10, 8, 0, 0, tzinfo=UTC)
    marcas = [(fin - timedelta(minutes=10 * (len(tramos) - i))) for i in range(len(tramos) + 1)]
    return [
        replace(t, salida=marcas[i].strftime(FORMATO), llegada=marcas[i + 1].strftime(FORMATO))
        for i, t in enumerate(tramos)
    ]


def deducida(*tramos, ahora=FIN_DEL_BUCLE):
    return en_curso.deducir(encadenados(tramos), ahora, PAUSA)


def test_el_bucle_real_sale_cerrado_de_dos_paradas_con_sus_viajes_y_su_cr_h():
    conexion = sqlite3.connect(":memory:", isolation_level=None)
    esquema.migrar(conexion)
    guardar_el_bucle(conexion)
    tramos = en_curso.leer(conexion, "F0000001")

    ruta = en_curso.deducir(tramos, FIN_DEL_BUCLE, PAUSA)

    assert ruta.cerrada is True
    assert {p["market_id"] for p in ruta.paradas} == {ANTONELLI, BEREGOVOI}
    assert ruta.viajes == 14
    assert ruta.ganancia == sum(t.ganancia for t in tramos)
    assert ruta.por_hora_real == pytest.approx(ruta.ganancia * 3600 / ruta.segundos)
    assert ruta.clave == fijadas.clave(True, [ANTONELLI, BEREGOVOI])
    conexion.close()


def test_las_mercancias_de_las_paradas_son_las_del_ultimo_tramo_que_salio_de_ellas():
    conexion = sqlite3.connect(":memory:", isolation_level=None)
    esquema.migrar(conexion)
    guardar_el_bucle(conexion)

    ruta = en_curso.deducir(en_curso.leer(conexion, "F0000001"), FIN_DEL_BUCLE, PAUSA)

    por_id = {p["market_id"]: p["mercancia"] for p in ruta.paradas}
    assert por_id == {ANTONELLI: "bauxite", BEREGOVOI: "titanium"}
    conexion.close()


def test_sin_ciclo_la_ruta_es_el_ultimo_tramo_abierto():
    ruta = deducida(leg(1, 2), leg(2, 3))

    assert ruta.cerrada is False
    assert [p["market_id"] for p in ruta.paradas] == [2, 3]
    assert ruta.paradas[1]["mercancia"] is None
    assert ruta.viajes == 1


def test_un_ciclo_de_tres_paradas_se_reconoce_y_cuenta_solo_lo_que_se_repite():
    ruta = deducida(leg(9, 1), leg(1, 2), leg(2, 3), leg(3, 1), leg(1, 2), leg(2, 3), leg(3, 1))

    assert ruta.cerrada is True
    assert ruta.viajes == 6
    assert ruta.clave == fijadas.clave(True, [1, 2, 3])


def test_una_estacion_repetida_dentro_del_ciclo_no_lo_hace_cerrado():
    ruta = deducida(leg(1, 2), leg(2, 3), leg(3, 2), leg(2, 4), leg(4, 2))

    assert ruta.cerrada is True
    assert [p["market_id"] for p in ruta.paradas] == [2, 4]


def test_los_tramos_mas_viejos_que_la_pausa_no_dan_ruta():
    tramos = [leg(1, 2, llegada="2026-11-10T08:00:00Z")]

    assert en_curso.deducir(tramos, FIN_DEL_BUCLE + timedelta(hours=4), PAUSA) is None
    assert en_curso.deducir(tramos, FIN_DEL_BUCLE, PAUSA) is not None


def test_sin_tramos_no_hay_ruta():
    assert en_curso.deducir([], FIN_DEL_BUCLE, PAUSA) is None


def test_un_tramo_sin_estacion_conocida_corta_la_cadena():
    ruta = deducida(leg(1, 2), leg(2, 1), leg(None, 2), leg(2, 1))

    assert ruta.cerrada is False
    assert [p["market_id"] for p in ruta.paradas] == [2, 1]


def test_si_el_ultimo_tramo_no_tiene_estacion_no_hay_ruta():
    assert deducida(leg(1, 2), leg(2, None)) is None


def test_un_tramo_de_una_estacion_a_si_misma_no_es_una_ruta():
    assert deducida(leg(1, 1)) is None


def test_la_siguiente_parada_en_los_dos_sentidos_y_none_si_es_abierta_o_ajena():
    cerrada = deducida(leg(1, 2), leg(2, 1))

    assert en_curso.siguiente(cerrada, 1)["market_id"] == 2
    assert en_curso.siguiente(cerrada, 2)["market_id"] == 1
    assert en_curso.siguiente(cerrada, 99) is None
    assert en_curso.siguiente(deducida(leg(1, 2), leg(2, 3)), 2) is None


@pytest.fixture
def mercado():
    conexion = base_vacia()
    for numero in range(1, 5):
        sistema(conexion, numero, 5.0 * numero)
        estacion(conexion, numero * 100, numero)
    vende(conexion, 100, "gold", 9_000)
    compra(conexion, 200, "gold", 30_000)
    vende(conexion, 300, "gold", 9_000)
    compra(conexion, 400, "gold", 12_000)
    yield conexion
    conexion.close()


def candidatas(mercado):
    p = perfil()
    cargados = candidatos.cargar(mercado, p, (0.0, 0.0, 0.0), AHORA)
    return [("un_salto", t) for t in rutas.un_salto(cargados, p, Curva(), timing.POR_DEFECTO)]


def test_la_mejor_candidata_gana_si_supera_la_referencia_por_mas_del_margen(mercado):
    todas = candidatas(mercado)
    mejor = max(t.ganancia_hora for _, t in todas)

    elegida = en_curso.mejor_que(todas, "otra", mejor / 1.2, 10.0)

    assert elegida is not None
    assert elegida[1].ganancia_hora == mejor


def test_no_avisa_si_la_mejora_no_llega_al_margen(mercado):
    todas = candidatas(mercado)
    mejor = max(t.ganancia_hora for _, t in todas)

    assert en_curso.mejor_que(todas, "otra", mejor / 1.1, 20.0) is None


def test_la_propia_ruta_en_curso_no_compite_consigo_misma(mercado):
    todas = candidatas(mercado)
    mejor_tramo = max(todas, key=lambda c: c[1].ganancia_hora)[1]
    a, b = mejor_tramo.compra.estacion.market_id, mejor_tramo.venta.estacion.market_id

    elegida = en_curso.mejor_que(todas, fijadas.clave(False, [a, b]), 1.0, 10.0)

    assert elegida is not None
    assert elegida[1] is not mejor_tramo


def test_sin_candidatas_no_hay_mejor():
    assert en_curso.mejor_que([], "x", 1.0, 10.0) is None


def test_un_hueco_entre_sesiones_corta_la_cadena():
    tramos = encadenados([leg(1, 2), leg(2, 1), leg(1, 2), leg(2, 1)])
    tramos[1] = replace(tramos[1], salida="2026-11-09T20:00:00Z", llegada="2026-11-09T20:10:00Z")
    tramos[0] = replace(tramos[0], llegada="2026-11-09T20:00:00Z")

    ruta = en_curso.deducir(tramos, FIN_DEL_BUCLE, PAUSA)

    assert ruta.viajes == 2
