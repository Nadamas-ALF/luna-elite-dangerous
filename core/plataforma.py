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
import sys
import time
from collections.abc import Callable

from core.config.ventana import Geometria

registro = logging.getLogger("luna.plataforma")

ESTADO_NORMAL = "Normal"
ESTADO_MAXIMIZADA = "Maximized"


# Atributos de DwmSetWindowAttribute (learn.microsoft.com, DWMWINDOWATTRIBUTE). Los colores
# de la barra existen desde Windows 11 (compilación 22000); el modo oscuro, desde Windows 10.
DWMWA_MODO_OSCURO = 20
DWMWA_COLOR_BORDE = 34
DWMWA_COLOR_BARRA = 35
DWMWA_COLOR_TEXTO = 36
COMPILACION_CON_COLORES = 22000

# Los de `--bg` y `--text` de ui/css/base.css y de ui/css/lunar.css (por tema); una prueba
# comprueba que siguen iguales.
COLORES_DE_BARRA = {
    "sobrio": ((0x0A, 0x12, 0x20), (0xEA, 0xF4, 0xFF)),
    "lunar": ((0x06, 0x0D, 0x1C), (0xEE, 0xF6, 0xFF)),
}


def _colorref(rgb: tuple[int, int, int]) -> int:
    rojo, verde, azul = rgb
    return rojo | verde << 8 | azul << 16


def _atributo(manejador: int, atributo: int, valor: int) -> bool:
    dato = ctypes.c_int(valor)
    resultado = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        ctypes.c_void_p(manejador), atributo, ctypes.byref(dato), ctypes.sizeof(dato)
    )
    return resultado == 0


def en_el_hilo_de_la_interfaz(forma, funcion: Callable[[], None]) -> None:
    """Ejecuta `funcion` en el hilo que creó la ventana y espera a que termine.

    WinForms solo admite cambios en una ventana desde ese hilo, y pywebview llama a los
    manejadores de `shown` y a la API desde hilos propios. Fuera del depurador WinForms no
    lo comprueba, así que el fallo no se ve hasta que algo falla de verdad.
    """
    if not forma.InvokeRequired:
        funcion()
        return
    from System import Action  # pythonnet, ya cargado por pywebview

    forma.Invoke(Action(funcion))


def tenir_barra_de_titulo(forma, tema: str, compilacion: int | None = None) -> bool:
    """Colorea la barra nativa sin quitarle el marco; si Windows no puede, queda como estaba.

    Hay que llamarla desde el hilo de la interfaz (`en_el_hilo_de_la_interfaz`).
    """
    if compilacion is None:
        compilacion = sys.getwindowsversion().build
    try:
        color_barra, color_texto = COLORES_DE_BARRA[tema]
        manejador = int(forma.Handle.ToInt64())
        acierto = _atributo(manejador, DWMWA_MODO_OSCURO, 1)
        if compilacion >= COMPILACION_CON_COLORES:
            acierto = (
                _atributo(manejador, DWMWA_COLOR_BARRA, _colorref(color_barra))
                and _atributo(manejador, DWMWA_COLOR_TEXTO, _colorref(color_texto))
                and _atributo(manejador, DWMWA_COLOR_BORDE, _colorref(color_barra))
            )
    except Exception:  # noqa: BLE001 - una barra sin teñir no es fatal
        registro.exception("no se pudo teñir la barra de título")
        return False
    if not acierto:
        registro.warning(
            "Windows rechazó el color de la barra de título (compilación %s)", compilacion
        )
    return acierto


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
# El portapapeles lo puede tener abierto otro programa un instante.
INTENTOS_DE_PORTAPAPELES = 3
ESPERA_DE_PORTAPAPELES = 0.05


def _abrir_portapapeles(user32) -> bool:
    for intento in range(INTENTOS_DE_PORTAPAPELES):
        if user32.OpenClipboard(None):
            return True
        if intento < INTENTOS_DE_PORTAPAPELES - 1:
            time.sleep(ESPERA_DE_PORTAPAPELES)
    return False


def copiar_al_portapapeles(texto: str) -> bool:
    """Escribe `texto` en el portapapeles de Windows; solo escribe, nunca lee.

    False si no pudo (portapapeles ocupado tras tres intentos, o error de Windows): el
    registro no lleva el texto.
    """
    datos = (texto + "\0").encode("utf-16-le")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    if not _abrir_portapapeles(user32):
        return False
    try:
        user32.EmptyClipboard()
        memoria = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(datos))
        if not memoria:
            return False
        destino = kernel32.GlobalLock(memoria)
        if not destino:
            kernel32.GlobalFree(memoria)
            return False
        ctypes.memmove(destino, datos, len(datos))
        kernel32.GlobalUnlock(memoria)
        if not user32.SetClipboardData(CF_UNICODETEXT, memoria):
            kernel32.GlobalFree(memoria)
            return False
        return True  # desde aquí la memoria es de Windows
    finally:
        user32.CloseClipboard()


MB_ICONERROR = 0x10
MB_ICONINFORMATION = 0x40


def mostrar_error(titulo: str, mensaje: str, icono: int = MB_ICONERROR) -> None:
    """Empaquetado con PyInstaller no hay consola donde ver una traza."""
    try:
        ctypes.windll.user32.MessageBoxW(None, mensaje, titulo, icono)
    except (AttributeError, OSError):
        registro.exception("no se pudo mostrar el aviso nativo: %s", mensaje)


ERROR_ALREADY_EXISTS = 183
# Windows libera el mutex al morir el proceso; la referencia solo evita cerrarlo antes.
_instancia: list[int] = []


def hay_otra_instancia(nombre: str) -> bool:
    """Toma un mutex con nombre; True si otro proceso ya lo tenía.

    Si Windows no deja crearlo, se dice que no hay otra: mejor arrancar dos veces que no
    arrancar ninguna.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    manejador = kernel32.CreateMutexW(None, False, nombre)
    if not manejador:
        registro.warning(
            "no se pudo crear el mutex de instancia (error %s)", ctypes.get_last_error()
        )
        return False
    otra = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    _instancia.append(manejador)
    return otra


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
