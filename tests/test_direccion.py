import json
from pathlib import Path

import pytest

from core import direccion

FIXTURES = Path(__file__).parent / "fixtures"
HOLLAND = (-72.0625, 220.5625, 291.3125)


def test_el_sol_cae_en_su_propia_caja():
    # SystemAddress y posición del Sol, tomados del journal.
    assert direccion.es_coherente(10477373803, (0.0, 0.0, 0.0))


def test_los_sistemas_reales_de_spansh_son_coherentes():
    lineas = (FIXTURES / "spansh" / "galaxy_stations_muestra.json").read_bytes().splitlines()
    sistemas = [json.loads(linea.rstrip(b",")) for linea in lineas[1:-1]]
    assert len(sistemas) == 10
    for sistema in sistemas:
        c = sistema["coords"]
        assert direccion.es_coherente(sistema["id64"], (c["x"], c["y"], c["z"])), sistema["name"]


def test_los_mensajes_reales_de_eddn_son_coherentes():
    revisados = 0
    for archivo in (FIXTURES / "eddn").glob("journal_1_*.json"):
        cuerpo = json.loads(archivo.read_text(encoding="utf-8"))["message"]
        if "StarPos" in cuerpo:
            assert direccion.es_coherente(cuerpo["SystemAddress"], tuple(cuerpo["StarPos"]))
            revisados += 1
    assert revisados >= 3


def test_unas_coordenadas_de_otro_sitio_no_caben():
    assert not direccion.es_coherente(10477373803, (40.0, 0.0, 0.0))


@pytest.mark.parametrize("eje", [0, 1, 2])
def test_cada_eje_se_comprueba(eje):
    posicion = [0.0, 0.0, 0.0]
    posicion[eje] = 500.0
    assert not direccion.es_coherente(10477373803, tuple(posicion))


def test_la_caja_del_sol_tiene_su_lado_y_esquina():
    esquina, lado = direccion.caja(10477373803)
    assert lado == 80.0
    assert esquina == (-65.0, -25.0, -25.0)


def test_el_borde_de_la_caja_cuenta_como_dentro():
    esquina, lado = direccion.caja(10477373803)
    assert direccion.es_coherente(10477373803, esquina)
    assert direccion.es_coherente(
        10477373803, (esquina[0] + lado, esquina[1] + lado, esquina[2] + lado)
    )
    assert not direccion.es_coherente(10477373803, (esquina[0] + lado + 1, esquina[1], esquina[2]))


@pytest.mark.parametrize("valor", [1, 7, 2**63 - 1, 2**55])
def test_cualquier_direccion_se_decodifica_sin_fallar(valor):
    esquina, lado = direccion.caja(valor)
    assert lado in {10.0 * (1 << codigo) for codigo in range(8)}
    assert len(esquina) == 3
