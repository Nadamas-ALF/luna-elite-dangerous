"""Archivos de estado que el juego reescribe: Cargo.json y Status.json.

El juego los sustituye enteros, así que una lectura puede coincidir con la
escritura y ver el archivo vacío o cortado; eso no es un error, se reintenta en
la siguiente pasada.
"""

from __future__ import annotations

import json
from pathlib import Path

CARGO = "Cargo.json"
STATUS = "Status.json"


def leer(carpeta: Path, nombre: str) -> dict | None:
    try:
        datos = json.loads((carpeta / nombre).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


def marca(carpeta: Path, nombre: str) -> tuple[int, int] | None:
    """Fecha de modificación y tamaño: lo bastante para saber si cambió."""
    try:
        info = (carpeta / nombre).stat()
    except OSError:
        return None
    return info.st_mtime_ns, info.st_size
