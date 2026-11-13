"""Que el archivo de la base no guarde gigas vacíos.

SQLite no devuelve al disco el espacio de las filas borradas: lo deja libre dentro
del archivo. Con `auto_vacuum = INCREMENTAL` ese espacio se puede devolver por
tandas (`incremental_vacuum`), sin reescribir la base. Una base nueva se crea ya
así; una anterior se convierte una sola vez con un `VACUUM`, que no puede correr
dentro de una transacción y por eso lo hace el escritor antes de atender trabajos.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path

registro = logging.getLogger("luna.db")

INCREMENTAL = 2
# Páginas que se devuelven en cada trabajo del escritor: tandas cortas que no lo bloquean.
LOTE_DE_PAGINAS = 10_000
# Por debajo de esto (unos 10 MB con páginas de 4 KB) no compensa seguir devolviendo.
UMBRAL_DE_PAGINAS = 2_560
# VACUUM reescribe los datos útiles y el WAL puede crecer otro tanto.
FACTOR_DE_ESPACIO = 2.2
RESERVA_DE_DISCO = 64 * 1024 * 1024

AL_DIA = "al_dia"
CONVERTIDA = "convertida"
SIN_ESPACIO = "sin_espacio"
ERROR = "error"

AVISO_COMPACTANDO = "base_compactando"
AVISO_SIN_ESPACIO = "base_sin_espacio"
AVISO_SIN_COMPACTAR = "base_sin_compactar"


def preparar_base_nueva(conexion: sqlite3.Connection) -> None:
    """Hay que pedirlo antes de crear la primera tabla; después solo lo cambia un VACUUM."""
    if conexion.execute("PRAGMA page_count").fetchone()[0] == 0:
        conexion.execute(f"PRAGMA auto_vacuum = {INCREMENTAL}")


def modo(conexion: sqlite3.Connection) -> int:
    return conexion.execute("PRAGMA auto_vacuum").fetchone()[0]


def paginas_libres(conexion: sqlite3.Connection) -> int:
    return conexion.execute("PRAGMA freelist_count").fetchone()[0]


def _bytes_utiles(conexion: sqlite3.Connection) -> int:
    paginas = conexion.execute("PRAGMA page_count").fetchone()[0]
    tamano = conexion.execute("PRAGMA page_size").fetchone()[0]
    return (paginas - paginas_libres(conexion)) * tamano


def convertir(
    conexion: sqlite3.Connection, ruta: Path, al_empezar: Callable[[], None] = lambda: None
) -> str:
    """Convierte una base anterior a `auto_vacuum` incremental. Una sola vez en la vida de la base.

    No lo intenta si no hay disco para la copia que hace VACUUM: la base sigue
    funcionando igual, solo que sin devolver espacio.
    """
    if modo(conexion) == INCREMENTAL:
        return AL_DIA
    try:
        libre_en_disco = shutil.disk_usage(ruta.parent).free
        necesario = _bytes_utiles(conexion) * FACTOR_DE_ESPACIO + RESERVA_DE_DISCO
    except (OSError, sqlite3.Error):
        registro.exception("no se pudo calcular el espacio para compactar la base")
        return ERROR
    if libre_en_disco < necesario:
        registro.warning(
            "no hay disco para compactar la base: faltan %d bytes", necesario - libre_en_disco
        )
        return SIN_ESPACIO
    al_empezar()
    try:
        conexion.execute(f"PRAGMA auto_vacuum = {INCREMENTAL}")
        conexion.execute("VACUUM")
        conexion.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        convertida = modo(conexion) == INCREMENTAL
    except sqlite3.Error:
        registro.exception("fallo al compactar la base")
        return ERROR
    return CONVERTIDA if convertida else ERROR


def devolver(conexion: sqlite3.Connection, paginas: int = LOTE_DE_PAGINAS) -> tuple[int, int]:
    """Devuelve al archivo hasta `paginas` páginas libres. (libres antes, libres después).

    Hay que leer el resultado del PRAGMA: libera una página por cada fila leída.
    """
    antes = paginas_libres(conexion)
    if antes == 0 or modo(conexion) != INCREMENTAL:
        return antes, antes
    conexion.execute(f"PRAGMA incremental_vacuum({int(paginas)})").fetchall()
    return antes, paginas_libres(conexion)
