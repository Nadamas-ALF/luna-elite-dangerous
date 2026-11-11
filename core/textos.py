"""Acceso a los textos de la interfaz.

Vive en el núcleo porque lo necesitan tanto el arranque como la pantalla Estado
y la clase expuesta a la interfaz: los códigos de `core/config/rutas.py` se
convierten aquí en frases.
"""

from __future__ import annotations

import json

from core import recursos

CLAVE_TITULO = ("ventana", "titulo")
CLAVE_ERROR_ARRANQUE = ("errores", "arranque")
CLAVE_SIN_WEBVIEW2 = ("errores", "sin_webview2")

GRUPO_DATOS = "datos"


def cargar() -> dict:
    """Puede lanzar OSError o ValueError: es.json forma parte de la instalación."""
    return json.loads(recursos.ruta("ui", "i18n", "es.json").read_text(encoding="utf-8"))


def texto(claves: tuple[str, ...], diccionario: dict) -> str | None:
    nodo: object = diccionario
    for clave in claves:
        if not isinstance(nodo, dict) or clave not in nodo:
            return None
        nodo = nodo[clave]
    return nodo if isinstance(nodo, str) else None


def frase_de_codigo(codigo: str, diccionario: dict) -> str | None:
    """Frase de un motivo o aviso de la carpeta de datos."""
    return texto((GRUPO_DATOS, codigo), diccionario)


def con_detalle(claves: tuple[str, ...], diccionario: dict, error: object) -> str:
    """Mensaje de error con su detalle, sin romperse si la plantilla está mal.

    Se usa dentro del manejador de errores, así que no puede lanzar: `es.json`
    lo edita el usuario y un `{` suelto convertiría el aviso en una muerte
    silenciosa.
    """
    plantilla = texto(claves, diccionario)
    if plantilla is None:
        return str(error)
    try:
        return plantilla.format(error=error)
    except (KeyError, IndexError, ValueError):
        return f"{plantilla} ({error})"
