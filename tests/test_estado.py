import json
from pathlib import Path

from core import nave
from core.state import estado as modulo

FIXTURES = Path(__file__).parent / "fixtures" / "journal"


def eventos(nombre: str) -> list[dict]:
    texto = (FIXTURES / nombre).read_text(encoding="utf-8")
    return [json.loads(linea) for linea in texto.splitlines() if linea.strip()]


def reconstruir(lista: list[dict]) -> modulo.Estado:
    resultado = modulo.Estado()
    for evento in lista:
        resultado = modulo.aplicar(resultado, evento)
    return resultado


def hasta(nombre_evento: str, lista: list[dict]) -> list[dict]:
    """Eventos hasta el primero con ese nombre, incluido."""
    posicion = next(i for i, e in enumerate(lista) if e["event"] == nombre_evento)
    return lista[: posicion + 1]


SESION = eventos("sesion_comercio.log")


def test_la_sesion_real_reconstruye_comandante_y_nave():
    resultado = reconstruir(SESION)

    assert resultado.comandante == "CMDR Prueba"
    assert resultado.legacy is False
    assert resultado.version == "4.4.2.1"
    assert resultado.nave.simbolo == "panthermkii"
    assert resultado.nave.capacidad_carga == 1120
    assert resultado.nave.error is None
    assert resultado.nave_localizada == (14, "Panther Clipper Mk II")


def test_la_nave_del_loadout_calcula_el_rango_del_juego():
    resultado = reconstruir(SESION)

    assert nave.rango_maximo(resultado.nave.datos) == nave.rango_maximo(resultado.nave.datos, 0)
    assert abs(nave.rango_maximo(resultado.nave.datos) - 49.302464) < 0.001


def test_atracado_al_arrancar_y_libre_tras_despegar():
    antes = reconstruir(hasta("Location", SESION))
    despues = reconstruir(hasta("Undocked", SESION))

    assert antes.estacion.nombre == "Voltaire Terminal"
    assert antes.estacion.market_id == 4356870147
    assert despues.estacion is None


def test_un_salto_cambia_sistema_y_posicion_y_no_deja_estacion():
    resultado = reconstruir(hasta("FSDJump", SESION))

    assert resultado.sistema == "Pegasi Sector ZB-I a11-2"
    assert resultado.posicion == (-156.28125, -29.03125, -2.5625)
    assert resultado.estacion is None
    assert resultado.system_address == 40534290615120


def test_al_atracar_se_conoce_la_estacion_y_el_sistema():
    resultado = reconstruir(hasta("Docked", SESION))

    assert resultado.estacion.nombre == "St4r F0x's Salt Shack"
    assert resultado.estacion.tipo == "Coriolis"
    assert resultado.sistema == "Col 285 Sector HB-C b14-2"


def test_comprar_y_vender_ajustan_el_saldo():
    inicial = reconstruir(hasta("Loadout", SESION)).creditos
    final = reconstruir(SESION).creditos

    assert inicial == 1_000_000_000
    assert final == inicial - 3_248_000 + 43_479_520


def test_el_ultimo_evento_es_la_marca_del_journal():
    assert reconstruir(SESION).ultimo_evento == SESION[-1]["timestamp"]


def test_un_journal_legacy_se_detecta_y_se_descarta_lo_anterior():
    legacy = eventos("legacy_sintetico.log")

    resultado = reconstruir(SESION + legacy)

    assert resultado.legacy is True
    assert resultado.version == "3.8.0.407"
    assert resultado.nave is None
    assert resultado.sistema is None
    assert resultado.comandante is None


def test_un_journal_live_posterior_quita_el_aviso_de_legacy():
    resultado = reconstruir(eventos("legacy_sintetico.log") + SESION)

    assert resultado.legacy is False
    assert resultado.comandante == "CMDR Prueba"


def test_es_legacy_no_acusa_cuando_no_entiende_la_version():
    assert modulo.es_legacy("3.8.0.407") is True
    assert modulo.es_legacy("4.0.0.1") is False
    assert modulo.es_legacy("beta") is None
    assert modulo.es_legacy(None) is None


