"""Preparar un cambio de centro o de radio de la esfera (regla 6 de la sección 5.4).

Aquí no se cambia nada: se averigua lo que la interfaz debe mostrar antes de
pedir confirmación (qué centro es, si hace falta descargar y cuánto pesa).
"""

from __future__ import annotations

import math
import sqlite3
from contextlib import closing
from pathlib import Path

from core.config import ajustes
from core.db.escritor import abrir_lectura
from core.db.mercado import FUENTE_EDDN
from core.esfera import Esfera
from core.spansh import descarga
from core.spansh.descarga import Abrir, ErrorDeDescarga

MOTIVO_DESCONOCIDO = "desconocido"
MOTIVO_AMBIGUO = "ambiguo"
MOTIVO_NOMBRE = "nombre"
MOTIVO_RADIO = "radio"

LARGO_MAXIMO_DE_NOMBRE = 100
_TOLERANCIA = 1 + 1e-9


class ErrorDeCambio(Exception):
    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


def validar_radio(radio: object) -> float:
    numero = isinstance(radio, (int, float)) and not isinstance(radio, bool)
    if not numero or not math.isfinite(radio) or not 0 < radio <= ajustes.RADIO_MAXIMO:
        raise ErrorDeCambio(MOTIVO_RADIO)
    return float(radio)


def resolver_centro(base: Path | None, nombre: object) -> Esfera:
    """La esfera de radio 0 centrada en el sistema llamado así; el radio lo pone quien llama.

    El Sol se conoce siempre. Cualquier otro tiene que estar en la base (visitado,
    llegado por EDDN o descargado de Spansh): no hay otra forma de saber dónde está.
    """
    if not isinstance(nombre, str) or not nombre.strip() or len(nombre) > LARGO_MAXIMO_DE_NOMBRE:
        raise ErrorDeCambio(MOTIVO_NOMBRE)
    limpio = nombre.strip()
    if limpio.casefold() == ajustes.CENTRO_NOMBRE_POR_DEFECTO.casefold():
        return Esfera(ajustes.CENTRO_NOMBRE_POR_DEFECTO, ajustes.CENTRO_POR_DEFECTO, 0.0)
    coincidencias = _buscar(base, limpio)
    if not coincidencias:
        raise ErrorDeCambio(MOTIVO_DESCONOCIDO)
    if len(set(coincidencias)) > 1:
        # Un duplicado provisional de EDDN no puede quitarle el nombre a un sistema fiable.
        coincidencias = [c for c in coincidencias if c[4] != FUENTE_EDDN]
    if len(set(coincidencias)) != 1:
        raise ErrorDeCambio(MOTIVO_AMBIGUO)
    nombre_real, x, y, z, _ = coincidencias[0]
    return Esfera(nombre_real, (x, y, z), 0.0)


def _buscar(base: Path | None, nombre: str) -> list[tuple[str, float, float, float, str]]:
    if base is None or not base.exists():
        return []
    try:
        with closing(abrir_lectura(base)) as conexion:
            return conexion.execute(
                "SELECT nombre, x, y, z, fuente FROM systems "
                "WHERE nombre = ? COLLATE NOCASE AND x IS NOT NULL AND y IS NOT NULL "
                "AND z IS NOT NULL",
                (nombre,),
            ).fetchall()
    except sqlite3.Error:
        return []


def esfera_dentro(interior: Esfera, exterior: Esfera) -> bool:
    """Si `interior` cabe entera dentro de `exterior`."""
    alcance = math.dist(exterior.centro, interior.centro) + interior.radio
    return alcance <= exterior.radio * _TOLERANCIA


def descarga_necesaria(cubierta: Esfera | None, nueva: Esfera) -> bool:
    """Si la esfera nueva cabe entera dentro de lo que sigue guardado, no hay nada que bajar."""
    return cubierta is None or not esfera_dentro(nueva, cubierta)


def cobertura_tras_cambiar(cobertura: Esfera | None, nueva: Esfera) -> Esfera | None:
    """Lo que queda guardado de una descarga cuando la esfera pasa a ser `nueva` sin descargar.

    La limpieza borra lo que cae fuera de `nueva`. Si `nueva` cabe dentro de lo guardado,
    queda `nueva`; si lo guardado cabe dentro de `nueva`, no se borra nada; si se solapan
    sin más, queda una intersección que no es una esfera y no se puede garantizar nada.
    """
    if cobertura is None:
        return None
    if esfera_dentro(nueva, cobertura):
        return nueva
    return cobertura if esfera_dentro(cobertura, nueva) else None


def tamano_del_volcado(abrir: Abrir = descarga.abrir_https) -> int:
    """Bytes que pesa hoy el volcado, pidiendo un solo byte (el archivo no se baja)."""
    try:
        with abrir(descarga.URL, {"Range": "bytes=0-0"}) as respuesta:
            if respuesta.status == 206:
                total = respuesta.headers.get("Content-Range", "").rpartition("/")[2]
            else:
                total = respuesta.headers.get("Content-Length", "")
    except ErrorDeDescarga:
        raise
    except OSError as error:
        raise ErrorDeDescarga(descarga.MOTIVO_RED, type(error).__name__) from error
    if not total.isdigit() or int(total) <= 0:
        raise ErrorDeDescarga(descarga.MOTIVO_HTTP, "sin tamaño")
    return int(total)
