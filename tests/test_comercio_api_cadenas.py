"""Varias paradas y Circuito por la API de Comercio (fase 8)."""

import json
import re
import sqlite3
from itertools import count
from pathlib import Path

import pytest

from core.config import ajustes
from core.db import esquema
from core.state.estado import Estado
from modules.comercio import api as modulo
from modules.comercio import estimar, fijadas, timing
from modules.comercio.engine.calculo import Curva
from tests.mercado_de_prueba import AHORA, compra, estacion, perfil, sistema, vende

AQUI = Estado(legacy=False, sistema="S1", posicion=(0.0, 0.0, 0.0))
ORIGEN = (0.0, 0.0, 0.0)


@pytest.fixture
def triangulo(tmp_path):
    """1→2 con oro, 2→3 con plata y 3→1 con hierro: tres estaciones a 10 ly una de otra."""
    archivo = tmp_path / "luna.db"
    conexion = sqlite3.connect(archivo, isolation_level=None)
    esquema.migrar(conexion)
    for numero, x in ((1, 0.0), (2, 10.0), (3, 20.0)):
        sistema(conexion, numero, x)
        estacion(conexion, numero * 100, numero)
    vende(conexion, 100, "gold", 9_000)
    compra(conexion, 200, "gold", 10_000)
    vende(conexion, 200, "silver", 4_000)
    compra(conexion, 300, "silver", 4_800)
    vende(conexion, 300, "iron", 2_000)
    compra(conexion, 100, "iron", 2_600)
    conexion.close()
    return archivo


def comercio(base, tmp_path, **opciones) -> modulo.Comercio:
    return modulo.Comercio(
        lambda: AQUI, tmp_path / "config.json", base, None, reloj=lambda: AHORA, **opciones
    )


def datos(**cambios) -> dict:
    return perfil(**cambios).a_dict()


def test_varias_paradas_devuelve_cadenas_con_su_detalle(triangulo, tmp_path):
    respuesta = comercio(triangulo, tmp_path).buscar_rutas("cadena", datos(), 3)

    assert respuesta["modo"] == "cadena"
    assert respuesta["cortada"] is False
    assert respuesta["limite_s"] == 8
    primero = respuesta["resultados"][0]
    assert primero["cerrada"] is False
    assert primero["paradas"] == 3
    assert len(primero["tramos"]) == 2
    assert len(primero["detalle"]["paradas"]) == 3
    assert primero["detalle"]["cerrada"] is False
    json.dumps(respuesta)


def test_un_circuito_devuelve_el_detalle_cerrado(triangulo, tmp_path):
    respuesta = comercio(triangulo, tmp_path).buscar_rutas("circuito", datos(), 3)

    [circuito] = respuesta["resultados"]
    assert circuito["cerrada"] is True
    assert len(circuito["tramos"]) == 3
    assert circuito["detalle"]["cerrada"] is True
    assert len(circuito["detalle"]["paradas"]) == 3
    assert circuito["ganancia_viaje"] == sum(t["ganancia_viaje"] for t in circuito["tramos"])


@pytest.mark.parametrize(
    ("modo", "paradas"),
    [
        ("cadena", None),
        ("cadena", 2),
        ("cadena", 7),
        ("cadena", True),
        ("cadena", "4"),
        ("circuito", 3.0),
        ("circuito", None),
        ("un_salto", 3),
        ("bucle", 4),
    ],
)
def test_las_paradas_invalidas_se_rechazan_nombrando_el_campo(triangulo, tmp_path, modo, paradas):
    respuesta = comercio(triangulo, tmp_path).buscar_rutas(modo, datos(), paradas)
    assert respuesta == {"error": "parametro", "campo": "paradas"}


def test_los_modos_de_antes_no_cortan(triangulo, tmp_path):
    respuesta = comercio(triangulo, tmp_path).buscar_rutas("un_salto", datos())
    assert respuesta["cortada"] is False


