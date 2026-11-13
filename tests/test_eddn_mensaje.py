import json
import zlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core import estacion as clasificacion
from core.eddn import mensaje
from core.eddn.mensaje import Descartado, MercadoDeRed, Visita

FIXTURES = Path(__file__).parent / "fixtures" / "eddn"
# Los fixtures se capturaron el 12-11-2026 a las 22:3x UTC.
AHORA = datetime(2026, 11, 12, 22, 40, tzinfo=UTC)


def cargar(nombre: str) -> dict:
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


def comprimir(datos: object) -> bytes:
    return zlib.compress(json.dumps(datos).encode("utf-8"))


def interpretar(datos: object):
    return mensaje.interpretar(comprimir(datos), AHORA)


def motivo(datos: object) -> str:
    with pytest.raises(Descartado) as error:
        interpretar(datos)
    return error.value.motivo


def mercado_minimo(**cuerpo) -> dict:
    base = {
        "$schemaRef": mensaje.ESQUEMA_MERCADO,
        "header": {"gameversion": "CAPI-Live-market", "gatewayTimestamp": "2026-11-12T22:30:00Z"},
        "message": {
            "timestamp": "2026-11-12T22:29:23Z",
            "systemName": "Sol",
            "stationName": "Abraham Lincoln",
            "marketId": 128016384,
            "commodities": [
                {
                    "name": "Gold",
                    "meanPrice": 9000,
                    "buyPrice": 9500,
                    "stock": 40,
                    "stockBracket": 2,
                    "sellPrice": 9100,
                    "demand": 7,
                    "demandBracket": 0,
                }
            ],
        },
    }
    base["message"].update(cuerpo)
    return base


@pytest.mark.parametrize("nombre", sorted(p.name for p in FIXTURES.glob("commodity_3_[0-9].json")))
def test_los_mercados_reales_se_interpretan(nombre):
    resultado = interpretar(cargar(nombre))

    assert isinstance(resultado, MercadoDeRed)
    assert resultado.sistema
    assert resultado.estacion.nombre
    assert resultado.estacion.market_id > 0


def test_un_mercado_real_conserva_sistema_estacion_y_mercancias():
    datos = cargar("commodity_3_1.json")

    resultado = interpretar(datos)

    assert resultado.sistema == "Colonia"
    assert resultado.estacion.nombre == "Jaques Station"
    assert resultado.estacion.market_id == 128667761
    assert resultado.observado == "2026-11-12T22:29:23Z"
    assert len(resultado.articulos) == len(datos["message"]["commodities"])
    primero = resultado.articulos[0]
    assert (primero.simbolo, primero.precio_compra, primero.precio_venta) == (
        "advancedcatalysers",
        2953,
        2864,
    )


def test_la_demanda_residual_con_nivel_cero_se_pone_a_cero():
    resultado = interpretar(cargar("commodity_3_1.json"))

    catalizadores = resultado.articulos[0]
    assert (catalizadores.demanda, catalizadores.nivel_demanda) == (0, 0)
    assert catalizadores.stock == 51496


def test_un_fleet_carrier_se_reconoce_por_su_economia():
    resultado = interpretar(cargar("commodity_3_carrier_1.json"))

    assert resultado.estacion.categoria == clasificacion.FLEET_CARRIER
    assert resultado.articulos == ()


def test_una_estacion_corriente_queda_desconocida_hasta_ver_su_docked():
    resultado = interpretar(cargar("commodity_3_3.json"))

    assert resultado.estacion.categoria == clasificacion.DESCONOCIDA


def test_el_simbolo_va_en_minusculas_como_en_market_json():
    assert interpretar(mercado_minimo()).articulos[0].simbolo == "gold"


@pytest.mark.parametrize("nombre", sorted(p.name for p in FIXTURES.glob("journal_1_[0-9].json")))
def test_los_journal_reales_con_coordenadas_son_visitas(nombre):
    resultado = interpretar(cargar(nombre))

    assert isinstance(resultado, Visita)
    assert resultado.estacion is None


def test_una_visita_trae_sistema_direccion_y_posicion():
    resultado = interpretar(cargar("journal_1_4.json"))

    assert resultado.nombre == "Clookia QV-B d14-17"
    assert resultado.system_address == 593888218747
    assert resultado.posicion == (-3422.1875, -273.0, 13004.3125)


def test_un_docked_real_trae_la_estacion():
    resultado = interpretar(cargar("journal_1_docked_2.json"))

    assert resultado.nombre == "Col 359 Sector GA-W c3-11"
    estacion = resultado.estacion
    assert (estacion.market_id, estacion.nombre) == (4324967683, "Holland Hub")
    assert (estacion.categoria, estacion.plataforma) == (clasificacion.ORBITAL, "L")
    assert estacion.distancia_ls == pytest.approx(14394.882253)
    assert estacion.planetaria is False


