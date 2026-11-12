import inspect
import json
from pathlib import Path

import pytest

from core import events
from core.api import Api
from core.config import ajustes
from core.config.rutas import Ubicacion
from core.nucleo import Nucleo
from core.state import vista
from core.state.estado import Estado, aplicar

FIXTURES = Path(__file__).parent / "fixtures" / "journal"

CONTEXTO = vista.Contexto(
    journal=vista.JOURNAL_LEYENDO,
    motivo_datos=None,
    avisos_datos=(),
    base_disponible=True,
)


def sesion() -> Estado:
    estado = Estado()
    texto = (FIXTURES / "sesion_comercio.log").read_text(encoding="utf-8")
    for linea in texto.splitlines():
        estado = aplicar(estado, json.loads(linea))
    return estado


def test_la_vista_de_una_sesion_real_trae_nave_ubicacion_y_fuentes():
    datos = vista.a_diccionario(sesion(), CONTEXTO)

    assert datos["comandante"]["nombre"] == "CMDR Prueba"
    assert datos["comandante"]["legacy"] is False
    assert datos["comandante"]["version"] == "4.4.2.1"
    assert datos["comandante"]["saldo"] == 1_000_000_000 - 3_248_000 + 43_479_520
    assert datos["nave"]["modelo"] == "Panther Clipper Mk II"
    assert datos["nave"]["plataforma"] == "L"
    assert datos["nave"]["capacidad_carga"] == 1120
    assert abs(datos["nave"]["rango_vacio"] - 49.302464) < 0.001
    assert datos["ubicacion"]["sistema"] == "Col 285 Sector HB-C b14-2"
    assert datos["ubicacion"]["estacion"] == {"nombre": "St4r F0x's Salt Shack", "tipo": "Coriolis"}
    assert datos["fuentes"]["journal"]["estado"] == vista.JOURNAL_LEYENDO
    assert datos["fuentes"]["eddn"]["estado"] == "no_conectado"
    assert datos["fuentes"]["spansh"]["estado"] == "sin_descarga"


def test_el_rango_cargado_usa_el_combustible_actual_si_se_conoce():
    lleno = vista.a_diccionario(sesion(), CONTEXTO)["nave"]["rango_cargado"]
    sin_dato = sesion()
    sin_dato = Estado(**{**sin_dato.__dict__, "combustible": None})

    ficha = vista.a_diccionario(sin_dato, CONTEXTO)["nave"]["rango_cargado"]

    assert lleno < ficha
    assert lleno > 0


def test_sin_datos_cada_ausencia_trae_su_motivo():
    datos = vista.a_diccionario(Estado(), CONTEXTO)

    assert datos["nave"] == {"presente": False, "motivo": vista.MOTIVO_SIN_LOADOUT}
    assert datos["ubicacion"] == {"presente": False, "motivo": vista.MOTIVO_SIN_UBICACION}
    assert datos["carga"] == {"presente": False, "motivo": vista.MOTIVO_SIN_LECTURA}
    assert datos["comandante"]["nombre"] is None


def test_sin_journal_la_causa_de_cada_ausencia_es_esa_y_no_un_evento():
    sin_carpeta = vista.Contexto(vista.JOURNAL_SIN_CARPETA, None, (), True)

    datos = vista.a_diccionario(Estado(), sin_carpeta)

    assert datos["comandante"]["motivo_nombre"] == vista.MOTIVO_SIN_JOURNAL
    assert datos["comandante"]["motivo_saldo"] == vista.MOTIVO_SIN_JOURNAL
    for panel in ("nave", "ubicacion", "carga"):
        assert datos[panel]["motivo"] == vista.MOTIVO_SIN_JOURNAL


def test_con_journal_la_causa_es_el_evento_que_falta():
    datos = vista.a_diccionario(Estado(), CONTEXTO)

    assert datos["comandante"]["motivo_nombre"] == vista.MOTIVO_SIN_COMANDANTE
    assert datos["comandante"]["motivo_saldo"] == vista.MOTIVO_SIN_SALDO


def test_una_nave_que_el_catalogo_no_conoce_dice_por_que_no_hay_plataforma():
    estado = sesion()
    loadout = {"event": "Loadout", "Ship": "naveinventada", "ShipID": 5, "Modules": []}
    estado = aplicar(estado, loadout)

    nave = vista.a_diccionario(estado, CONTEXTO)["nave"]

    assert nave["plataforma"] is None
    assert nave["motivo_plataforma"] == vista.MOTIVO_NAVE_NO_CONOCIDA
    assert nave["rango_vacio"] is None
    assert nave["motivo_rango"] == "loadout_incompleto"
    assert nave["modelo"] == "naveinventada"


def test_la_distancia_al_centro_es_la_euclidea_desde_el_sol():
    estado = aplicar(Estado(), {"event": "FSDJump", "StarSystem": "X", "StarPos": [3, 4, 12]})

    assert vista.a_diccionario(estado, CONTEXTO)["ubicacion"]["distancia_al_centro"] == 13.0


def test_los_avisos_de_datos_incluyen_la_falta_de_base():
    contexto = vista.Contexto(vista.JOURNAL_LEYENDO, "unidad_de_red", ("unidad_extraible",), False)

    datos = vista.a_diccionario(Estado(), contexto)["datos"]

    assert datos == {
        "motivo": "unidad_de_red",
        "avisos": ["unidad_extraible", vista.AVISO_SIN_BASE],
    }


