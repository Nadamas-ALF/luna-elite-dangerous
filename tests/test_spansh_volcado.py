import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core import estacion as clasificacion
from core.esfera import Esfera
from core.spansh import volcado
from core.validacion import Descartado

FIXTURE = Path(__file__).parent / "fixtures" / "spansh" / "galaxy_stations_muestra.json"
GALAXIA = Esfera("Sol", (0.0, 0.0, 0.0), 1_000_000.0)
AHORA = datetime(2026, 12, 1, tzinfo=UTC)


def lineas() -> list[bytes]:
    return FIXTURE.read_bytes().split(b"\n")


@pytest.fixture(scope="module")
def sistemas() -> dict[str, volcado.SistemaDeVolcado]:
    leidos = (volcado.interpretar(linea, GALAXIA, AHORA) for linea in lineas())
    return {s.sistema.nombre: s for s in leidos if s is not None}


def estaciones_de(sistemas, categoria: str):
    return [e for s in sistemas.values() for e in s.estaciones if e.estacion.categoria == categoria]


def linea(**cambios) -> bytes:
    sistema = {
        "id64": 42,
        "name": "Prueba",
        "coords": {"x": 1.0, "y": 2.0, "z": 3.0},
        "date": "2026-11-01T10:00:00Z",
        "stations": [],
    } | cambios
    return b"\t" + json.dumps(sistema, separators=(",", ":")).encode() + b","


def estacion(**cambios) -> dict:
    return {
        "id": 7,
        "name": "Puerto",
        "type": "Coriolis Starport",
        "distanceToArrival": 12.5,
        "landingPads": {"large": 4, "medium": 2, "small": 1},
        "market": {
            "updateTime": "2026-11-01T10:00:00Z",
            "commodities": [
                {"symbol": "Gold", "supply": 0, "demand": 500, "buyPrice": 0, "sellPrice": 9000}
            ],
        },
    } | cambios


def test_la_muestra_real_se_lee_entera(sistemas):
    assert len(sistemas) == 10
    assert all(s.estaciones_descartadas == 0 for s in sistemas.values())


def test_las_lineas_de_estructura_no_son_sistemas():
    assert volcado.interpretar(b"[\n", GALAXIA) is None
    assert volcado.interpretar(b"]\n", GALAXIA) is None
    assert volcado.interpretar(b"\n", GALAXIA) is None


def test_un_sistema_trae_coordenadas_y_distancia_al_centro(sistemas):
    s = sistemas["Phua Fraae AA-A h0"].sistema
    assert s.system_address == 819519
    assert s.posicion == (-34608.78125, 513.34375, 26058.59375)
    assert s.distancia_centro == pytest.approx(GALAXIA.distancia(s.posicion))


def test_clasifica_cada_tipo_de_estacion_de_spansh(sistemas):
    categorias = {e.estacion.categoria for s in sistemas.values() for e in s.estaciones}
    assert categorias >= {
        clasificacion.ORBITAL,
        clasificacion.PUESTO_AVANZADO,
        clasificacion.ASENTAMIENTO,
        clasificacion.FLEET_CARRIER,
        clasificacion.COLONIZACION,
    }
    assert clasificacion.DESCONOCIDA not in categorias


def test_los_sitios_de_construccion_y_la_nave_de_colonizacion_son_colonizacion(sistemas):
    nombres = {e.estacion.nombre for e in estaciones_de(sistemas, clasificacion.COLONIZACION)}
    assert any(n.startswith("Orbital Construction Site:") for n in nombres)
    assert "System Colonisation Ship" in nombres


def test_un_asentamiento_sin_tipo_dentro_de_un_cuerpo_es_planetario(sistemas):
    asentamientos = estaciones_de(sistemas, clasificacion.ASENTAMIENTO)
    assert asentamientos
    assert all(e.estacion.planetaria for e in asentamientos)


def test_una_estacion_orbital_no_es_planetaria(sistemas):
    orbitales = estaciones_de(sistemas, clasificacion.ORBITAL)
    assert orbitales
    assert any(not e.estacion.planetaria for e in orbitales)