def test_el_docked_de_un_carrier_es_fleet_carrier():
    estacion = interpretar(cargar("journal_1_docked_1.json")).estacion

    assert estacion.categoria == clasificacion.FLEET_CARRIER


def test_el_docked_de_la_colonizacion_es_de_colonizacion():
    estacion = interpretar(cargar("journal_1_docked_colonizacion_1.json")).estacion

    assert estacion.nombre == "$EXT_PANEL_ColonisationShip; Bowman Horizons"
    assert estacion.categoria == clasificacion.COLONIZACION


@pytest.mark.parametrize("nombre", ["commodity_3_2.json", "commodity_3_4.json"])
def test_los_mercados_de_colonizacion_se_reconocen_por_el_nombre(nombre):
    assert interpretar(cargar(nombre)).estacion.categoria == clasificacion.COLONIZACION


def test_un_docked_con_estacion_rota_sigue_siendo_una_visita():
    datos = cargar("journal_1_docked_2.json")
    datos["message"]["MarketID"] = "no es un numero"

    resultado = interpretar(datos)

    assert isinstance(resultado, Visita)
    assert resultado.estacion is None


def test_un_evento_del_journal_sin_coordenadas_no_sirve_y_no_es_un_error():
    datos = cargar("journal_1_4.json")
    del datos["message"]["StarPos"]

    assert interpretar(datos) is None


def test_los_mensajes_de_prueba_se_descartan():
    datos = mercado_minimo()
    datos["$schemaRef"] = "https://eddn.edcd.io/schemas/commodity/3/test"

    assert motivo(datos) == mensaje.MOTIVO_PRUEBA


def test_otros_esquemas_se_descartan():
    datos = mercado_minimo()
    datos["$schemaRef"] = "https://eddn.edcd.io/schemas/shipyard/2"

    assert motivo(datos) == mensaje.MOTIVO_ESQUEMA


@pytest.mark.parametrize("version", ["CAPI-Legacy-market", "3.8.0.407", "CAPI-legacy-shipyard"])
def test_legacy_se_descarta(version):
    datos = mercado_minimo()
    datos["header"]["gameversion"] = version

    assert motivo(datos) == mensaje.MOTIVO_LEGACY


def test_sin_version_del_juego_se_acepta():
    datos = mercado_minimo()
    del datos["header"]["gameversion"]

    assert isinstance(interpretar(datos), MercadoDeRed)


@pytest.mark.parametrize(
    "marca",
    [
        "2026-11-12T22:32:00Z",  # más de un minuto por delante de la pasarela
        "2026-09-01T00:00:00Z",  # más de 30 días
        "ayer",
        "2026-11-12T22:29:23",  # sin zona horaria
        20261112,
        None,
    ],
    ids=repr,
)
def test_marcas_de_tiempo_no_creibles_se_descartan(marca):
    assert motivo(mercado_minimo(timestamp=marca)) in (
        mensaje.MOTIVO_FECHA,
        mensaje.MOTIVO_MAL_FORMADO,
    )


def test_la_marca_se_normaliza_a_utc_con_segundos():
    resultado = interpretar(mercado_minimo(timestamp="2026-11-12T23:29:23.512+01:00"))

    assert resultado.observado == "2026-11-12T22:29:23Z"


def test_sin_pasarela_se_compara_con_el_reloj_local():
    datos = mercado_minimo(timestamp="2026-11-12T23:00:00Z")
    del datos["header"]["gatewayTimestamp"]

    assert motivo(datos) == mensaje.MOTIVO_FECHA


@pytest.mark.parametrize(
    "cambio",
    [
        {"marketId": 0},
        {"marketId": True},
        {"marketId": "1"},
        {"systemName": ""},
        {"systemName": "x" * 101},
        {"stationName": None},
        {"stationName": "mal\x00nombre"},
        {"commodities": "oro"},
        {"commodities": [1]},
        {"commodities": [{"name": "Gold"}]},
    ],
    ids=repr,
)
def test_un_mercado_mal_formado_se_descarta(cambio):
    assert motivo(mercado_minimo(**cambio)) == mensaje.MOTIVO_MAL_FORMADO


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("buyPrice", -1),
        ("buyPrice", 1.5),
        ("buyPrice", 2**60),
        ("stock", True),
        ("demandBracket", 4),
        ("stockBracket", "alto"),
        ("sellPrice", None),
        ("name", ""),
    ],
    ids=repr,
)
def test_una_mercancia_mala_descarta_el_mercado_entero(campo, valor):
    datos = mercado_minimo()
    datos["message"]["commodities"][0][campo] = valor

    assert motivo(datos) == mensaje.MOTIVO_MAL_FORMADO