def test_la_carga_suma_toneladas_y_conoce_la_capacidad():
    estado = sesion()
    estado = aplicar(
        estado,
        {
            "event": "Cargo",
            "Vessel": "Ship",
            "Count": 7,
            "Inventory": [{"Name": "gold", "Name_Localised": "Oro", "Count": 7}],
        },
    )

    carga = vista.a_diccionario(estado, CONTEXTO)["carga"]

    assert carga == {
        "presente": True,
        "mercancias": [{"nombre": "Oro", "cantidad": 7}],
        "total": 7,
        "capacidad": 1120,
    }


@pytest.fixture
def elegida():
    """Lo que devolvería el diálogo nativo; None es que el usuario cancela."""
    return {"ruta": None}


@pytest.fixture
def api(tmp_path, elegida):
    config = tmp_path / "config.json"
    nucleo = Nucleo(config, events.Bus(), None)
    return (
        Api(
            nucleo,
            Ubicacion(tmp_path, portable=True),
            config,
            base_disponible=True,
            elegir_carpeta=lambda: elegida["ruta"],
        ),
        config,
        nucleo,
    )


def test_la_interfaz_solo_ve_los_metodos_previstos(api):
    interfaz, _, _ = api

    # pywebview expone los métodos públicos y recorre los atributos públicos
    # que sean objetos (webview.util.inject_pywebview).
    publicos = [nombre for nombre in dir(interfaz) if not nombre.startswith("_")]
    expuestas = {n for n in publicos if inspect.ismethod(getattr(interfaz, n))}

    assert set(publicos) == expuestas
    assert expuestas == {
        "estado",
        "configuracion",
        "elegir_carpeta_journal",
        "usar_carpeta_automatica",
    }


def test_elegir_carpeta_la_guarda_y_pide_reconstruir(api, elegida, tmp_path):
    interfaz, config, nucleo = api
    destino = tmp_path / "juego"
    destino.mkdir()
    elegida["ruta"] = str(destino)

    resultado = interfaz.elegir_carpeta_journal()

    assert ajustes.carpeta_journal(config) == str(destino)
    assert resultado["journal"] == {
        "carpeta": str(destino),
        "automatica": False,
        "elegida_no_existe": False,
    }
    assert nucleo._reiniciar.is_set()


def test_cancelar_el_dialogo_no_cambia_nada(api):
    interfaz, config, nucleo = api

    interfaz.elegir_carpeta_journal()

    assert ajustes.carpeta_journal(config) is None
    assert not nucleo._reiniciar.is_set()


def test_un_dialogo_que_falla_no_rompe_la_interfaz(tmp_path):
    def roto():
        raise OSError("sin dialogo")

    nucleo = Nucleo(tmp_path / "config.json", events.Bus(), None)
    interfaz = Api(
        nucleo, Ubicacion(tmp_path, portable=True), tmp_path / "config.json", True, roto
    )

    assert interfaz.elegir_carpeta_journal()["journal"]["automatica"] is True


def test_volver_a_la_deteccion_automatica(api, tmp_path):
    interfaz, config, nucleo = api
    ajustes.guardar_carpeta_journal(config, str(tmp_path))

    resultado = interfaz.usar_carpeta_automatica()

    assert resultado["journal"]["automatica"] is True
    assert ajustes.carpeta_journal(config) is None
    assert nucleo._reiniciar.is_set()


def test_una_carpeta_elegida_que_desaparecio_se_avisa(api, tmp_path):
    interfaz, config, _ = api
    ajustes.guardar_carpeta_journal(config, str(tmp_path / "borrada"))

    assert interfaz.configuracion()["journal"]["elegida_no_existe"] is True


def test_los_ajustes_invalidos_caen_al_valor_por_defecto(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"journal": {"carpeta": 7, "dias": true}}', encoding="utf-8")
    assert ajustes.carpeta_journal(config) is None
    assert ajustes.dias_journal(config) == ajustes.DIAS_POR_DEFECTO

    config.write_text('{"journal": {"dias": 100000}}', encoding="utf-8")
    assert ajustes.dias_journal(config) == ajustes.DIAS_MAXIMOS

    config.write_text('{"journal": []}', encoding="utf-8")
    assert ajustes.dias_journal(config) == ajustes.DIAS_POR_DEFECTO


def test_si_no_se_puede_guardar_la_carpeta_se_avisa_y_no_se_reconstruye(
    api, elegida, tmp_path, monkeypatch
):
    interfaz, _, nucleo = api
    elegida["ruta"] = str(tmp_path)
    monkeypatch.setattr(ajustes, "guardar_carpeta_journal", lambda config, carpeta: False)

    assert interfaz.elegir_carpeta_journal()["no_guardado"] is True
    assert interfaz.usar_carpeta_automatica()["no_guardado"] is True
    assert not nucleo._reiniciar.is_set()


def test_si_se_guarda_no_hay_aviso(api, elegida, tmp_path):
    interfaz, _, _ = api
    elegida["ruta"] = str(tmp_path)

    assert interfaz.elegir_carpeta_journal()["no_guardado"] is False
