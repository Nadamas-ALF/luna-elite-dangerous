import copy
import json
from pathlib import Path

import pytest

from modules.comercio import paradas

FIXTURES = Path(__file__).parent / "fixtures" / "rutas"
TOTALES = {"ganancia_hora": 1.0}


def tramos_encadenados() -> list[dict]:
    return json.loads((FIXTURES / "tramos_encadenados.json").read_text(encoding="utf-8"))


def con_destino(tramo: dict, market_id: int) -> dict:
    cambiado = copy.deepcopy(tramo)
    cambiado["venta"]["market_id"] = market_id
    return cambiado


def ids(detalle: dict) -> list[int]:
    return [p["estacion"]["market_id"] for p in detalle["paradas"]]


def test_un_salto_son_dos_paradas_abiertas_con_la_compra_en_la_primera():
    [tramo, *_] = tramos_encadenados()
    tramo = {
        **tramo,
        "ganancia_hora": 1.0,
        "ganancia_viaje": 2,
        "ganancia_sesion": 3.0,
        "confianza": 1.0,
    }

    detalle = paradas.detalle("un_salto", tramo)

    primera, segunda = detalle["paradas"]
    assert (detalle["cerrada"], detalle["desde_posicion"]) == (False, False)
    assert primera["llegada"] is None
    assert [c["mercancia"]["simbolo"] for c in primera["comprar"]] == ["gold"]
    assert primera["vender"] == []
    assert segunda["comprar"] == []
    assert segunda["llegada"]["saltos"] == tramo["saltos"]
    [venta] = segunda["vender"]
    assert venta["ingreso"] == tramo["toneladas"] * tramo["venta"]["precio"]
    assert venta["demanda"] == tramo["venta"]["cantidad"]
    assert detalle["totales"]["ganancia_viaje"] == 2


def test_un_bucle_pinta_cada_estacion_y_cada_mercancia_una_sola_vez():
    ida, vuelta, *_ = tramos_encadenados()
    vuelta = {**vuelta, "compra": ida["venta"], "venta": ida["compra"]}
    bucle = {
        "ida": ida,
        "vuelta": vuelta,
        "ganancia_hora": 1.0,
        "ganancia_viaje": 2,
        "ganancia_sesion": 3.0,
        "segundos": 4.0,
        "distancia_ly": 5.0,
        "confianza": 1.0,
    }

    detalle = paradas.detalle("bucle", bucle)

    assert detalle["cerrada"] is True
    assert sorted(ids(detalle)) == [101, 202]
    for parada in detalle["paradas"]:
        assert len(parada["comprar"]) == 1
        assert len(parada["vender"]) == 1
        assert parada["llegada"] is not None
    primera, segunda = detalle["paradas"]
    # En la parada 1 se vende lo de la vuelta y se compra lo de la ida.
    assert primera["vender"][0]["mercancia"] == vuelta["mercancia"]
    assert primera["comprar"][0]["mercancia"] == ida["mercancia"]
    assert segunda["vender"][0]["mercancia"] == ida["mercancia"]
    assert segunda["comprar"][0]["mercancia"] == vuelta["mercancia"]


def test_vender_la_carga_es_una_parada_desde_la_posicion_sin_ganancia_si_no_se_sabe():
    [tramo, *_] = tramos_encadenados()
    venta = {
        "mercancia": tramo["mercancia"],
        "venta": tramo["venta"],
        "toneladas": 100,
        "distancia_ly": 3.0,
        "saltos": 1,
        "segundos": 60.0,
        "tiempo": tramo["tiempo"],
        "ingreso": 1_000_000,
        "ingreso_hora": 5.0,
        "ganancia": None,
        "confianza": 0.9,
    }

    detalle = paradas.detalle("venta", venta)

    [parada] = detalle["paradas"]
    assert (detalle["cerrada"], detalle["desde_posicion"]) == (False, True)
    assert parada["comprar"] == []
    assert parada["llegada"]["distancia_ly"] == 3.0
    [vendida] = parada["vender"]
    assert (vendida["ganancia"], vendida["ganancia_tonelada"]) == (None, None)
    assert vendida["ingreso"] == 100 * tramo["venta"]["precio"]
    assert detalle["totales"]["ganancia_viaje"] is None
    assert "ganancia_hora" not in detalle["totales"]


