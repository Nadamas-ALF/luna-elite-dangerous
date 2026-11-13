import json

import pytest

from core.config import ajustes
from core.esfera import Esfera


def escribir(ruta, datos):
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    return ruta


def test_sin_archivo_la_esfera_es_el_sol_con_cien_ly(tmp_path):
    esfera = ajustes.esfera(tmp_path / "config.json")

    assert (esfera.nombre, esfera.centro, esfera.radio) == ("Sol", (0.0, 0.0, 0.0), 100.0)


def test_lee_centro_y_radio_editados(tmp_path):
    config = escribir(
        tmp_path / "config.json",
        {
            "esfera": {
                "centro": {"nombre": "Colonia", "x": -9530.5, "y": -910.28, "z": 19808.1},
                "radio": 250,
            }
        },
    )

    esfera = ajustes.esfera(config)

    assert (esfera.nombre, esfera.centro, esfera.radio) == (
        "Colonia",
        (-9530.5, -910.28, 19808.1),
        250.0,
    )


@pytest.mark.parametrize("radio", [0, -5, "100", True, None, float("inf"), 1e9, [100]], ids=repr)
def test_un_radio_invalido_cae_al_de_por_defecto(tmp_path, radio):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"esfera": {"radio": radio}}).replace("Infinity", "1e999"))

    assert ajustes.esfera(config).radio == ajustes.RADIO_POR_DEFECTO


@pytest.mark.parametrize(
    "centro",
    [
        {"nombre": "X", "x": 1, "y": 2},
        {"nombre": "", "x": 1, "y": 2, "z": 3},
        {"nombre": "X", "x": "1", "y": 2, "z": 3},
        {"nombre": "X", "x": 1e9, "y": 2, "z": 3},
        "Colonia",
    ],
    ids=repr,
)
def test_un_centro_invalido_vuelve_al_sol_entero(tmp_path, centro):
    config = escribir(tmp_path / "config.json", {"esfera": {"centro": centro, "radio": 50}})

    esfera = ajustes.esfera(config)

    assert (esfera.nombre, esfera.centro, esfera.radio) == ("Sol", (0.0, 0.0, 0.0), 50.0)


def test_config_ilegible_da_la_esfera_por_defecto(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{roto", encoding="utf-8")

    assert ajustes.esfera(config).radio == ajustes.RADIO_POR_DEFECTO


@pytest.mark.parametrize(
    ("contenido", "esperado"),
    [
        ({}, True),
        ({"eddn": {"activado": False}}, False),
        ({"eddn": {"activado": True}}, True),
        ({"eddn": {"activado": "no"}}, True),
        ({"eddn": False}, True),
    ],
    ids=repr,
)
def test_eddn_activado(tmp_path, contenido, esperado):
    config = escribir(tmp_path / "config.json", contenido)

    assert ajustes.eddn_activado(config) is esperado


SOL = Esfera("Sol", (0.0, 0.0, 0.0), 100.0)


def test_una_descarga_anterior_a_la_cobertura_se_lee_como_entera(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        '{"spansh": {"fecha": "2026-11-13T00:00:00Z", "radio": 100, '
        '"centro": {"nombre": "Sol", "x": 0, "y": 0, "z": 0}}}',
        encoding="utf-8",
    )
    ultima = ajustes.ultima_descarga(config)
    assert ultima.cobertura == ultima.esfera == Esfera("Sol", (0.0, 0.0, 0.0), 100.0)


def test_la_cobertura_se_guarda_y_se_lee(tmp_path):
    config = tmp_path / "config.json"
    ajustes.guardar_ultima_descarga(config, "2026-11-13T00:00:00Z", SOL)
    menor = Esfera("Sol", (0.0, 0.0, 0.0), 40.0)

    assert ajustes.guardar_cobertura(config, menor)
    ultima = ajustes.ultima_descarga(config)
    assert (ultima.esfera, ultima.cobertura) == (SOL, menor)

    assert ajustes.guardar_cobertura(config, None)
    ultima = ajustes.ultima_descarga(config)
    assert (ultima.esfera, ultima.cobertura) == (SOL, None)
    assert ultima.fecha == "2026-11-13T00:00:00Z"


def test_sin_descarga_no_hay_cobertura_que_guardar(tmp_path):
    assert not ajustes.guardar_cobertura(tmp_path / "config.json", SOL)
    assert not (tmp_path / "config.json").exists()


def test_la_antiguedad_con_memoria_lee_el_archivo_solo_cada_intervalo(tmp_path):
    config = tmp_path / "config.json"
    ajustes.guardar_retencion(config, 3.0, 10.0)
    hora = {"t": 0.0}
    leer = ajustes.antiguedad_maxima_con_memoria(config, 60.0, lambda: hora["t"])

    assert leer() == 10.0
    ajustes.guardar_retencion(config, 3.0, 20.0)
    hora["t"] = 59.0
    assert leer() == 10.0
    hora["t"] = 61.0
    assert leer() == 20.0


def test_la_antiguedad_con_memoria_usa_el_valor_por_defecto_sin_config(tmp_path):
    leer = ajustes.antiguedad_maxima_con_memoria(tmp_path / "no-existe.json")
    assert leer() == ajustes.ANTIGUEDAD_MAXIMA_DIAS_POR_DEFECTO
