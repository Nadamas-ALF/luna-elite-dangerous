"""Por qué una búsqueda sale vacía o corta: cuánto descartó cada filtro (DESIGN.md §4.3).

Los recuentos se hacen aquí y no en la interfaz. Los filtros de estación van en
cascada (cada uno cuenta lo que quita de lo que dejó el anterior), igual que los
de precio; los de saldo y ganancia mínima se miden sobre todos los pares de
compra y venta que quedaron, en un sentido.
Un filtro que no quitó nada vale cero.

Los recuentos de la base son agregados de SQLite y no filas leídas en Python: se
piden justo cuando el usuario aprieta los filtros, y releer los precios del radio
doblaba el tiempo de la búsqueda (revisión del bloque 3: de 2 s a 4,9 s con 100 ly).
"""

from __future__ import annotations

import bisect
import sqlite3
import threading
from datetime import datetime, timedelta

from modules.comercio.engine import candidatos
from modules.comercio.engine.candidatos import BusquedaCancelada, Candidatos, Posicion
from modules.comercio.engine.perfil import Perfil

# Por debajo de esto una búsqueda se considera corta y se explica.
RESULTADOS_CORTOS = 10

# La distancia exacta al origen, al cuadrado: así la esfera se filtra en SQLite, sin raíces.
_ESFERA = " AND (y.x - ?) * (y.x - ?) + (y.y - ?) * (y.y - ?) + (y.z - ?) * (y.z - ?) <= ?"

_ESTACIONES = (
    "SELECT COUNT(*), TOTAL(p), TOTAL(p AND l), TOTAL(p AND l AND t) FROM ("  # noqa: S608
    "SELECT COALESCE(s.plataforma IN ({plataformas}), 0) AS p, "
    "COALESCE(s.distancia_ls <= ?, 0) AS l, COALESCE(({tipos}), 0) AS t "
    + candidatos.CAJA
    + _ESFERA
    + ")"
)

# `viejo` compara la marca como texto, igual que la consulta del motor.
_PRECIOS = (
    "SELECT "  # noqa: S608
    "TOTAL(CASE WHEN viejo THEN oferta + demanda END), "
    "TOTAL(CASE WHEN NOT viejo AND NOT fuente THEN oferta + demanda END), "
    "TOTAL(CASE WHEN NOT viejo AND fuente AND rara THEN oferta + demanda END), "
    "TOTAL(CASE WHEN NOT viejo AND fuente AND NOT rara AND oferta AND stock < ? THEN 1 END), "
    "TOTAL(CASE WHEN NOT viejo AND fuente AND NOT rara AND oferta AND stock >= ? THEN 1 END), "
    "TOTAL(CASE WHEN NOT viejo AND fuente AND NOT rara AND demanda THEN 1 END) "
    "FROM (SELECT p.observado < ? AS viejo, p.origen IN ({origenes}) AS fuente, "
    "(NOT ? AND p.commodity IN (SELECT simbolo FROM commodities WHERE rara = 1)) AS rara, "
    "(p.buy_price > 0 AND p.stock > 0) AS oferta, "
    "(p.demand > 0 AND p.sell_price > 0) AS demanda, p.stock AS stock "
    "FROM market_prices p WHERE p.market_id IN (SELECT s.market_id "
    + candidatos.DESDE
    + _ESFERA
    + ") AND ((p.buy_price > 0 AND p.stock > 0) OR (p.demand > 0 AND p.sell_price > 0)))"
)


def _esfera(perfil: Perfil, centro: Posicion) -> list[float]:
    x, y, z = centro
    return [x, x, y, y, z, z, perfil.distancia_max_ly**2]