def test_vender_la_carga_reparte_la_ganancia_por_tonelada():
    [tramo, *_] = tramos_encadenados()
    venta = {
        "mercancia": tramo["mercancia"],
        "venta": tramo["venta"],
        "toneladas": 100,
        "distancia_ly": 3.0,
        "saltos": 1,
        "segundos": 60.0,
        "tiempo": tramo["tiempo"],
        "ingreso": 1,
        "ingreso_hora": 5.0,
        "ganancia": 25_050,
        "confianza": 0.9,
    }

    [vendida] = paradas.detalle("venta", venta)["paradas"][0]["vender"]

    assert vendida["ganancia_tonelada"] == 250


def test_tres_tramos_encadenados_abiertos_dan_cuatro_paradas():
    detalle = paradas.de_tramos(tramos_encadenados(), False, TOTALES)

    assert ids(detalle) == [101, 202, 303, 404]
    assert [p["llegada"] is None for p in detalle["paradas"]] == [True, False, False, False]
    assert [len(p["comprar"]) for p in detalle["paradas"]] == [1, 1, 1, 0]
    assert [len(p["vender"]) for p in detalle["paradas"]] == [0, 1, 1, 1]


def test_cuatro_tramos_cerrados_dan_cuatro_paradas_y_la_primera_llega_de_la_cuarta():
    tramos = tramos_encadenados()
    tramos.append(con_destino(copy.deepcopy(tramos[0]), 101))
    tramos[3]["compra"] = tramos[2]["venta"]
    tramos[3]["saltos"] = 7

    detalle = paradas.de_tramos(tramos, True, TOTALES)

    assert ids(detalle) == [101, 202, 303, 404]
    assert detalle["paradas"][0]["llegada"]["saltos"] == 7
    assert [len(p["vender"]) for p in detalle["paradas"]] == [1, 1, 1, 1]


def test_tramos_que_no_encadenan_se_rechazan():
    tramos = tramos_encadenados()
    tramos[1]["compra"] = {**tramos[1]["compra"], "market_id": 999}

    with pytest.raises(ValueError, match="encadenan"):
        paradas.de_tramos(tramos, False, TOTALES)


def test_una_ruta_cerrada_que_no_vuelve_a_la_primera_parada_se_rechaza():
    with pytest.raises(ValueError, match="cerrada"):
        paradas.de_tramos(tramos_encadenados(), True, TOTALES)


def test_sin_tramos_no_hay_detalle():
    with pytest.raises(ValueError):
        paradas.de_tramos([], False, TOTALES)


def test_un_modo_desconocido_se_rechaza():
    with pytest.raises(ValueError, match="modo"):
        paradas.detalle("otro", {})


def test_un_resultado_con_otra_forma_da_key_error():
    with pytest.raises(KeyError):
        paradas.detalle("un_salto", {"ganancia_hora": 1.0})


def test_el_detalle_es_json():
    json.dumps(paradas.de_tramos(tramos_encadenados(), False, TOTALES))


def totales_de_comercio() -> dict:
    return {
        "ganancia_hora": 1.0,
        "ganancia_viaje": 2,
        "ganancia_sesion": 3.0,
        "segundos": 4.0,
        "distancia_ly": 5.0,
        "confianza": 1.0,
    }


def test_varias_paradas_son_una_estacion_mas_que_tramos():
    tramos = tramos_encadenados()
    datos = {**totales_de_comercio(), "cerrada": False, "tramos": tramos}

    detalle = paradas.detalle("cadena", datos)

    assert detalle["cerrada"] is False
    assert len(detalle["paradas"]) == len(tramos) + 1
    assert detalle["totales"]["ganancia_viaje"] == 2


def test_un_circuito_tiene_tantas_paradas_como_tramos_y_vuelve_a_la_primera():
    *resto, ultimo = tramos_encadenados()
    primero = resto[0]
    cerrado = [*resto, con_destino(ultimo, primero["compra"]["market_id"])]
    datos = {**totales_de_comercio(), "cerrada": True, "tramos": cerrado}

    detalle = paradas.detalle("circuito", datos)

    assert detalle["cerrada"] is True
    assert len(detalle["paradas"]) == len(cerrado)
    assert detalle["paradas"][0]["llegada"] is not None
