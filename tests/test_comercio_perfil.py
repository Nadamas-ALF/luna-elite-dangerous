import pytest

from core import nave
from modules.comercio.engine import perfil as modulo
from modules.comercio.engine.perfil import PerfilInvalido
from tests.test_nave import MEDIDO_EN_EL_JUEGO

TOPE_DIAS = 7


def desde_dict(datos, tope_dias=TOPE_DIAS):
    return modulo.desde_dict(datos, tope_dias)


def valido(**cambios) -> dict:
    datos = {
        "capacidad": 1120,
        "rango": 32.03,
        "plataforma": "L",
        "limitar_saldo": True,
        "origen": "Sol",
        "distancia_max_ly": 50,
        "distancia_max_ls": 5000,
        "antiguedad_max_h": 24,
        "stock_minimo": 1120,
        "ganancia_min": 0,
        "tipos": ["orbital", "asentamiento"],
        "origenes": ["eddn", "propio"],
        "raras": False,
        "horas_sesion": 1,
        "orden": "ganancia_hora",
    }
    return {**datos, **cambios}


def test_un_perfil_valido_se_convierte_y_vuelve_igual():
    perfil = desde_dict(valido())
    assert perfil.capacidad == 1120
    assert perfil.origenes == ("propio", "eddn")  # orden canónico
    assert desde_dict(perfil.a_dict()) == perfil


def test_los_valores_por_defecto_son_los_de_la_seccion_7_1():
    perfil = modulo.Perfil(capacidad=1, rango=1.0, plataforma="S", creditos=None, origen="Sol")
    assert (perfil.distancia_max_ly, perfil.distancia_max_ls, perfil.antiguedad_max_h) == (
        50,
        5000,
        24,
    )
    assert (perfil.stock_minimo, perfil.ganancia_min, perfil.limitar_saldo) == (1, 0, True)
    assert perfil.raras is False
    assert perfil.horas_sesion == 1
    assert perfil.orden == "ganancia_hora"
    assert set(perfil.origenes) == {"propio", "eddn", "spansh"}


def test_el_saldo_solo_limita_las_compras_si_la_casilla_esta_marcada():
    assert modulo.desde_dict(valido(), TOPE_DIAS, saldo=5_000).creditos == 5_000
    assert modulo.desde_dict(valido(limitar_saldo=False), TOPE_DIAS, saldo=5_000).creditos is None
    assert modulo.desde_dict(valido(), TOPE_DIAS, saldo=None).creditos is None


def test_el_saldo_no_viaja_en_el_perfil_ni_se_acepta_de_la_interfaz():
    perfil = modulo.desde_dict(valido(), TOPE_DIAS, saldo=5_000)
    assert "creditos" not in perfil.a_dict()
    with pytest.raises(PerfilInvalido) as error:
        desde_dict(valido(creditos=5_000))
    assert error.value.campo == "creditos"


def test_el_stock_minimo_se_pide_en_toneladas_enteras_y_puede_superar_la_bodega():
    assert desde_dict(valido(capacidad=100, stock_minimo=5_000)).stock_minimo == 5_000
    assert desde_dict(valido(stock_minimo=0)).stock_minimo == 0


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("capacidad", 0),
        ("capacidad", 10.5),
        ("capacidad", True),
        ("capacidad", "100"),
        ("rango", 0),
        ("rango", float("nan")),
        ("rango", float("inf")),
        ("plataforma", "XL"),
        ("limitar_saldo", 1),
        ("ganancia_min", -1),
        ("ganancia_min", 1.5),
        ("stock_minimo", 10.5),
        ("capacidad", -(10**400)),
        ("rango", 10**400),
        ("origen", ""),
        ("origen", "   "),
        ("origen", "x" * 101),
        ("origen", "S\x00l"),
        ("origen", 5),
        ("distancia_max_ly", 0),
        ("distancia_max_ly", 5000),
        ("antiguedad_max_h", -1),
        ("antiguedad_max_h", 7 * 24 + 1),
        ("stock_minimo", -1),
        ("tipos", []),
        ("tipos", ["fleet_carrier"]),
        ("tipos", "orbital"),
        ("tipos", ["orbital"] * 6),
        ("origenes", ["inara"]),
        ("raras", 1),
        ("horas_sesion", 0),
        ("horas_sesion", 25),
        ("orden", "precio"),
    ],
)
def test_un_campo_invalido_se_rechaza_nombrandolo(campo, valor):
    with pytest.raises(PerfilInvalido) as error:
        desde_dict(valido(**{campo: valor}))
    assert error.value.campo == campo


def test_la_antiguedad_llega_justo_hasta_el_tope_de_la_configuracion():
    assert desde_dict(valido(antiguedad_max_h=7 * 24)).antiguedad_max_h == 168
    assert desde_dict(valido(antiguedad_max_h=30 * 24), tope_dias=30).antiguedad_max_h == 720
    with pytest.raises(PerfilInvalido):
        desde_dict(valido(antiguedad_max_h=48), tope_dias=1)


def test_un_campo_de_mas_o_de_menos_se_rechaza():
    with pytest.raises(PerfilInvalido) as error:
        desde_dict(valido(sql="DROP TABLE"))
    assert error.value.campo == "sql"
    datos = valido()
    del datos["rango"]
    with pytest.raises(PerfilInvalido) as error:
        desde_dict(datos)
    assert error.value.campo == "rango"


@pytest.mark.parametrize("datos", [None, [], "perfil", 5])
def test_algo_que_no_es_un_diccionario_se_rechaza(datos):
    with pytest.raises(PerfilInvalido):
        desde_dict(datos)


def test_el_rango_del_perfil_es_el_medido_en_el_juego_con_bodega_y_deposito_llenos():
    """Panther Clipper MkII, 1120 t: 32,03 ly en el panel del juego (verificaciones.md, 4)."""
    barco = nave.desde_loadout(MEDIDO_EN_EL_JUEGO)
    assert nave.rango_de_comercio(barco) == pytest.approx(32.03, abs=0.01)