def test_las_plataformas_se_leen_en_minuscula(sistemas):
    plataformas = {e.estacion.plataforma for s in sistemas.values() for e in s.estaciones}
    assert plataformas & {"S", "M", "L"}


def test_los_simbolos_van_en_minuscula_como_en_el_journal(sistemas):
    simbolos = {
        a.simbolo for s in sistemas.values() for e in s.estaciones for a in e.articulos or ()
    }
    assert "tritium" in simbolos
    assert all(simbolo == simbolo.lower() for simbolo in simbolos)


def test_spansh_no_trae_niveles_y_se_marcan_desconocidos(sistemas):
    articulos = [a for s in sistemas.values() for e in s.estaciones for a in e.articulos or ()]
    assert articulos
    assert {a.nivel_stock for a in articulos} == {volcado.NIVEL_DESCONOCIDO}
    assert {a.nivel_demanda for a in articulos} == {volcado.NIVEL_DESCONOCIDO}


def test_con_oferta_la_demanda_residual_se_descarta(sistemas):
    articulos = [a for s in sistemas.values() for e in s.estaciones for a in e.articulos or ()]
    assert not [a for a in articulos if a.stock > 0 and a.demanda > 0]


def test_una_estacion_sin_mercado_no_toca_precios(sistemas):
    sin_mercado = [e for s in sistemas.values() for e in s.estaciones if e.articulos is None]
    assert sin_mercado
    assert all(e.observado is None for e in sin_mercado)


def test_la_marca_del_mercado_es_la_de_su_updatetime():
    resultado = volcado.interpretar(linea(stations=[estacion()]), GALAXIA, AHORA)
    assert resultado.estaciones[0].observado == "2026-11-01T10:00:00Z"
    assert resultado.estaciones[0].articulos[0].demanda == 500


def test_las_estaciones_de_los_cuerpos_tambien_cuentan():
    cuerpos = [{"id64": 1, "name": "A 1", "stations": [estacion(id=8, type="Settlement")]}]
    resultado = volcado.interpretar(linea(bodies=cuerpos), GALAXIA, AHORA)
    assert [e.estacion.market_id for e in resultado.estaciones] == [8]
    assert resultado.estaciones[0].estacion.planetaria


def test_una_estacion_repetida_se_guarda_una_vez():
    resultado = volcado.interpretar(
        linea(stations=[estacion(), estacion(name="Otro")]), GALAXIA, AHORA
    )
    assert [e.estacion.nombre for e in resultado.estaciones] == ["Puerto"]


def test_fuera_de_la_esfera_no_se_interpreta_ni_se_valida():
    # Cuerpo roto a propósito: si la línea se parseara entera, fallaría.
    cabecera = b'\t{"id64":1,"name":"Lejos","coords":{"x":9000.0,"y":0.0,"z":0.0},"date":'
    pequena = Esfera("Sol", (0.0, 0.0, 0.0), 100.0)
    assert volcado.interpretar(cabecera + b"roto,", pequena, AHORA) is None


def test_dentro_de_la_esfera_una_linea_rota_se_descarta():
    cabecera = b'\t{"id64":1,"name":"Cerca","coords":{"x":1.0,"y":0.0,"z":0.0},"date":roto,'
    with pytest.raises(Descartado):
        volcado.interpretar(cabecera, GALAXIA, AHORA)


def test_la_cabecera_nunca_decide_si_difiere_del_formato_conocido():
    # Las claves en otro orden no casan con la cabecera: se parsea entera y se filtra bien.
    otra = (
        b'\t{"name":"Lejos","id64":1,"coords":{"x":9000.0,"y":0.0,"z":0.0},'
        b'"date":"2026-11-01T10:00:00Z"},'
    )
    pequena = Esfera("Sol", (0.0, 0.0, 0.0), 100.0)
    assert volcado.interpretar(otra, pequena, AHORA) is None


@pytest.mark.parametrize(
    "cambios",
    [
        {"id64": True},
        {"id64": 0},
        {"name": ""},
        {"coords": {"x": 1.0, "y": "a", "z": 3.0}},
        {"coords": None},
        {"date": "ayer"},
        {"date": "2026-11-01 10:00:00"},
    ],
)
def test_un_sistema_mal_formado_se_descarta(cambios):
    with pytest.raises(Descartado):
        volcado.interpretar(linea(**cambios), GALAXIA, AHORA)


