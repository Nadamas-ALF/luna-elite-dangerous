import shutil
from pathlib import Path

import pytest

from core import estacion
from core.journal import archivos
from core.journal import mercado as lector_mercado

FIXTURES = Path(__file__).parent / "fixtures" / "journal"


@pytest.fixture
def carpeta(tmp_path):
    shutil.copy(FIXTURES / "Market.json", tmp_path / archivos.MERCADO)
    return tmp_path


def test_lee_el_mercado_real(carpeta):
    mercado = lector_mercado.leer(carpeta)

    assert mercado.market_id == 4220195075
    assert mercado.estacion == "St4r F0x's Salt Shack"
    assert mercado.observado == "2026-11-10T05:13:02Z"
    paladio = next(a for a in mercado.articulos if a.simbolo == "palladium")
    assert (paladio.nombre, paladio.categoria, paladio.stock) == ("Paladio", "metals", 174)


def test_el_simbolo_es_el_de_eddn():
    assert lector_mercado.simbolo("$platinum_name;") == "platinum"
    assert lector_mercado.simbolo("$EraninPearlWhisky_Name;") == "eraninpearlwhisky"
    assert lector_mercado.simbolo(None) is None
    assert lector_mercado.simbolo("$_name;") is None


def test_solo_se_comercia_lo_que_tiene_stock_o_demanda(carpeta):
    articulos = {a.simbolo: a for a in lector_mercado.leer(carpeta).articulos}

    assert not articulos["platinum"].se_comercia
    assert articulos["water"].se_comercia
    assert articulos["eraninpearlwhisky"].rara


def test_la_demanda_residual_de_un_productor_cuenta_como_cero(carpeta):
    """Paladio real: la estación lo produce (Stock 174) y el juego anota Demand 1, nivel 0."""
    paladio = next(a for a in lector_mercado.leer(carpeta).articulos if a.simbolo == "palladium")

    assert (paladio.stock, paladio.demanda) == (174, 0)
    assert paladio.se_comercia


def test_un_consumidor_sin_stock_no_ofrece_nada(carpeta):
    agua = next(a for a in lector_mercado.leer(carpeta).articulos if a.simbolo == "water")

    assert (agua.stock, agua.demanda) == (0, 19172)


@pytest.mark.parametrize(
    "contenido",
    ["", "[]", "{}", '{"MarketID": 1, "timestamp": "2026-01-01T00:00:00Z"}', '{"MarketID": 1'],
)
def test_un_archivo_que_no_es_un_mercado_no_devuelve_nada(tmp_path, contenido):
    (tmp_path / archivos.MERCADO).write_text(contenido, encoding="utf-8")

    assert lector_mercado.leer(tmp_path) is None


def test_una_linea_mala_no_invalida_el_mercado():
    valido = {
        "Name": "$gold_name;",
        "BuyPrice": 10,
        "SellPrice": 9,
        "Stock": 5,
        "Demand": 0,
        "StockBracket": 1,
        "DemandBracket": 0,
    }
    mercado = lector_mercado.convertir(
        {
            "MarketID": 7,
            "timestamp": "2026-01-01T00:00:00Z",
            "Items": ["basura", {"Name": "$gold_name;", "BuyPrice": "caro"}, valido],
        }
    )

    assert [a.simbolo for a in mercado.articulos] == ["gold"]


def test_sin_archivo_no_hay_mercado(tmp_path):
    assert lector_mercado.leer(tmp_path) is None


@pytest.mark.parametrize(
    ("idioma", "codigo"),
    [("Spanish/ES", "es"), ("English/UK", "en"), ("German/DE", None), (None, None)],
)
def test_codigo_de_idioma(idioma, codigo):
    assert lector_mercado.codigo_de_idioma(idioma) == codigo


@pytest.mark.parametrize(
    ("tipo", "categoria", "planetaria"),
    [
        ("Coriolis", estacion.ORBITAL, False),
        ("Ocellus", estacion.ORBITAL, False),
        ("CraterPort", estacion.ORBITAL, True),
        ("Outpost", estacion.PUESTO_AVANZADO, False),
        ("CraterOutpost", estacion.PUESTO_AVANZADO, True),
        ("OnFootSettlement", estacion.ASENTAMIENTO, True),
        ("FleetCarrier", estacion.FLEET_CARRIER, False),
        ("AlgoNuevo", estacion.DESCONOCIDA, False),
        (None, estacion.DESCONOCIDA, False),
    ],
)
def test_clasifica_las_estaciones(tipo, categoria, planetaria):
    assert estacion.categoria(tipo) == categoria
    assert estacion.es_planetaria(tipo) is planetaria


def test_plataforma_maxima_es_la_mayor_con_huecos():
    assert estacion.plataforma_maxima({"Small": 17, "Medium": 18, "Large": 9}) == "L"
    assert estacion.plataforma_maxima({"Small": 2, "Medium": 1, "Large": 0}) == "M"
    assert estacion.plataforma_maxima({"Small": 1, "Medium": 0, "Large": 0}) == "S"
    assert estacion.plataforma_maxima({"Small": 0, "Medium": 0, "Large": 0}) is None
    assert estacion.plataforma_maxima(None) is None


@pytest.mark.parametrize(
    ("nombre", "esperada"),
    [
        ("$EXT_PANEL_ColonisationShip; Bowman Horizons", estacion.COLONIZACION),
        ("Orbital Construction Site: Crockett Landing", estacion.COLONIZACION),
        ("orbital construction site: x", estacion.COLONIZACION),
        ("Jaques Station", estacion.ORBITAL),
        ("Mi Orbital Construction Site: no", estacion.ORBITAL),
        (None, estacion.ORBITAL),
    ],
)
def test_la_colonizacion_se_reconoce_por_el_nombre(nombre, esperada):
    assert estacion.categoria("Coriolis", nombre) == esperada
