"""Primer arranque: la bienvenida sale solo si `config.json` no existía al arrancar."""

import json

from core import events
from core.api import Api
from core.config import ajustes
from core.config.rutas import Ubicacion
from core.nucleo import Nucleo


def interfaz(config):
    return Api(
        Nucleo(config, events.Bus(), None),
        Ubicacion(config.parent, portable=True),
        config,
        base_disponible=True,
        elegir_carpeta=lambda: None,
    )


def test_sin_config_se_crea_con_la_bienvenida_pendiente(tmp_path):
    config = tmp_path / "config.json"

    assert ajustes.marcar_primer_arranque(config)

    assert json.loads(config.read_text("utf-8")) == {"interfaz": {"bienvenida_pendiente": True}}
    assert interfaz(config).bienvenida() == {"pendiente": True}


def test_con_config_no_se_toca(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"esfera": {"radio": 250}}', encoding="utf-8")

    assert not ajustes.marcar_primer_arranque(config)

    assert config.read_text("utf-8") == '{"esfera": {"radio": 250}}'
    assert interfaz(config).bienvenida() == {"pendiente": False}


def test_un_config_roto_no_cuenta_como_primera_vez(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{roto", encoding="utf-8")

    assert not ajustes.marcar_primer_arranque(config)

    assert config.read_text("utf-8") == "{roto"
    assert not ajustes.bienvenida_pendiente(config)


def test_terminar_quita_la_marca_y_se_puede_repetir(tmp_path):
    config = tmp_path / "config.json"
    ajustes.marcar_primer_arranque(config)
    api = interfaz(config)

    assert api.terminar_bienvenida() == {"guardado": True}
    assert api.terminar_bienvenida() == {"guardado": True}

    assert api.bienvenida() == {"pendiente": False}


def test_terminar_conserva_el_resto_de_la_configuracion(tmp_path):
    config = tmp_path / "config.json"
    ajustes.marcar_primer_arranque(config)
    ajustes.guardar_siempre_encima(config, True)

    ajustes.terminar_bienvenida(config)

    assert ajustes.interfaz(config) == (True, False)


def test_si_config_no_se_puede_escribir_terminar_dice_que_no_guardo(tmp_path):
    config = tmp_path / "config.json"
    config.mkdir()  # leerlo da un error de acceso, no un JSON roto

    assert interfaz(config).terminar_bienvenida() == {"guardado": False}
    assert config.is_dir()


def test_una_marca_que_no_es_booleana_no_cuenta(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"interfaz": {"bienvenida_pendiente": "si"}}', encoding="utf-8")

    assert not ajustes.bienvenida_pendiente(config)
