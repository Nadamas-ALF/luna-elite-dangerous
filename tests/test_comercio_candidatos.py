import threading

import pytest

from modules.comercio.engine import candidatos
from tests.mercado_de_prueba import (
    AHORA,
    base_vacia,
    compra,
    estacion,
    perfil,
    sistema,
    vende,
)

ORIGEN = (0.0, 0.0, 0.0)


@pytest.fixture
def base():
    conexion = base_vacia()
    yield conexion
    conexion.close()


def cargar(base, **cambios):
    return candidatos.cargar(base, perfil(**cambios), ORIGEN, AHORA)


def vendedores(resultado, mercancia="gold") -> set[int]:
    return {p.estacion.market_id for p in resultado.ofertas.get(mercancia, [])}


def compradores(resultado, mercancia="gold") -> set[int]:
    return {p.estacion.market_id for p in resultado.demandas.get(mercancia, [])}


def test_solo_entra_lo_que_esta_dentro_del_radio_no_de_la_caja(base):
    estacion(base, 1, sistema(base, 10, 49))
    estacion(base, 2, sistema(base, 20, 40, 40))  # dentro de la caja, a 56,6 ly
    for market_id in (1, 2):
        vende(base, market_id, "gold", 9000)
    resultado = cargar(base)
    assert vendedores(resultado) == {1}
    assert resultado.estaciones[1].distancia_origen == pytest.approx(49)


@pytest.mark.parametrize(("necesaria", "esperadas"), [("S", {1, 2, 3}), ("M", {2, 3}), ("L", {3})])
def test_la_plataforma_tiene_que_ser_al_menos_la_de_la_nave(base, necesaria, esperadas):
    direccion = sistema(base, 10, 5)
    for market_id, tamano in ((1, "S"), (2, "M"), (3, "L"), (4, None)):
        estacion(base, market_id, direccion, plataforma=tamano)
        vende(base, market_id, "gold", 9000)
    assert vendedores(cargar(base, plataforma=necesaria)) == esperadas


def test_la_distancia_a_la_estrella_se_respeta_y_sin_ella_no_se_entra(base):
    direccion = sistema(base, 10, 5)
    for market_id, ls in ((1, 5000), (2, 5001), (3, None)):
        estacion(base, market_id, direccion, ls=ls)
        vende(base, market_id, "gold", 9000)
    assert vendedores(cargar(base, distancia_max_ls=5000)) == {1}


def test_los_tipos_de_estacion_filtran_y_los_fleet_carrier_nunca_entran(base):
    direccion = sistema(base, 10, 5)
    tipos = {
        1: ("orbital", False),
        2: ("orbital", True),
        3: ("puesto_avanzado", False),
        4: ("puesto_avanzado", True),
        5: ("asentamiento", True),
        6: ("colonizacion", False),
        7: ("fleet_carrier", False),
        8: ("desconocida", False),
    }
    for market_id, (categoria, planetaria) in tipos.items():
        estacion(base, market_id, direccion, categoria=categoria, planetaria=planetaria)
        vende(base, market_id, "gold", 9000)
    assert vendedores(cargar(base)) == {1, 2, 3, 4, 5, 6, 8}
    assert vendedores(cargar(base, tipos=("puerto_planetario",))) == {2, 4, 8}
    assert vendedores(cargar(base, tipos=("orbital", "puesto_avanzado"))) == {1, 3, 8}


def test_la_antiguedad_y_el_origen_del_dato_filtran(base):
    direccion = sistema(base, 10, 5)
    for market_id, horas, origen in ((1, 23, "eddn"), (2, 25, "eddn"), (3, 1, "spansh")):
        estacion(base, market_id, direccion)
        vende(base, market_id, "gold", 9000, horas=horas, origen=origen)
    assert vendedores(cargar(base)) == {1, 3}
    assert vendedores(cargar(base, origenes=("eddn",))) == {1}
    oferta = cargar(base).ofertas_de[1]["gold"]
    assert oferta.horas == pytest.approx(23)


def test_el_stock_minimo_es_un_porcentaje_de_la_bodega(base):
    direccion = sistema(base, 10, 5)
    for market_id, stock in ((1, 100), (2, 99), (3, 0)):
        estacion(base, market_id, direccion)
        vende(base, market_id, "gold", 9000, stock=stock)
    assert vendedores(cargar(base, capacidad=100)) == {1}
    assert vendedores(cargar(base, capacidad=100, stock_minimo_pct=0)) == {1, 2}