def test_carga_con_inventario_y_vacia():
    con_carga = {
        "event": "Cargo",
        "Vessel": "Ship",
        "Count": 3,
        "Inventory": [{"Name": "gold", "Name_Localised": "Oro", "Count": 3}],
    }
    vacia = {"event": "Cargo", "Vessel": "Ship", "Count": 0, "Inventory": []}

    lleno = modulo.aplicar(modulo.Estado(), con_carga)

    assert lleno.carga == (modulo.Mercancia("Oro", 3, "gold"),)
    assert modulo.aplicar(lleno, vacia).carga == ()


def _compra(simbolo: str, toneladas: int, precio: int) -> dict:
    return {
        "event": "MarketBuy",
        "Type": simbolo,
        "Count": toneladas,
        "BuyPrice": precio,
        "TotalCost": toneladas * precio,
    }


def _bodega(**cantidades: int) -> dict:
    inventario = [{"Name": s, "Count": n} for s, n in cantidades.items()]
    return {
        "event": "Cargo",
        "Vessel": "Ship",
        "Count": sum(cantidades.values()),
        "Inventory": inventario,
    }


def test_el_precio_de_compra_es_la_media_de_lo_comprado_desde_que_entro_en_la_bodega():
    estado = reconstruir(
        [
            _compra("gold", 100, 9_000),
            _bodega(gold=100),
            _compra("gold", 300, 10_000),
            _bodega(gold=400),
        ]
    )

    assert modulo.precio_de_compra(estado, "gold") == 9_750


def test_vender_una_parte_no_cambia_el_precio_de_compra():
    estado = reconstruir([_compra("gold", 100, 9_000), _bodega(gold=100), _bodega(gold=40)])

    assert modulo.precio_de_compra(estado, "gold") == 9_000


def test_lo_que_sale_del_todo_de_la_bodega_olvida_su_precio():
    estado = reconstruir(
        [
            _compra("gold", 100, 9_000),
            _bodega(gold=100),
            _bodega(),
            _compra("gold", 10, 5_000),
            _bodega(gold=10),
        ]
    )

    assert modulo.precio_de_compra(estado, "gold") == 5_000


def test_sin_compra_en_el_journal_no_hay_precio():
    estado = reconstruir([_bodega(silver=5)])

    assert modulo.precio_de_compra(estado, "silver") is None


def test_comprar_mas_de_lo_que_ya_llevabas_sin_compra_conocida_no_da_precio():
    # 100 t de una sesión anterior, que LUNA no vio comprar, y 10 t más ahora.
    estado = reconstruir([_bodega(gold=100), _compra("gold", 10, 5_000), _bodega(gold=110)])

    assert modulo.precio_de_compra(estado, "gold") is None


def test_vaciar_la_bodega_deja_que_la_siguiente_compra_tenga_precio():
    estado = reconstruir(
        [_bodega(gold=100), _compra("gold", 10, 5_000), _bodega(), _compra("gold", 10, 5_000)]
    )

    assert modulo.precio_de_compra(estado, "gold") == 5_000


def test_la_carga_de_mision_y_la_robada_no_son_vendibles():
    evento = {
        "event": "Cargo",
        "Vessel": "Ship",
        "Count": 135,
        "Inventory": [
            {"Name": "gold", "Count": 100, "Stolen": 0},
            {"Name": "gold", "MissionID": 123, "Count": 20, "Stolen": 0},
            {"Name": "silver", "Count": 15, "Stolen": 5},
        ],
    }
    carga = modulo.aplicar(modulo.Estado(), evento).carga

    assert [m.vendibles for m in carga] == [100, 0, 10]
    assert modulo.vendibles(carga, "gold") == 100
    assert modulo.vendibles(carga, "silver") == 10


def test_si_solo_queda_carga_de_mision_se_olvida_el_precio_de_compra():
    solo_mision = {
        "event": "Cargo",
        "Vessel": "Ship",
        "Count": 20,
        "Inventory": [{"Name": "gold", "MissionID": 123, "Count": 20, "Stolen": 0}],
    }
    estado = reconstruir([_compra("gold", 100, 9_000), _bodega(gold=100), solo_mision])

    assert estado.compras == ()


