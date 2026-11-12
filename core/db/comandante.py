"""Tablas del comandante (sección 5.2): trabajos para el hilo escritor.

Nunca se borran automáticamente (regla 7 de la sección 5.4), por eso solo hay
altas y actualizaciones.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class FichaDeNave:
    fid: str
    ship_id: int
    modelo: str
    nombre: str
    capacidad_carga: int
    rango_vacio: float | None
    rango_cargado: float | None
    plataforma: str | None
    actualizado: str


def registrar_comandante(conexion: sqlite3.Connection, fid: str, nombre: str, visto: str) -> None:
    conexion.execute(
        "INSERT INTO commanders (fid, nombre, visto) VALUES (?, ?, ?) "
        "ON CONFLICT(fid) DO UPDATE SET nombre = excluded.nombre, visto = excluded.visto",
        (fid, nombre, visto),
    )


def guardar_nave(conexion: sqlite3.Connection, ficha: FichaDeNave) -> None:
    conexion.execute(
        "INSERT INTO ships (fid, ship_id, modelo, nombre, capacidad_carga, rango_vacio, "
        "rango_cargado, plataforma, actualizado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(fid, ship_id) DO UPDATE SET modelo = excluded.modelo, "
        "nombre = excluded.nombre, capacidad_carga = excluded.capacidad_carga, "
        "rango_vacio = excluded.rango_vacio, rango_cargado = excluded.rango_cargado, "
        "plataforma = excluded.plataforma, actualizado = excluded.actualizado",
        (
            ficha.fid,
            ficha.ship_id,
            ficha.modelo,
            ficha.nombre,
            ficha.capacidad_carga,
            ficha.rango_vacio,
            ficha.rango_cargado,
            ficha.plataforma,
            ficha.actualizado,
        ),
    )
