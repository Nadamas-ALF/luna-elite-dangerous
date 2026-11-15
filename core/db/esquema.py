"""Esquema de la base de datos y sus migraciones.

La versión vive en `PRAGMA user_version`. Cada migración se aplica una sola vez,
en orden, dentro de su propia transacción. Las tablas de mercado (sección 5.1)
llegan con las fases que las usan.
"""

from __future__ import annotations

import sqlite3

MIGRACIONES: tuple[str, ...] = (
    """
    CREATE TABLE commanders (
        fid     TEXT PRIMARY KEY,
        nombre  TEXT NOT NULL,
        visto   TEXT NOT NULL
    );
    CREATE TABLE ships (
        fid             TEXT    NOT NULL REFERENCES commanders(fid),
        ship_id         INTEGER NOT NULL,
        modelo          TEXT    NOT NULL,
        nombre          TEXT    NOT NULL,
        capacidad_carga INTEGER NOT NULL,
        rango_vacio     REAL,
        rango_cargado   REAL,
        plataforma      TEXT,
        actualizado     TEXT    NOT NULL,
        PRIMARY KEY (fid, ship_id)
    );
    """,
    """
    CREATE TABLE systems (
        system_address    INTEGER PRIMARY KEY,
        nombre            TEXT NOT NULL,
        x                 REAL,
        y                 REAL,
        z                 REAL,
        distancia_centro  REAL,
        actualizado       TEXT NOT NULL
    );
    CREATE TABLE stations (
        market_id       INTEGER PRIMARY KEY,
        system_address  INTEGER REFERENCES systems(system_address),
        nombre          TEXT    NOT NULL,
        categoria       TEXT    NOT NULL,
        plataforma      TEXT,
        distancia_ls    REAL,
        planetaria      INTEGER NOT NULL,
        actualizado     TEXT    NOT NULL
    );
    CREATE TABLE commodities (
        simbolo     TEXT PRIMARY KEY,
        nombre_en   TEXT,
        nombre_es   TEXT,
        categoria   TEXT,
        rara        INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE market_prices (
        market_id      INTEGER NOT NULL REFERENCES stations(market_id) ON DELETE CASCADE,
        commodity      TEXT    NOT NULL,
        buy_price      INTEGER NOT NULL,
        sell_price     INTEGER NOT NULL,
        stock          INTEGER NOT NULL,
        demand         INTEGER NOT NULL,
        stock_bracket  INTEGER NOT NULL,
        demand_bracket INTEGER NOT NULL,
        origen         TEXT    NOT NULL,
        observado      TEXT    NOT NULL,
        PRIMARY KEY (market_id, commodity)
    ) WITHOUT ROWID;
    CREATE INDEX precios_por_venta ON market_prices (commodity, sell_price);
    CREATE INDEX precios_por_compra ON market_prices (commodity, buy_price);
    """,
    # commodity/3 de EDDN trae el nombre del sistema y no su dirección.
    "CREATE INDEX sistemas_por_nombre ON systems (nombre);",
    # «Sistemas a menos de X ly»: una caja sobre este índice y la distancia exacta
    # después. R*Tree no compensa (docs/decisiones.md).
    "CREATE INDEX sistemas_por_posicion ON systems (x, y, z);",
    # De dónde salió cada sistema: lo que llega por EDDN no está autenticado y es
    # provisional; el journal propio y Spansh mandan sobre un nombre o unas coordenadas.
    "ALTER TABLE systems ADD COLUMN fuente TEXT NOT NULL DEFAULT 'eddn';",
    # La retención busca los mercados caducados por su marca sin recorrer la tabla entera.
    "CREATE INDEX precios_por_antiguedad ON market_prices (observado);",
    # Buscar las estaciones de un sistema, para borrarlas o saber si quedan.
    "CREATE INDEX estaciones_por_sistema ON stations (system_address);",
    # Perfiles de búsqueda guardados (5.2). No dependen del comandante ni de la nave:
    # se pueden usar desde cualquiera. «Panther» y «panther» son el mismo perfil.
    """
    CREATE TABLE search_profiles (
        nombre     TEXT PRIMARY KEY COLLATE NOCASE,
        parametros TEXT NOT NULL
    );
    """,
)


class BaseDeDatosPosterior(RuntimeError):
    """La base la creó una versión más nueva de LUNA y esta no la entiende."""


def version(conexion: sqlite3.Connection) -> int:
    return conexion.execute("PRAGMA user_version").fetchone()[0]


def migrar(conexion: sqlite3.Connection) -> None:
    actual = version(conexion)
    if actual > len(MIGRACIONES):
        raise BaseDeDatosPosterior(f"version {actual}, esta LUNA llega a {len(MIGRACIONES)}")
    for numero, script in enumerate(MIGRACIONES[actual:], start=actual + 1):
        # executescript confirma lo pendiente antes de ejecutar, así que la
        # transacción se abre dentro del propio script.
        conexion.executescript(f"BEGIN;{script}PRAGMA user_version = {numero};COMMIT;")
