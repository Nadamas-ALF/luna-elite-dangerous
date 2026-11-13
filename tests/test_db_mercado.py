import sqlite3

import pytest

from core import catalogo
from core.db import esquema, mercado
from core.db.escritor import abrir
from core.journal.mercado import Articulo

SISTEMA = 5070611555729


def articulo(simbolo="gold", compra=100, venta=90, stock=10, demanda=0, **cambios) -> Articulo:
    base = {
        "simbolo": simbolo,
        "nombre": "Oro",
        "categoria": "metals",
        "precio_compra": compra,
        "precio_venta": venta,
        "stock": stock,
        "demanda": demanda,
        "nivel_stock": 1,
        "nivel_demanda": 0,
        "rara": False,
    }
    return Articulo(**{**base, **cambios})


def propio(articulos, observado="2026-11-10T05:13:02Z", idioma="es", sistema=True):
    return mercado.MercadoPropio(
        sistema=mercado.Sistema(SISTEMA, "Col 285", (1.0, 2.0, 2.0), 3.0) if sistema else None,
        estacion=mercado.Estacion(42, "Salt Shack", "orbital", "L", 336.5, False),
        observado=observado,
        articulos=tuple(articulos),
        idioma=idioma,
    )


@pytest.fixture
def conexion(tmp_path):
    activa = abrir(tmp_path / "luna.db")
    esquema.migrar(activa)
    yield activa
    activa.close()


def precios(conexion) -> dict[str, tuple]:
    consulta = "SELECT commodity, buy_price, sell_price, stock, origen FROM market_prices"
    return {f[0]: f[1:] for f in conexion.execute(consulta)}


def nombres(conexion, simbolo: str) -> tuple:
    consulta = "SELECT nombre_es, nombre_en FROM commodities WHERE simbolo = ?"
    return conexion.execute(consulta, (simbolo,)).fetchone()


def test_guarda_sistema_estacion_y_precios_con_origen_propio(conexion):
    assert mercado.guardar_propio(conexion, propio([articulo()])) is True

    assert precios(conexion) == {"gold": (100, 90, 10, "propio")}
    assert conexion.execute("SELECT nombre, distancia_centro FROM systems").fetchall() == [
        ("Col 285", 3.0)
    ]
    estacion = "SELECT nombre, categoria, plataforma, distancia_ls, planetaria, system_address"
    assert conexion.execute(f"{estacion} FROM stations").fetchall() == [
        ("Salt Shack", "orbital", "L", 336.5, 0, SISTEMA)
    ]


def test_un_dato_mas_viejo_no_reemplaza_al_guardado(conexion):
    mercado.guardar_propio(conexion, propio([articulo(compra=100)], "2026-11-10T06:00:00Z"))

    viejo = propio([articulo(compra=999)], "2026-11-10T05:00:00Z")

    assert mercado.guardar_propio(conexion, viejo) is False
    assert precios(conexion)["gold"][0] == 100


def test_el_mismo_instante_tampoco_reemplaza(conexion):
    mercado.guardar_propio(conexion, propio([articulo()]))

    assert mercado.guardar_propio(conexion, propio([articulo(compra=5)])) is False


def test_un_dato_mas_nuevo_sustituye_el_mercado_entero(conexion):
    mercado.guardar_propio(conexion, propio([articulo("gold"), articulo("silver")]))

    nuevo = propio([articulo("gold", compra=120)], "2026-11-10T07:00:00Z")
    mercado.guardar_propio(conexion, nuevo)

    assert precios(conexion) == {"gold": (120, 90, 10, "propio")}


def test_no_guarda_los_precios_de_lo_que_la_estacion_no_mueve(conexion):
    sin_movimiento = articulo("platinum", stock=0, demanda=0)

    mercado.guardar_propio(conexion, propio([articulo(), sin_movimiento]))

    assert set(precios(conexion)) == {"gold"}
    assert conexion.execute("SELECT simbolo FROM commodities ORDER BY simbolo").fetchall() == [
        ("gold",),
        ("platinum",),
    ]


def test_el_nombre_localizado_va_a_la_columna_de_su_idioma(conexion):
    mercado.guardar_propio(conexion, propio([articulo(nombre="Oro")], idioma="es"))
    mercado.guardar_propio(
        conexion, propio([articulo(nombre="Gold")], "2026-11-10T07:00:00Z", idioma="en")
    )

    assert nombres(conexion, "gold") == ("Oro", "Gold")


def test_sin_idioma_conocido_no_se_toma_el_nombre(conexion):
    mercado.guardar_propio(conexion, propio([articulo(nombre="Gold")], idioma=None))

    assert nombres(conexion, "gold") == (None, None)


def test_los_nombres_se_guardan_aunque_el_dato_sea_viejo(conexion):
    mercado.guardar_propio(conexion, propio([articulo()], "2026-11-10T06:00:00Z"))

    viejo = propio([articulo("silver", nombre="Plata")], "2026-11-10T05:00:00Z")
    mercado.guardar_propio(conexion, viejo)

    assert nombres(conexion, "silver") == ("Plata", None)


def test_sin_sistema_conocido_la_estacion_se_guarda_igual(conexion):
    mercado.guardar_propio(conexion, propio([articulo()], sistema=False))

    assert conexion.execute("SELECT system_address FROM stations").fetchall() == [(None,)]


def test_una_visita_sin_coordenadas_no_borra_las_conocidas(conexion):
    mercado.guardar_propio(conexion, propio([articulo()]))

    sin_posicion = mercado.Sistema(SISTEMA, "Col 285", None, None)
    mercado.guardar_sistema(conexion, sin_posicion, "2026-11-11T00:00:00Z")

    assert conexion.execute("SELECT x, y, z, distancia_centro FROM systems").fetchall() == [
        (1.0, 2.0, 2.0, 3.0)
    ]


def test_el_esquema_tiene_los_indices_de_busqueda(conexion):
    indices = {f[1] for f in conexion.execute("PRAGMA index_list(market_prices)")}

    assert {"precios_por_venta", "precios_por_compra"} <= indices


def test_un_precio_de_una_estacion_desconocida_viola_la_clave_foranea(conexion):
    with pytest.raises(sqlite3.IntegrityError):
        conexion.execute(
            "INSERT INTO market_prices VALUES (1, 'gold', 1, 1, 1, 1, 1, 1, 'propio', 'x')"
        )


def test_sembrar_no_pisa_un_nombre_que_ya_salio_del_juego(conexion):
    mercado.guardar_propio(conexion, propio([articulo(nombre="Oro del juego")]))

    mercado.sembrar_mercancias(conexion, {"gold": ("Gold", "Oro"), "silver": ("Silver", None)})

    assert nombres(conexion, "gold") == ("Oro del juego", "Gold")
    assert nombres(conexion, "silver") == (None, "Silver")


def test_la_tabla_estatica_trae_las_mercancias_comunes():
    assert catalogo.mercancias()["gold"] == ("Gold", "Oro")


def test_un_sistema_ya_conocido_no_cambia_de_sitio_ni_de_nombre(conexion):
    mercado.guardar_propio(conexion, propio([articulo()]))

    falso = mercado.Sistema(SISTEMA, "Otro nombre", (90.0, 0.0, 0.0), 90.0)
    mercado.guardar_sistema(conexion, falso, "2026-11-12T00:00:00Z")

    assert conexion.execute("SELECT nombre, x, y, z, distancia_centro FROM systems").fetchall() == [
        ("Col 285", 1.0, 2.0, 2.0, 3.0)
    ]
