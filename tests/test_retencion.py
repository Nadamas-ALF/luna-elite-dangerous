import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from core.db import esquema, retencion
from core.db.mercado import ORIGEN_EDDN, ORIGEN_PROPIO, ORIGEN_SPANSH
from core.db.retencion import Reglas
from core.esfera import Esfera

AHORA = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)
SOL = Esfera("Sol", (0.0, 0.0, 0.0), 100.0)
REGLAS = Reglas(visitados_dias=3, antiguedad_maxima_dias=30)


def hace(dias: float) -> str:
    return (AHORA - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def base():
    conexion = sqlite3.connect(":memory:", isolation_level=None)
    conexion.execute("PRAGMA foreign_keys = ON")
    esquema.migrar(conexion)
    yield conexion
    conexion.close()


def sistema(base, direccion: int, x: float, y: float = 0.0, z: float = 0.0) -> int:
    base.execute(
        "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, actualizado) "
        "VALUES (?, ?, ?, ?, ?, 0, ?)",
        (direccion, f"S{direccion}", x, y, z, hace(0)),
    )
    return direccion


def estacion(base, market_id: int, direccion: int | None, origen: str, dias: float) -> int:
    base.execute(
        "INSERT INTO stations (market_id, system_address, nombre, categoria, planetaria, "
        "actualizado) VALUES (?, ?, ?, 'orbital', 0, ?)",
        (market_id, direccion, f"E{market_id}", hace(dias)),
    )
    base.execute(
        "INSERT INTO market_prices VALUES (?, 'gold', 0, 9000, 0, 100, 0, 3, ?, ?)",
        (market_id, origen, hace(dias)),
    )
    return market_id


def mercados(base) -> set[int]:
    return {m for (m,) in base.execute("SELECT DISTINCT market_id FROM market_prices")}


def limpiar(base, esfera=SOL, reglas=REGLAS):
    return retencion.limpiar(base, esfera, reglas, AHORA)


def test_dentro_de_la_esfera_se_conserva_el_dato_reciente(base):
    estacion(base, 1, sistema(base, 10, 50), ORIGEN_EDDN, 5)
    assert limpiar(base).total == 0
    assert mercados(base) == {1}


def test_un_precio_de_mas_de_30_dias_se_borra_aunque_este_dentro(base):
    estacion(base, 1, sistema(base, 10, 50), ORIGEN_SPANSH, 31)
    estacion(base, 2, sistema(base, 11, 60), ORIGEN_SPANSH, 29)
    resultado = limpiar(base)
    assert mercados(base) == {2}
    assert resultado.precios_viejos == 1


def test_la_antiguedad_maxima_se_puede_configurar(base):
    estacion(base, 1, sistema(base, 10, 50), ORIGEN_EDDN, 8)
    limpiar(base, reglas=Reglas(antiguedad_maxima_dias=7))
    assert mercados(base) == set()


def test_la_estacion_dentro_se_queda_aunque_pierda_sus_precios(base):
    estacion(base, 1, sistema(base, 10, 50), ORIGEN_SPANSH, 31)
    limpiar(base)
    assert base.execute("SELECT count(*) FROM stations").fetchone() == (1,)
    assert base.execute("SELECT count(*) FROM systems").fetchone() == (1,)


def test_fuera_de_la_esfera_un_mercado_visitado_dura_tres_dias(base):
    estacion(base, 1, sistema(base, 10, 500), ORIGEN_PROPIO, 2)
    estacion(base, 2, sistema(base, 11, 500), ORIGEN_PROPIO, 4)
    limpiar(base)
    assert mercados(base) == {1}


def test_fuera_de_la_esfera_lo_que_no_visito_el_jugador_se_borra_ya(base):
    estacion(base, 1, sistema(base, 10, 500), ORIGEN_EDDN, 0)
    estacion(base, 2, sistema(base, 11, 500), ORIGEN_SPANSH, 0)
    resultado = limpiar(base)
    assert mercados(base) == set()
    assert resultado.precios_fuera == 2


def test_la_estacion_y_el_sistema_de_fuera_se_van_con_sus_precios(base):
    estacion(base, 1, sistema(base, 10, 500), ORIGEN_EDDN, 0)
    resultado = limpiar(base)
    assert base.execute("SELECT count(*) FROM stations").fetchone() == (0,)
    assert base.execute("SELECT count(*) FROM systems").fetchone() == (0,)
    assert (resultado.estaciones, resultado.sistemas) == (1, 1)


def test_un_sistema_de_fuera_con_un_mercado_visitado_reciente_se_queda_entero(base):
    estacion(base, 1, sistema(base, 10, 500), ORIGEN_PROPIO, 1)
    limpiar(base)
    assert base.execute("SELECT count(*) FROM stations").fetchone() == (1,)
    assert base.execute("SELECT count(*) FROM systems").fetchone() == (1,)


def test_un_sistema_de_fuera_con_otra_estacion_viva_no_se_borra(base):
    direccion = sistema(base, 10, 500)
    estacion(base, 1, direccion, ORIGEN_PROPIO, 1)
    estacion(base, 2, direccion, ORIGEN_EDDN, 1)
    limpiar(base)
    assert mercados(base) == {1}
    assert base.execute("SELECT count(*) FROM systems").fetchone() == (1,)


def test_el_borde_de_la_esfera_cuenta_como_dentro(base):
    estacion(base, 1, sistema(base, 10, 100.0), ORIGEN_EDDN, 0)
    limpiar(base)
    assert mercados(base) == {1}


def test_un_sistema_sin_coordenadas_se_trata_como_fuera(base):
    base.execute(
        "INSERT INTO systems (system_address, nombre, actualizado) VALUES (10, 'Raro', ?)",
        (hace(0),),
    )
    estacion(base, 1, 10, ORIGEN_EDDN, 0)
    limpiar(base)
    assert mercados(base) == set()


def test_una_estacion_sin_sistema_se_trata_como_fuera(base):
    estacion(base, 1, None, ORIGEN_EDDN, 0)
    limpiar(base)
    assert base.execute("SELECT count(*) FROM stations").fetchone() == (0,)


def test_las_tablas_del_comandante_no_se_tocan(base):
    base.execute("INSERT INTO commanders VALUES ('F1', 'CMDR', ?)", (hace(100),))
    base.execute(
        "INSERT INTO ships VALUES ('F1', 1, 'python', 'N', 100, 20.0, 15.0, 'M', ?)", (hace(100),)
    )
    limpiar(base)
    assert base.execute("SELECT count(*) FROM commanders").fetchone() == (1,)
    assert base.execute("SELECT count(*) FROM ships").fetchone() == (1,)


def test_limpiar_dos_veces_no_cambia_nada_la_segunda(base):
    estacion(base, 1, sistema(base, 10, 500), ORIGEN_EDDN, 0)
    estacion(base, 2, sistema(base, 11, 50), ORIGEN_EDDN, 0)
    limpiar(base)
    assert limpiar(base).total == 0


def test_achicar_la_esfera_borra_lo_que_queda_fuera(base):
    estacion(base, 1, sistema(base, 10, 50), ORIGEN_SPANSH, 0)
    estacion(base, 2, sistema(base, 11, 90), ORIGEN_SPANSH, 0)
    retencion.aplicar_esfera(base, Esfera("Sol", (0.0, 0.0, 0.0), 60.0), REGLAS, AHORA)
    assert mercados(base) == {1}


def test_mover_el_centro_recalcula_las_distancias_y_limpia_con_el_nuevo(base):
    estacion(base, 1, sistema(base, 10, 50), ORIGEN_SPANSH, 0)
    estacion(base, 2, sistema(base, 11, -90), ORIGEN_SPANSH, 0)
    nueva = Esfera("Lejos", (100.0, 0.0, 0.0), 80.0)
    retencion.aplicar_esfera(base, nueva, REGLAS, AHORA)
    assert mercados(base) == {1}
    (distancia,) = base.execute(
        "SELECT distancia_centro FROM systems WHERE system_address = 10"
    ).fetchone()
    assert distancia == pytest.approx(50.0)


def test_recalcular_no_toca_los_sistemas_sin_coordenadas(base):
    base.execute(
        "INSERT INTO systems (system_address, nombre, distancia_centro, actualizado) "
        "VALUES (10, 'Raro', 7.0, ?)",
        (hace(0),),
    )
    assert retencion.recalcular_distancias(base, SOL) == 0
    assert base.execute("SELECT distancia_centro FROM systems").fetchone() == (7.0,)


def test_el_indice_espacial_se_usa_en_la_busqueda_por_caja(base):
    plan = base.execute(
        "EXPLAIN QUERY PLAN SELECT system_address FROM systems "
        "WHERE x BETWEEN 0 AND 10 AND y BETWEEN 0 AND 10 AND z BETWEEN 0 AND 10"
    ).fetchall()
    assert "sistemas_por_posicion" in str(plan)


def varios_mercados_viejos(base, cantidad: int) -> None:
    direccion = sistema(base, 10, 50)
    for market_id in range(1, cantidad + 1):
        estacion(base, market_id, direccion, ORIGEN_SPANSH, 40)


def test_la_limpieza_borra_por_lotes_y_avisa_de_que_queda_mas(base):
    varios_mercados_viejos(base, 5)

    primero = retencion.limpiar(base, SOL, REGLAS, AHORA, lote=2)
    assert primero.precios_viejos == 2
    assert primero.incompleta
    assert len(mercados(base)) == 3


def test_repetir_la_limpieza_acaba_y_borra_lo_mismo_que_de_una_vez(base):
    varios_mercados_viejos(base, 5)

    total = retencion.Limpieza()
    for _ in range(10):
        lote = retencion.limpiar(base, SOL, REGLAS, AHORA, lote=2)
        total += lote
        if not lote.incompleta:
            break
    assert not lote.incompleta
    assert total.precios_viejos == 5
    assert mercados(base) == set()


def test_un_lote_incompleto_no_se_queda_en_bucle_con_mercados_que_se_conservan(base):
    # Visitados fuera de la esfera y recientes: se conservan y no cuentan como trabajo pendiente.
    direccion = sistema(base, 10, 500)
    for market_id in range(1, 6):
        estacion(base, market_id, direccion, ORIGEN_PROPIO, 1)

    resultado = retencion.limpiar(base, SOL, REGLAS, AHORA, lote=2)

    assert not resultado.incompleta
    assert len(mercados(base)) == 5


def test_los_lotes_tambien_borran_estaciones_y_sistemas_de_fuera(base):
    for numero in range(1, 6):
        estacion(base, numero, sistema(base, 100 + numero, 500), ORIGEN_EDDN, 0)

    total = retencion.Limpieza()
    for _ in range(10):
        lote = retencion.limpiar(base, SOL, REGLAS, AHORA, lote=2)
        total += lote
        if not lote.incompleta:
            break
    assert (total.precios_fuera, total.estaciones, total.sistemas) == (5, 5, 5)
    assert base.execute("SELECT count(*) FROM systems").fetchone() == (0,)


def test_la_limpieza_de_viejos_usa_el_indice_de_antiguedad(base):
    plan = base.execute(
        "EXPLAIN QUERY PLAN " + retencion.CONSULTA_DE_CADUCADOS, ("x", 5)
    ).fetchall()
    assert "SEARCH" in str(plan)
    assert "precios_por_antiguedad" in str(plan)


def test_sumar_lotes_acumula_y_conserva_si_el_ultimo_quedo_incompleto():
    suma = retencion.Limpieza(1, 2, 3, 4, 5, incompleta=True) + retencion.Limpieza(
        10, 20, 30, 40, 50, incompleta=False
    )
    assert (suma.precios_viejos, suma.sistemas, suma.impostores) == (11, 44, 55)
    assert not suma.incompleta