def test_una_linea_gigante_se_descarta():
    with pytest.raises(Descartado):
        volcado.interpretar(b"x" * (volcado.TAMANO_MAXIMO_DE_LINEA + 1), GALAXIA, AHORA)


@pytest.mark.parametrize(
    "mala",
    [
        estacion(id=0),
        estacion(id=True),
        estacion(name=""),
        estacion(market={"updateTime": "2030-01-01T00:00:00Z", "commodities": []}),
        estacion(market={"updateTime": "hoy", "commodities": []}),
        estacion(market={"updateTime": "2026-11-01T10:00:00Z", "commodities": "no"}),
        estacion(
            market={
                "updateTime": "2026-11-01T10:00:00Z",
                "commodities": [
                    {"symbol": "Gold", "supply": -1, "demand": 0, "buyPrice": 0, "sellPrice": 0}
                ],
            }
        ),
        estacion(
            market={
                "updateTime": "2026-11-01T10:00:00Z",
                "commodities": [
                    {"symbol": "Gold", "supply": 1, "demand": 0, "buyPrice": 1, "sellPrice": 1},
                    {"symbol": "gold", "supply": 1, "demand": 0, "buyPrice": 1, "sellPrice": 1},
                ],
            }
        ),
    ],
)
def test_una_estacion_dudosa_se_omite_y_se_cuenta(mala):
    resultado = volcado.interpretar(linea(stations=[mala, estacion(id=9)]), GALAXIA, AHORA)
    assert [e.estacion.market_id for e in resultado.estaciones] == [9]
    assert resultado.estaciones_descartadas == 1


def test_la_linea_compacta_recupera_exactamente_lo_leido(sistemas):
    for original in sistemas.values():
        copia = volcado.deserializar(volcado.serializar(original))
        assert copia == original


def test_la_linea_compacta_pesa_una_fraccion_de_la_original():
    original = sum(len(linea) for linea in lineas())
    compacta = sum(
        len(volcado.serializar(s))
        for s in (volcado.interpretar(linea, GALAXIA, AHORA) for linea in lineas())
        if s is not None
    )
    assert compacta < original / 3


def test_la_linea_compacta_distingue_sin_mercado_de_mercado_vacio():
    sin = volcado.interpretar(linea(stations=[estacion() | {"market": None}]), GALAXIA, AHORA)
    vacio = volcado.interpretar(
        linea(
            stations=[estacion(market={"updateTime": "2026-11-01T10:00:00Z", "commodities": []})]
        ),
        GALAXIA,
        AHORA,
    )
    assert volcado.deserializar(volcado.serializar(sin)).estaciones[0].articulos is None
    assert volcado.deserializar(volcado.serializar(vacio)).estaciones[0].articulos == ()


def test_la_linea_compacta_conserva_nombres_con_acentos_y_comillas():
    original = volcado.interpretar(
        linea(name="Épsilon «Ñu»", stations=[estacion(name='Puerto "Norte"')]), GALAXIA, AHORA
    )
    copia = volcado.deserializar(volcado.serializar(original))
    assert copia.sistema.nombre == "Épsilon «Ñu»"
    assert copia.estaciones[0].estacion.nombre == 'Puerto "Norte"'


def test_un_reloj_atrasado_unas_horas_no_descarta_los_mercados_recientes():
    atrasado = datetime(2026, 11, 1, 8, 0, 0, tzinfo=UTC)  # el mercado es de las 10:00
    resultado = volcado.interpretar(linea(stations=[estacion()]), GALAXIA, atrasado)
    assert resultado.estaciones_descartadas == 0
    assert len(resultado.estaciones) == 1


def test_un_mercado_de_dos_dias_en_el_futuro_sigue_descartandose():
    atrasado = datetime(2026, 10, 30, 10, 0, 0, tzinfo=UTC)
    resultado = volcado.interpretar(linea(stations=[estacion()]), GALAXIA, atrasado)
    assert resultado.estaciones_descartadas == 1