def test_una_compra_mal_formada_no_cuenta():
    roto = {"event": "MarketBuy", "Type": "gold", "Count": "mucho", "TotalCost": 10}

    assert modulo.aplicar(modulo.Estado(), roto).compras == ()


def test_la_carga_sin_inventario_espera_al_archivo():
    sin_detalle = {"event": "Cargo", "Vessel": "Ship", "Count": 7}

    assert modulo.aplicar(modulo.Estado(), sin_detalle).carga is None


def test_la_carga_del_srv_no_cuenta():
    srv = {"event": "Cargo", "Vessel": "SRV", "Count": 1, "Inventory": [{"Name": "x", "Count": 1}]}

    assert modulo.aplicar(modulo.Estado(), srv).carga is None


def test_status_actualiza_el_combustible_sin_tocar_la_hora():
    inicial = modulo.Estado(ultimo_evento="2026-11-12T10:00:00Z")
    status = {"event": "Status", "timestamp": "2099-01-01T00:00:00Z", "Fuel": {"FuelMain": 12.5}}

    resultado = modulo.aplicar(inicial, status)

    assert resultado.combustible == 12.5
    assert resultado.ultimo_evento == "2026-11-12T10:00:00Z"


def test_un_status_sin_combustible_no_borra_el_que_hay():
    inicial = modulo.Estado(combustible=20.0)

    assert modulo.aplicar(inicial, {"event": "Status", "Flags": 0}).combustible == 20.0


def test_un_propulsor_desconocido_queda_como_error_y_no_rompe():
    loadout = dict(next(e for e in SESION if e["event"] == "Loadout"))
    loadout["Modules"] = [{"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_futuro", "On": True}]

    resultado = modulo.aplicar(modulo.Estado(), loadout)

    assert resultado.nave.datos is None
    assert resultado.nave.error == modulo.ERROR_PROPULSOR
    assert resultado.nave.capacidad_carga == 1120


def test_un_loadout_sin_propulsor_queda_como_incompleto():
    loadout = {"event": "Loadout", "Ship": "sidewinder", "ShipID": 2, "Modules": []}

    resultado = modulo.aplicar(modulo.Estado(), loadout)

    assert resultado.nave.error == modulo.ERROR_LOADOUT


def test_los_valores_de_tipo_inesperado_no_rompen_el_estado():
    basura = {
        "event": "Location",
        "StarSystem": 7,
        "StarPos": ["a", 1, 2],
        "SystemAddress": True,
        "Docked": "si",
        "StationName": ["x"],
    }

    resultado = modulo.aplicar(modulo.Estado(sistema="Sol"), basura)

    assert resultado.sistema == "Sol"
    assert resultado.posicion is None
    assert resultado.estacion is None


def test_los_eventos_que_no_interesan_dejan_el_estado_igual():
    inicial = modulo.Estado(comandante="CMDR Prueba")

    assert modulo.aplicar(inicial, {"event": "Music", "MusicTrack": "x"}) is inicial
    assert modulo.aplicar(inicial, {"sin_evento": 1}) is inicial


def test_atracar_recoge_plataforma_y_distancia_a_la_estrella():
    estado = modulo.aplicar(
        modulo.Estado(),
        {
            "event": "Docked",
            "StationName": "Salt Shack",
            "StationType": "Coriolis",
            "MarketID": 42,
            "DistFromStarLS": 336.5,
            "LandingPads": {"Small": 17, "Medium": 18, "Large": 9},
        },
    )

    assert estado.estacion.plataforma == "L"
    assert estado.estacion.distancia_ls == 336.5


def test_el_idioma_viene_del_fileheader():
    cabecera = {"event": "Fileheader", "gameversion": "4.4", "language": "Spanish/ES"}
    estado = modulo.aplicar(modulo.Estado(), cabecera)

    assert estado.idioma == "Spanish/ES"