def test_los_niveles_desconocidos_de_spansh_no_excluyen_nada(base):
    direccion = sistema(base, 10, 5)
    estacion(base, 1, direccion)
    estacion(base, 2, direccion)
    vende(base, 1, "gold", 9000, origen="spansh", nivel=-1)
    compra(base, 2, "gold", 12000, origen="spansh", nivel=-1)
    resultado = cargar(base)
    assert vendedores(resultado) == {1}
    assert compradores(resultado) == {2}


def test_las_raras_solo_entran_si_se_piden(base):
    base.execute("INSERT INTO commodities (simbolo, rara) VALUES ('lavianbrandy', 1)")
    estacion(base, 1, sistema(base, 10, 5))
    vende(base, 1, "lavianbrandy", 500)
    assert vendedores(cargar(base), "lavianbrandy") == set()
    assert vendedores(cargar(base, raras=True), "lavianbrandy") == {1}
    con_carga = candidatos.cargar(base, perfil(), ORIGEN, AHORA, raras=True)
    assert vendedores(con_carga, "lavianbrandy") == {1}


def test_una_estacion_que_vende_y_compra_aparece_en_los_dos_lados(base):
    estacion(base, 1, sistema(base, 10, 5))
    vende(base, 1, "gold", 9000)
    compra(base, 1, "silver", 5000)
    resultado = cargar(base)
    assert set(resultado.ofertas_de[1]) == {"gold"}
    assert set(resultado.demandas_de[1]) == {"silver"}


# Pasan el filtro de antigüedad, que compara texto: la de 11:00 es de hoy pero sin zona.
@pytest.mark.parametrize("marca", ["ayer", "2026-11-13T11:00:00", "9999-99-99T00:00:00Z"])
def test_un_precio_con_marca_ilegible_se_descarta_sin_romper_la_busqueda(base, marca):
    direccion = sistema(base, 10, 5)
    estacion(base, 1, direccion)
    estacion(base, 2, direccion)
    vende(base, 1, "gold", 9000)
    vende(base, 2, "gold", 9100)
    compra(base, 2, "silver", 5000)
    base.execute("UPDATE market_prices SET observado = ? WHERE market_id = 2", (marca,))
    resultado = cargar(base)
    assert vendedores(resultado) == {1}
    assert compradores(resultado, "silver") == set()
    assert [o.mercancia for o in candidatos.ofertas_de_la_estacion(base, 2, perfil(), AHORA)] == []


def test_las_ofertas_de_la_estacion_actual_no_pasan_por_los_filtros_de_estacion(base):
    direccion = sistema(base, 10, 500)  # fuera del radio
    estacion(base, 1, direccion, plataforma=None, ls=None, categoria="fleet_carrier")
    vende(base, 1, "gold", 9000, horas=300)
    vende(base, 1, "silver", 4000, stock=5)
    ofertas = candidatos.ofertas_de_la_estacion(base, 1, perfil(), AHORA)
    assert [o.mercancia for o in ofertas] == ["gold"]
    assert ofertas[0].estacion.posicion == (500, 0, 0)


def test_una_estacion_actual_desconocida_no_tiene_ofertas(base):
    assert candidatos.ofertas_de_la_estacion(base, 99, perfil(), AHORA) == []


class _ParaTrasLeer:
    """Se activa después de la primera comprobación, como si llegara otra búsqueda a medias."""

    def __init__(self) -> None:
        self.vistas = 0

    def is_set(self) -> bool:
        self.vistas += 1
        return self.vistas > 1


def _muchos_precios(base, filas: int) -> None:
    direccion = sistema(base, 10, 5)
    for market_id in range(filas // 100 + 1):
        estacion(base, market_id, direccion)
        for n in range(100):
            vende(base, market_id, f"m{n}", 1000)


def test_una_busqueda_cancelada_a_medias_deja_de_leer(base):
    _muchos_precios(base, 2 * candidatos.FILAS_ENTRE_COMPROBACIONES)
    parar = _ParaTrasLeer()
    with pytest.raises(candidatos.BusquedaCancelada):
        candidatos.cargar(base, perfil(), ORIGEN, AHORA, parar=parar)
    assert parar.vistas == 2


def test_sin_cancelar_la_busqueda_lee_todo(base):
    direccion = sistema(base, 10, 5)
    estacion(base, 1, direccion)
    vende(base, 1, "gold", 9000)
    resultado = candidatos.cargar(base, perfil(), ORIGEN, AHORA, parar=threading.Event())
    assert vendedores(resultado) == {1}
