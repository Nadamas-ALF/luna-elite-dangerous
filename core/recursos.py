r"""Rutas de los recursos de solo lectura que LUNA trae consigo: ui/ y data/.

No comparten raíz con los datos del usuario (`core/config/rutas.py`):
PyInstaller extrae lo empaquetado en `sys._MEIPASS`, que no es la carpeta del
.exe. La sección 10.2 de SPEC.md exige que la interfaz se resuelva por ruta
absoluta también dentro del ejecutable.
"""

from __future__ import annotations

import sys
from pathlib import Path


def carpeta_de_recursos() -> Path:
    interna = getattr(sys, "_MEIPASS", None)
    return Path(interna) if interna else Path(__file__).resolve().parents[1]


def ruta(*partes: str) -> Path:
    destino = carpeta_de_recursos().joinpath(*partes)
    if not destino.exists():
        raise FileNotFoundError(destino)
    return destino


def url_de_la_interfaz() -> str:
    """URL file:// de index.html.

    Con una ruta absoluta a secas, pywebview la toma por "local" y levanta su
    servidor HTTP aunque http_server sea False (`webview.util.is_local_url`).
    """
    return ruta("ui", "index.html").resolve().as_uri()
