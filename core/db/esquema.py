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