@pytest.mark.parametrize("modo", ["cadena", "circuito"])
def test_la_primera_ruta_da_las_mismas_cifras_al_estimarla_como_fijada(triangulo, tmp_path, modo):
    primero = comercio(triangulo, tmp_path).buscar_rutas(modo, datos(), 3)["resultados"][0]
    paradas = [
        {"market_id": p["estacion"]["market_id"], "mercancia": _comprada(p)}
        for p in primero["detalle"]["paradas"]
    ]
    conexion = sqlite3.connect(triangulo, isolation_level=None)
    pedida = fijadas.validar({"cerrada": primero["cerrada"], "paradas": paradas})
    ruta = fijadas.completar(conexion, pedida)
    contexto = estimar.leer_contexto(
        conexion,
        {p["market_id"] for p in paradas},
        AHORA,
        ORIGEN,
        perfil(),
        Curva(),
        timing.POR_DEFECTO,
    )
    estimada = estimar.estimar(contexto, ruta)["resumen"]
    conexion.close()

    assert estimada["ganancia_viaje"] == primero["ganancia_viaje"]
    assert estimada["ganancia_hora"] == pytest.approx(primero["ganancia_hora"])


def _comprada(parada: dict) -> str | None:
    return parada["comprar"][0]["mercancia"]["simbolo"] if parada["comprar"] else None


def test_con_el_tiempo_agotado_la_respuesta_llega_marcada_como_cortada(triangulo, tmp_path):
    reloj = count(0, 100)
    api = comercio(triangulo, tmp_path, cronometro=lambda: float(next(reloj)))

    respuesta = api.buscar_rutas("cadena", datos(), 4)

    assert respuesta["cortada"] is True
    assert respuesta["resultados"] == []


def test_el_limite_de_la_configuracion_llega_a_la_respuesta(triangulo, tmp_path):
    api = comercio(triangulo, tmp_path)
    assert api.guardar_ajustes_de_busqueda(7, ["orbital"], 12)["ok"] is True
    assert api.buscar_rutas("circuito", datos(), 3)["limite_s"] == 12


def test_los_ajustes_de_busqueda_traen_el_limite_y_sus_extremos(triangulo, tmp_path):
    ajustes_ = comercio(triangulo, tmp_path).ajustes_de_busqueda()
    assert ajustes_["limite_busqueda_s"] == 8
    assert (ajustes_["limite_minimo_s"], ajustes_["limite_maximo_s"]) == (3, 30)


@pytest.mark.parametrize("limite", [2, 31, 8.0, "8", True, None, -1])
def test_un_limite_fuera_de_rango_no_escribe_nada(triangulo, tmp_path, limite):
    respuesta = comercio(triangulo, tmp_path).guardar_ajustes_de_busqueda(7, ["orbital"], limite)
    assert respuesta == {"error": "parametro", "campo": "limite_busqueda_s"}
    assert not (tmp_path / "config.json").exists()


def test_el_limite_ilegible_de_la_configuracion_vuelve_a_ocho(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"comercio": {"limite_busqueda_s": 99}}), encoding="utf-8")
    assert ajustes.limite_de_busqueda(config) == 8


def test_las_paradas_de_la_interfaz_son_las_que_acepta_python():
    codigo = (Path(__file__).parent.parent / "ui" / "js" / "rutas.js").read_text(encoding="utf-8")
    ofrecidas = re.search(r"const PARADAS = \[([\d, ]+)\];", codigo)
    assert ofrecidas, "rutas.js deberia declarar PARADAS"
    numeros = [int(n) for n in ofrecidas.group(1).split(",")]
    assert numeros == list(range(modulo.PARADAS_MINIMAS, modulo.PARADAS_MAXIMAS + 1))


def test_el_tiempo_de_lectura_no_gasta_el_limite(triangulo, tmp_path, monkeypatch):
    reloj = {"t": 0.0}
    from modules.comercio.engine import candidatos

    cargar = candidatos.cargar

    def lenta(*args, **kwargs):
        reloj["t"] += 100.0
        return cargar(*args, **kwargs)

    monkeypatch.setattr(modulo.candidatos, "cargar", lenta)
    api = comercio(triangulo, tmp_path, cronometro=lambda: reloj["t"])

    respuesta = api.buscar_rutas("cadena", datos(), 3)

    assert respuesta["cortada"] is False
    assert respuesta["resultados"]
