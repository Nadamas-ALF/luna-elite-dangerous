import json
from pathlib import Path

import pytest

from core.journal import comercio
from core.state.estado import Estado, aplicar

FIXTURES = Path(__file__).parent / "fixtures" / "journal"
# Un bucle real Antonelli Arsenal ↔ Beregovoi Colony del 2026-11-10 (comandante
# anonimizado), que termina con el juego cerrado atracado.
BUCLE = [
    json.loads(linea)
    for linea in (FIXTURES / "bucle_comercio.log").read_text(encoding="utf-8").splitlines()
    if linea.strip()
]


def recorrer(eventos: list[dict]) -> tuple[list[comercio.Operacion], list[comercio.Tramo]]:
    estado, libro, operaciones, tramos = Estado(), comercio.Libro(), [], []
    for evento in eventos:
        estado = aplicar(estado, evento)
        hecha = comercio.operacion(estado, evento)
        if hecha:
            operaciones.append(hecha)
        libro, tramo = comercio.anotar(libro, estado, evento)
        if tramo:
            tramos.append(tramo)
    return operaciones, tramos


def ev(nombre: str, hora: str, **campos) -> dict:
    return {"timestamp": f"2026-11-10T{hora}Z", "event": nombre, **campos}


def atracar(hora: str, market_id: int, nombre: str) -> dict:
    return ev(
        "Docked",
        hora,
        MarketID=market_id,
        StationName=nombre,
        StationType="Coriolis",
        StarSystem=f"Sistema {market_id}",
        DistFromStarLS=500.0,
    )


def comprar(hora: str, market_id: int, cantidad: int = 100) -> dict:
    return ev(
        "MarketBuy",
        hora,
        MarketID=market_id,
        Type="gold",
        Count=cantidad,
        BuyPrice=9000,
        TotalCost=cantidad * 9000,
    )


def vender(hora: str, market_id: int, precio: int = 10000, cantidad: int = 100) -> dict:
    return ev(
        "MarketSell",
        hora,
        MarketID=market_id,
        Type="gold",
        Count=cantidad,
        SellPrice=precio,
        TotalSale=cantidad * precio,
        AvgPricePaid=9000,
    )


def test_un_bucle_real_da_un_tramo_por_cada_viaje_con_venta():
    _, tramos = recorrer(BUCLE)

    assert len(tramos) == 14
    primero = tramos[0]
    assert (primero.origen.estacion, primero.destino.estacion) == (
        "Antonelli Arsenal",
        "Beregovoi Colony",
    )
    # De despegar de Antonelli (06:01:39) a despegar de Beregovoi (06:11:10).
    assert (primero.salida, primero.llegada, primero.segundos) == (
        "2026-11-10T06:01:39Z",
        "2026-11-10T06:11:10Z",
        571,
    )
    assert primero.saltos == 3
    assert primero.ganancia == 1120 * (38821 - 2900)
    assert (primero.toneladas, primero.mercancia) == (1120, "bauxite")
    assert primero.distancia_ly == pytest.approx(62.9, abs=0.1)
    assert primero.rango == pytest.approx(32.03, abs=0.01)
    assert primero.ship_id == 14


def test_con_el_juego_cerrado_atracado_el_ultimo_tramo_acaba_en_la_ultima_operacion():
    _, tramos = recorrer(BUCLE)

    assert tramos[-1].llegada == "2026-11-10T08:22:06Z"
    assert tramos[-1].segundos == 504


def test_cada_compra_y_venta_es_una_operacion_con_su_estacion():
    operaciones, _ = recorrer(BUCLE)

    assert len(operaciones) == 28
    compra, venta = operaciones[0], operaciones[1]
    assert (compra.venta, compra.simbolo, compra.cantidad, compra.precio) == (
        False,
        "bauxite",
        1120,
        2900,
    )
    assert (compra.estacion, compra.ganancia) == ("Antonelli Arsenal", None)
    assert (venta.venta, venta.estacion, venta.precio_medio_compra) == (
        True,
        "Beregovoi Colony",
        2900,
    )
    assert venta.ganancia == 1120 * (38821 - 2900)


