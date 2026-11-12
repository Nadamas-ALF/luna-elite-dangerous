r"""Dónde está el journal.

Se resuelve con la carpeta conocida *Partidas guardadas* de Windows y no con
`%USERPROFILE%\Saved Games`, porque el usuario puede haberla movido (sección 4.1).
"""

from __future__ import annotations

import ctypes
import uuid
from ctypes import wintypes
from pathlib import Path

# FOLDERID_SavedGames
_SAVED_GAMES = uuid.UUID("4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4")
SUBCARPETA = ("Frontier Developments", "Elite Dangerous")


class _Guid(ctypes.Structure):
    _fields_ = (
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    )


def _guid(valor: uuid.UUID) -> _Guid:
    return _Guid(
        valor.time_low,
        valor.time_mid,
        valor.time_hi_version,
        (ctypes.c_ubyte * 8)(*valor.bytes[8:]),
    )


def partidas_guardadas() -> Path | None:
    """Ruta real de *Partidas guardadas*, o None si Windows no la resuelve."""
    ruta = ctypes.c_wchar_p()
    try:
        resultado = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(_guid(_SAVED_GAMES)), 0, None, ctypes.byref(ruta)
        )
        if resultado != 0 or not ruta.value:
            return None
        return Path(ruta.value)
    except (AttributeError, OSError):
        return None
    finally:
        ctypes.windll.ole32.CoTaskMemFree(ruta)


def por_defecto() -> Path | None:
    base = partidas_guardadas()
    return base.joinpath(*SUBCARPETA) if base else None


def resolver(configurada: str | None) -> Path | None:
    """La carpeta elegida por el usuario si existe; si no, la de Windows."""
    if configurada:
        elegida = Path(configurada)
        if elegida.is_dir():
            return elegida
    detectada = por_defecto()
    return detectada if detectada and detectada.is_dir() else None