def test_una_mercancia_repetida_descarta_el_mercado():
    datos = mercado_minimo()
    oro = datos["message"]["commodities"][0]
    datos["message"]["commodities"].append({**oro, "name": "GOLD"})

    assert motivo(datos) == mensaje.MOTIVO_MAL_FORMADO


def test_demasiadas_mercancias_se_descartan():
    datos = mercado_minimo()
    oro = datos["message"]["commodities"][0]
    datos["message"]["commodities"] = [
        {**oro, "name": f"m{i}"} for i in range(mensaje.MERCANCIAS_MAXIMAS + 1)
    ]

    assert motivo(datos) == mensaje.MOTIVO_MAL_FORMADO


@pytest.mark.parametrize(
    "posicion",
    [[1, 2], [1, 2, "3"], [1, 2, True], [1, 2, float("nan")], [1e9, 0, 0], "0,0,0", None],
    ids=repr,
)
def test_posiciones_malas_se_descartan(posicion):
    datos = cargar("journal_1_4.json")
    datos["message"]["StarPos"] = posicion

    assert motivo(datos) == mensaje.MOTIVO_MAL_FORMADO


@pytest.mark.parametrize("direccion", [0, -1, "1", True, 2**63])
def test_direcciones_de_sistema_malas_se_descartan(direccion):
    datos = cargar("journal_1_4.json")
    datos["message"]["SystemAddress"] = direccion

    assert motivo(datos) == mensaje.MOTIVO_MAL_FORMADO


@pytest.mark.parametrize(
    "crudo",
    [
        b"",
        b"no es zlib",
        zlib.compress(b"no es json"),
        zlib.compress(b"[1, 2]"),
        zlib.compress(b"7"),
    ],
    ids=repr,
)
def test_basura_se_descarta_sin_excepcion_ajena(crudo):
    with pytest.raises(Descartado) as error:
        mensaje.interpretar(crudo, AHORA)

    assert error.value.motivo == mensaje.MOTIVO_MAL_FORMADO


def test_una_bomba_de_descompresion_se_corta_en_el_tope():
    bomba = zlib.compress(b" " * (mensaje.TAMANO_MAXIMO * 50))

    assert len(bomba) < 100_000
    with pytest.raises(Descartado) as error:
        mensaje.interpretar(bomba, AHORA)
    assert error.value.motivo == mensaje.MOTIVO_MAL_FORMADO


def test_json_anidado_hasta_desbordar_la_pila_se_descarta():
    profundo = zlib.compress(b"[" * 500_000)

    with pytest.raises(Descartado):
        mensaje.interpretar(profundo, AHORA)


def test_cuerpo_o_cabecera_que_no_son_objetos_se_descartan():
    datos = mercado_minimo()
    datos["header"] = []

    assert motivo(datos) == mensaje.MOTIVO_MAL_FORMADO


def test_un_mercado_de_carrier_con_nivel_vacio_se_acepta_como_cero():
    datos = mercado_minimo()
    datos["message"]["commodities"][0].update(demand=0, demandBracket="", stockBracket=2)

    articulo = interpretar(datos).articulos[0]

    assert (articulo.nivel_demanda, articulo.demanda, articulo.nivel_stock) == (0, 0, 2)


def test_un_mercado_viejo_se_descarta_pero_una_visita_vieja_sirve():
    viejo = mercado_minimo(timestamp="2026-09-27T00:53:05Z")
    visita = cargar("journal_1_4.json")
    visita["message"]["timestamp"] = "2026-09-27T00:53:05Z"

    assert motivo(viejo) == mensaje.MOTIVO_FECHA
    assert interpretar(visita).nombre == "Clookia QV-B d14-17"


def test_una_visita_del_futuro_se_descarta():
    visita = cargar("journal_1_4.json")
    visita["message"]["timestamp"] = "2026-11-13T00:00:00Z"

    assert motivo(visita) == mensaje.MOTIVO_FECHA


def test_unas_coordenadas_que_no_caben_en_la_direccion_se_descartan():
    datos = cargar("journal_1_4.json")
    datos["message"]["StarPos"] = [datos["message"]["StarPos"][0] + 500.0, 0.0, 0.0]
    assert motivo(datos) == mensaje.MOTIVO_DIRECCION


def test_una_direccion_inventada_con_las_coordenadas_reales_se_descarta():
    datos = cargar("journal_1_4.json")
    datos["message"]["SystemAddress"] = 10477373803
    assert motivo(datos) == mensaje.MOTIVO_DIRECCION