def _estaciones(
    conexion: sqlite3.Connection, perfil: Perfil, centro: Posicion
) -> tuple[int, dict[str, int], int]:
    plataformas = candidatos.plataformas_validas(perfil.plataforma)
    caja = candidatos.parametros_de_estacion(perfil, centro)[:6]
    parametros = [*plataformas, perfil.distancia_max_ls, *caja, *_esfera(perfil, centro)]
    sql = candidatos.consulta(_ESTACIONES, perfil)
    en_radio, con_plataforma, con_ls, validas = (
        int(n) for n in conexion.execute(sql, parametros).fetchone()
    )
    descartes = {
        "plataforma": en_radio - con_plataforma,
        "distancia_ls": con_plataforma - con_ls,
        "tipo": con_ls - validas,
    }
    return en_radio, descartes, validas


def _precios(
    conexion: sqlite3.Connection, perfil: Perfil, centro: Posicion, ahora: datetime
) -> tuple[dict[str, int], int, int]:
    """Cada precio es una oferta (se compra ahí), una demanda (se vende ahí) o las dos."""
    limite = candidatos.marca(ahora - timedelta(hours=perfil.antiguedad_max_h))
    stock_minimo = max(perfil.stock_minimo, 1)
    parametros = [
        stock_minimo,
        stock_minimo,
        limite,
        *perfil.origenes,
        perfil.raras,
        *candidatos.parametros_de_estacion(perfil, centro),
        *_esfera(perfil, centro),
    ]
    fila = conexion.execute(candidatos.consulta(_PRECIOS, perfil), parametros).fetchone()
    antiguedad, origen, raras, sin_stock, ofertas, demandas = (int(n) for n in fila)
    cuenta = {
        "antiguedad": antiguedad,
        "origen": origen,
        "raras": raras,
        "stock_minimo": sin_stock,
    }
    return cuenta, ofertas, demandas


def _tratos(cargados: Candidatos, perfil: Perfil) -> dict[str, int]:
    """Todos los pares de cada mercancía, no solo los K extremos que compara el motor (E-27).

    El saldo quita primero el par que no llega a una tonelada; si no, la ganancia mínima.
    """
    cuenta = {"saldo": 0, "ganancia_min": 0}
    for mercancia, ofertas in cargados.ofertas.items():
        demandas = cargados.demandas.get(mercancia)
        if not demandas:
            continue
        pagan = sorted(venta.precio for venta in demandas)
        en_la_misma = {venta.estacion.market_id: venta.precio for venta in demandas}
        for compra in ofertas:
            propio = en_la_misma.get(compra.estacion.market_id)
            if perfil.creditos is not None and compra.precio > perfil.creditos:
                cuenta["saldo"] += _entre(pagan, propio, compra.precio, None)
            else:
                tope = compra.precio + perfil.ganancia_min
                cuenta["ganancia_min"] += _entre(pagan, propio, compra.precio, tope)
    return cuenta


def _entre(pagan: list[int], propio: int | None, desde: int, hasta: int | None) -> int:
    """Precios en `(desde, hasta)` sin contar el de la propia estación; sin `hasta`, sin tope."""
    fin = len(pagan) if hasta is None else bisect.bisect_left(pagan, hasta)
    cuantos = max(fin - bisect.bisect_right(pagan, desde), 0)
    if propio is not None and propio > desde and (hasta is None or propio < hasta):
        cuantos -= 1
    return cuantos


def _seguir(parar: threading.Event | None) -> None:
    if parar is not None and parar.is_set():
        raise BusquedaCancelada


def contar(
    conexion: sqlite3.Connection,
    perfil: Perfil,
    centro: Posicion,
    ahora: datetime,
    cargados: Candidatos,
    parar: threading.Event | None = None,
) -> dict:
    """`cargados` es lo que la búsqueda ya leyó con todos los filtros puestos."""
    _seguir(parar)
    en_radio, por_estacion, validas = _estaciones(conexion, perfil, centro)
    _seguir(parar)
    por_precio, ofertas, demandas = _precios(conexion, perfil, centro, ahora)
    _seguir(parar)
    return {
        "estaciones_en_radio": en_radio,
        "estaciones_validas": validas,
        "ofertas": ofertas,
        "demandas": demandas,
        "descartes": {**por_estacion, **por_precio, **_tratos(cargados, perfil)},
    }
