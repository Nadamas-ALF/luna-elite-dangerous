import re

from core import events
from core.api import Api
from core.config.rutas import Ubicacion
from core.nucleo import Nucleo
from core.version import VERSION


def test_la_version_tiene_tres_numeros():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)


def test_configuracion_ensena_la_version(tmp_path):
    config = tmp_path / "config.json"
    api = Api(
        Nucleo(config, events.Bus(), None),
        Ubicacion(tmp_path, portable=True),
        config,
        base_disponible=True,
        elegir_carpeta=lambda: None,
    )

    assert api.configuracion()["datos"]["version"] == VERSION
