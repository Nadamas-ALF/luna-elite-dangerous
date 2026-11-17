"""Base en memoria con el esquema real, para las pruebas del motor de comercio."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from core.db import esquema
from modules.comercio.engine.perfil import Perfil

AHORA = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)


def hace(horas: float) -> str:
    return (AHORA - timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")


def base_vacia() -> sqlite3.Connection:
    conexion = sqlite3.connect(":memory:", isolation_level=None)
    esquema.migrar(conexion)
    return conexion


def sistema(conexion, direccion: int, x: float, y: float = 0.0, z: float = 0.0, nombre=None) -> int:
    conexion.execute(
        "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, actualizado, "
        "fuente) VALUES (?, ?, ?, ?, ?, 0, ?, 'spansh')",
        (direccion, nombre or f"S{direccion}", x, y, z, hace(0)),
    )
    return direccion


def estacion(
    conexion,
    market_id: int,
    direccion: int,
    categoria: str = "orbital",
    plataforma: str | None = "L",
    ls: float | None = 100.0,
    planetaria: bool = False,
) -> int:
    conexion.execute(
        "INSERT INTO stations (market_id, system_address, nombre, categoria, plataforma, "
        "distancia_ls, planetaria, actualizado) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            market_id,
            direccion,
            f"E{market_id}",
            categoria,
            plataforma,
            ls,
            int(planetaria),
            hace(0),
        ),
    )
    return market_id


def vende(conexion, market_id, mercancia, precio, stock=10_000, horas=0.5, origen="eddn", nivel=2):
    _precio(conexion, market_id, mercancia, precio, 0, stock, 0, nivel, 0, origen, horas)


def compra(
    conexion, market_id, mercancia, precio, demanda=10_000, horas=0.5, origen="eddn", nivel=2
):
    _precio(conexion, market_id, mercancia, 0, precio, 0, demanda, 0, nivel, origen, horas)


def vende_y_compra(conexion, market_id, mercancia, compra_, venta, horas=0.5):
    """Una sola fila con los dos lados, como algunos mercados del juego."""
    _precio(conexion, market_id, mercancia, compra_, venta, 1000, 1000, 2, 2, "eddn", horas)


def _precio(conexion, market_id, mercancia, compra_, venta, stock, demanda, ns, nd, origen, horas):
    conexion.execute(
        "INSERT INTO market_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (market_id, mercancia, compra_, venta, stock, demanda, ns, nd, origen, hace(horas)),
    )


def perfil(**cambios) -> Perfil:
    valores = {
        "capacidad": 100,
        "rango": 20.0,
        "plataforma": "L",
        "creditos": None,
        "origen": "S1",
        "stock_minimo": 100,
    }
    return Perfil(**{**valores, **cambios})