def test_una_parada_sin_comercio_por_medio_no_corta_el_tramo():
    _, tramos = recorrer([
        atracar("10:00:00", 1, "A"),
        comprar("10:01:00", 1),
        ev("Undocked", "10:02:00", MarketID=1),
        ev("FSDJump", "10:03:00"),
        atracar("10:08:00", 2, "Repostaje"),
        ev("Undocked", "10:09:00", MarketID=2),
        ev("FSDJump", "10:10:00"),
        atracar("10:15:00", 3, "B"),
        vender("10:16:00", 3),
        ev("Undocked", "10:17:00", MarketID=3),
    ])

    assert [(t.origen.estacion, t.destino.estacion, t.saltos, t.segundos) for t in tramos] == [
        ("A", "B", 2, 900)
    ]


@pytest.mark.parametrize("corte", ["Shutdown", "LoadGame", "Died", "Resurrect", "CarrierJump"])
def test_un_cierre_por_medio_anula_el_tramo_aunque_haya_un_atraque_despues(corte):
    _, tramos = recorrer([
        atracar("10:00:00", 1, "A"),
        comprar("10:01:00", 1),
        ev("Undocked", "10:02:00", MarketID=1),
        ev(corte, "10:03:00"),
        atracar("10:30:00", 2, "Sin comercio"),
        ev("Undocked", "10:31:00", MarketID=2),
        atracar("10:40:00", 3, "B"),
        vender("10:41:00", 3),
        ev("Undocked", "10:42:00", MarketID=3),
    ])

    assert tramos == []


def test_un_viaje_en_taxi_anula_el_tramo():
    _, tramos = recorrer([
        atracar("10:00:00", 1, "A"),
        comprar("10:01:00", 1),
        ev("Undocked", "10:02:00", MarketID=1),
        ev("FSDJump", "10:03:00", Taxi=True),
        atracar("10:08:00", 3, "B"),
        vender("10:09:00", 3),
        ev("Undocked", "10:10:00", MarketID=3),
    ])

    assert tramos == []


def test_vender_sin_ganancia_no_es_un_tramo_de_la_ruta():
    _, tramos = recorrer([
        atracar("10:00:00", 1, "A"),
        comprar("10:01:00", 1),
        ev("Undocked", "10:02:00", MarketID=1),
        atracar("10:08:00", 3, "B"),
        vender("10:09:00", 3, precio=8000),
        ev("Undocked", "10:10:00", MarketID=3),
    ])

    assert tramos == []


def test_cargar_la_partida_atracado_sirve_de_origen():
    _, tramos = recorrer([
        ev(
            "Location",
            "10:00:00",
            Docked=True,
            MarketID=1,
            StationName="A",
            StationType="Coriolis",
            StarSystem="Uno",
            DistFromStarLS=10.0,
        ),
        comprar("10:01:00", 1),
        ev("Undocked", "10:02:00", MarketID=1),
        atracar("10:08:00", 3, "B"),
        vender("10:09:00", 3),
        ev("Undocked", "10:10:00", MarketID=3),
    ])

    assert [(t.origen.estacion, t.destino.estacion) for t in tramos] == [("A", "B")]


@pytest.mark.parametrize(
    "cambio",
    [
        {"Count": 0},
        {"Count": -5},
        {"Count": "100"},
        {"BuyPrice": None},
        {"Type": None},
        {"MarketID": "1"},
        {"timestamp": "ayer"},
    ],
)
def test_una_operacion_mal_formada_no_se_cuenta(cambio):
    evento = {**comprar("10:01:00", 1), **cambio}

    assert comercio.operacion(Estado(), evento) is None


def test_una_operacion_en_otra_estacion_que_la_tuya_no_lleva_nombre():
    estado = aplicar(Estado(), atracar("10:00:00", 1, "A"))

    hecha = comercio.operacion(estado, comprar("10:01:00", 2))

    assert (hecha.market_id, hecha.estacion, hecha.sistema) == (2, None, None)


def test_una_venta_sin_precio_de_compra_no_tiene_ganancia():
    evento = {**vender("10:00:00", 1), "AvgPricePaid": 0}

    assert comercio.operacion(Estado(), evento).ganancia is None
