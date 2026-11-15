import json
import logging

import pytest

from modules.comercio import perfiles
from tests.mercado_de_prueba import base_vacia, perfil

TOPE = 7


@pytest.fixture
def base():
    conexion = base_vacia()
    yield conexion
    conexion.close()


def nombres(base) -> list[str]:
    return [g.nombre for g in perfiles.listar(base, TOPE)]


def test_un_perfil_guardado_se_lee_igual(base):
    guardado = perfil(capacidad=720, raras=True, tipos=("orbital",))
    perfiles.guardar(base, "Panther", guardado)
    assert perfiles.listar(base, TOPE) == [perfiles.PerfilGuardado("Panther", guardado)]


def test_mismo_nombre_con_otras_mayusculas_sustituye_al_anterior(base):
    perfiles.guardar(base, "Panther", perfil(capacidad=100))
    perfiles.guardar(base, "panther", perfil(capacidad=200))
    [guardado] = perfiles.listar(base, TOPE)
    assert (guardado.nombre, guardado.perfil.capacidad) == ("panther", 200)


def test_se_listan_por_nombre_y_se_borran(base):
    for nombre in ("Cutter", "anaconda", "Beluga"):
        perfiles.guardar(base, nombre, perfil())
    assert nombres(base) == ["anaconda", "Beluga", "Cutter"]
    perfiles.borrar(base, "BELUGA")
    assert nombres(base) == ["anaconda", "Cutter"]


def test_un_perfil_por_encima_del_tope_actual_se_recorta_al_leerlo(base):
    perfiles.guardar(base, "largo", perfil(antiguedad_max_h=30 * 24.0))
    [guardado] = perfiles.listar(base, TOPE)
    assert guardado.perfil.antiguedad_max_h == TOPE * 24


@pytest.mark.parametrize(
    "parametros",
    ["no es json", "[]", json.dumps({"capacidad": 1}), json.dumps({**perfil().a_dict(), "x": 1})],
)
def test_un_perfil_ilegible_se_salta_sin_tapar_a_los_demas(base, parametros, caplog):
    base.execute("INSERT INTO search_profiles VALUES ('roto', ?)", (parametros,))
    perfiles.guardar(base, "bueno", perfil())
    with caplog.at_level(logging.WARNING):
        assert nombres(base) == ["bueno"]
    assert "roto" in caplog.text
