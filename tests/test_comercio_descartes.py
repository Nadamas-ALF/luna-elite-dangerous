import pytest

from modules.comercio.engine import candidatos, descartes
from tests.mercado_de_prueba import (
    AHORA,
    base_vacia,
    compra,
    estacion,
    perfil,
    sistema,
    vende,
    vende_y_compra,
)

ORIGEN = (0.0, 0.0, 0.0)


@pytest.fixture
def base():
    conexion = base_vacia()
    yield conexion
    conexion.close()


def contar(base, **cambios) -> dict:
    p = perfil(**cambios)
    cargados = candidatos.cargar(base, p, ORIGEN, AHORA)
    return descartes.contar(base, p, ORIGEN, AHORA, cargados)


def par_de_estaciones(base):
    direccion = sistema(base, 10, 5)
    estacion(base, 1, direccion)
    estacion(base, 2, direccion)
    vende(base, 1, "gold", 9000)
    compra(base, 2, "gold", 10_000)


def test_un_trato_sin_ningun_filtro_en_contra_no_descarta_nada(base):
    par_de_estaciones(base)
    resultado = contar(base)
    assert resultado["descartes"] == dict.fromkeys(resultado["descartes"], 0)
    assert (resultado["estaciones_en_radio"], resultado["estaciones_validas"]) == (2, 2)
    assert (resultado["ofertas"], resultado["demandas"]) == (1, 1)


def test_cada_filtro_de_estacion_cuenta_lo_que_quita_a_lo_que_dejo_el_anterior(base):
    direccion = sistema(base, 10, 5)
    estacion(base, 1, direccion, plataforma="S")  # plataforma
    estacion(base, 2, direccion, plataforma="M")  # plataforma
    estacion(base, 3, direccion, ls=9000)  # distancia a la estrella
    estacion(base, 4, direccion, categoria="asentamiento")  # tipo
    estacion(base, 5, direccion)  # pasa
    lejos = sistema(base, 11, 500)
    estacion(base, 6, lejos)  # fuera del radio: no cuenta en nada
    resultado = contar(base, plataforma="L", tipos=("orbital",))
    assert resultado["estaciones_en_radio"] == 5
    assert resultado["estaciones_validas"] == 1
    d = resultado["descartes"]
    assert (d["plataforma"], d["distancia_ls"], d["tipo"]) == (2, 1, 1)


def test_la_antiguedad_el_origen_las_raras_y_el_stock_cuentan_precios(base):
    direccion = sistema(base, 10, 5)
    for market_id in (1, 2, 3, 4, 5):
        estacion(base, market_id, direccion)
    vende(base, 1, "gold", 9000, horas=30)  # antigüedad
    vende(base, 2, "gold", 9000, origen="spansh")  # origen
    vende(base, 3, "gold", 9000, stock=10)  # stock mínimo
    vende(base, 4, "gold", 9000)  # pasa
    compra(base, 5, "gold", 10_000)  # pasa
    base.execute("INSERT INTO commodities (simbolo, rara) VALUES ('gold', 1)")
    sin_raras = contar(base, origenes=("eddn",), stock_minimo=100)["descartes"]
    assert sin_raras["raras"] == 3
    base.execute("UPDATE commodities SET rara = 0 WHERE simbolo = 'gold'")
    resultado = contar(base, origenes=("eddn",), stock_minimo=100, antiguedad_max_h=24)
    d = resultado["descartes"]
    assert (d["antiguedad"], d["origen"], d["raras"], d["stock_minimo"]) == (1, 1, 0, 1)
    assert (resultado["ofertas"], resultado["demandas"]) == (1, 1)


def test_la_ganancia_minima_y_el_saldo_cuentan_tratos(base):
    par_de_estaciones(base)  # ganancia de 1000 Cr/t con 10 000 t en juego
    d = contar(base, ganancia_min=1001)["descartes"]
    assert (d["ganancia_min"], d["saldo"]) == (1, 0)
    d = contar(base, creditos=100)["descartes"]
    assert (d["ganancia_min"], d["saldo"]) == (0, 1)


def test_se_cuentan_todos_los_pares_y_no_solo_los_extremos(base):
    """30 vendedores y 30 compradores: el motor compara 25 por lado, el recuento todos (E-27)."""
    direccion = sistema(base, 10, 5)
    for n in range(30):
        estacion(base, 100 + n, direccion)
        estacion(base, 200 + n, direccion)
        vende(base, 100 + n, "gold", 9000 + n)
        compra(base, 200 + n, "gold", 9500 + n)
    d = contar(base, ganancia_min=10_000)["descartes"]
    assert d["ganancia_min"] == 30 * 30
    d = contar(base, creditos=100)["descartes"]
    assert d["saldo"] == 30 * 30


def test_la_misma_estacion_no_cuenta_como_par(base):
    direccion = sistema(base, 10, 5)
    estacion(base, 1, direccion)
    estacion(base, 2, direccion)
    vende_y_compra(base, 1, "gold", 9000, 9500)
    compra(base, 2, "gold", 9600)
    d = contar(base, ganancia_min=10_000)["descartes"]
    assert d["ganancia_min"] == 1
    d = contar(base, creditos=100)["descartes"]
    assert d["saldo"] == 1


def test_una_busqueda_cancelada_no_cuenta(base):
    import threading

    par_de_estaciones(base)
    parar = threading.Event()
    parar.set()
    p = perfil()
    cargados = candidatos.cargar(base, p, ORIGEN, AHORA)
    with pytest.raises(candidatos.BusquedaCancelada):
        descartes.contar(base, p, ORIGEN, AHORA, cargados, parar)
