r"""Lo que hay que saber de Windows y del backend WinForms de pywebview.

Aquí está junto todo el trato con la ventana nativa, para que `main.py` se
quede con el arranque y para que el conocimiento medido en la fase 0 viva en un
solo sitio.

La geometría se lee y se escribe con la misma propiedad, `Bounds` del
formulario, en píxeles físicos. No se pasa por `create_window(x=…, width=…)`
porque pywebview multiplica la posición por el factor de escala del monitor y
la devuelve sin dividir, y porque el autoescalado de WinForms sobre el tamaño
depende del marco de la ventana. Leer y escribir la misma propiedad es
simétrico sin depender de ninguna de las dos cosas.
"""

from __future__ import annotations

import ctypes
import logging

from core.config.ventana import Geometria

registro = logging.getLogger("luna.plataforma")

ESTADO_NORMAL = "Normal"
ESTADO_MAXIMIZADA = "Maximized"


def mostrar_error(titulo: str, mensaje: str) -> None:
    """Empaquetado con PyInstaller no hay consola donde ver una traza."""
    MB_ICONERROR = 0x10
    try:
        ctypes.windll.user32.MessageBoxW(None, mensaje, titulo, MB_ICONERROR)
    except (AttributeError, OSError):
        registro.exception("no se pudo mostrar el aviso nativo: %s", mensaje)


def geometria_de_forma(forma) -> Geometria:
    """Geometría que habrá que restaurar la próxima vez.

    Medido en la fase 0: `RestoreBounds` se queda en los límites de creación
    mientras la ventana está en estado normal, y maximizada `Bounds` devuelve un
    rectángulo que se sale de la pantalla por el ancho del borde.
    """
    estado = str(forma.WindowState)
    limites = forma.Bounds if estado == ESTADO_NORMAL else forma.RestoreBounds
    return Geometria(
        ancho=limites.Width,
        alto=limites.Height,
        x=limites.X,
        y=limites.Y,
        maximizada=estado == ESTADO_MAXIMIZADA,
    )


def aplicar_geometria(forma, geometria: Geometria) -> None:
    """Coloca la ventana ya creada, en píxeles físicos.

    Quien quiera maximizarla lo hace después, con `window.maximize()`, para que
    `RestoreBounds` guarde el tamaño al que volver.
    """
    x = geometria.x if geometria.x is not None else forma.Bounds.X
    y = geometria.y if geometria.y is not None else forma.Bounds.Y
    forma.SetBounds(x, y, geometria.ancho, geometria.alto)
