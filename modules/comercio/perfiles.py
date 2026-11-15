"""Perfiles de búsqueda guardados con nombre (7.1, tabla `search_profiles`).

Guardar y borrar son trabajos para el hilo escritor; listar usa una conexión de
lectura. Un perfil se guarda entero, como el JSON que da `Perfil.a_dict`.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass

from modules.comercio.engine.perfil import Perfil, PerfilInvalido, desde_dict

registro = logging.getLogger("luna.comercio.perfiles")


@dataclass(frozen=True)
class PerfilGuardado:
    nombre: str
    perfil: Perfil


def guardar(conexion: sqlite3.Connection, nombre: str, perfil: Perfil) -> None:
    """Uno con el mismo nombre, sin distinguir mayúsculas, se sustituye."""
    conexion.execute(
        "INSERT INTO search_profiles (nombre, parametros) VALUES (?, ?) "
        "ON CONFLICT(nombre) DO UPDATE SET nombre = excluded.nombre, "
        "parametros = excluded.parametros",
        (nombre, json.dumps(perfil.a_dict(), ensure_ascii=False)),
    )


def borrar(conexion: sqlite3.Connection, nombre: str) -> None:
    conexion.execute("DELETE FROM search_profiles WHERE nombre = ?", (nombre,))


def listar(conexion: sqlite3.Connection, tope_antiguedad_dias: int) -> list[PerfilGuardado]:
    """Por nombre. Uno que ya no se entiende se salta y queda en el registro."""
    guardados = []
    for nombre, parametros in conexion.execute(
        "SELECT nombre, parametros FROM search_profiles ORDER BY nombre"
    ):
        perfil = _leer(parametros, tope_antiguedad_dias)
        if perfil is None:
            registro.warning("perfil guardado ilegible: %r", nombre)
        else:
            guardados.append(PerfilGuardado(nombre, perfil))
    return guardados


def _leer(parametros: str, tope_antiguedad_dias: int) -> Perfil | None:
    try:
        datos = json.loads(parametros)
    except ValueError:
        return None
    if not isinstance(datos, dict):
        return None
    try:
        return desde_dict(_recortar(datos, tope_antiguedad_dias), tope_antiguedad_dias)
    except PerfilInvalido:
        return None


def _recortar(datos: dict, tope_antiguedad_dias: int) -> dict:
    """Si el tope bajó después de guardarlo, el perfil se usa con el tope nuevo."""
    horas = datos.get("antiguedad_max_h")
    tope = tope_antiguedad_dias * 24.0
    if isinstance(horas, (int, float)) and not isinstance(horas, bool) and horas > tope:
        return {**datos, "antiguedad_max_h": tope}
    return datos
