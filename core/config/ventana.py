"""Tamaño, posición y estado de la ventana entre sesiones (requisito 3 de la 9.1).

Una posición guardada deja de ser válida si el usuario desconecta un monitor, y
un tamaño guardado puede no caber en la pantalla actual. Aquí se valida y se
corrige; colocar la ventana es cosa de `core/plataforma.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from core.config import archivo

CLAVE = "ventana"
ANCHO_MINIMO = 960
ALTO_MINIMO = 600
TAMANO_MINIMO = (ANCHO_MINIMO, ALTO_MINIMO)

# Barra de título que debe quedar visible para poder arrastrar la ventana.
ANCHO_AGARRE = 80
ALTO_AGARRE = 16


@dataclass(frozen=True)
class Geometria:
    ancho: int
    alto: int
    x: int | None = None
    y: int | None = None
    maximizada: bool = False


POR_DEFECTO = Geometria(ancho=1280, alto=800)


class Pantalla(Protocol):
    x: int
    y: int
    width: int
    height: int


def _entero(valor: object) -> int | None:
    # bool es subclase de int y no es una coordenada válida.
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def desde_dict(datos: object) -> Geometria:
    """Convierte lo leído de config.json; los valores inválidos se descartan."""
    if not isinstance(datos, dict):
        return POR_DEFECTO

    ancho = _entero(datos.get("ancho")) or POR_DEFECTO.ancho
    alto = _entero(datos.get("alto")) or POR_DEFECTO.alto
    x = _entero(datos.get("x"))
    y = _entero(datos.get("y"))
    if x is None or y is None:
        x = y = None

    return Geometria(
        ancho=max(ancho, ANCHO_MINIMO),
        alto=max(alto, ALTO_MINIMO),
        x=x,
        y=y,
        maximizada=datos.get("maximizada") is True,
    )


def a_dict(geometria: Geometria) -> dict:
    datos = {
        "ancho": geometria.ancho,
        "alto": geometria.alto,
        "maximizada": geometria.maximizada,
    }
    if geometria.x is not None and geometria.y is not None:
        datos["x"] = geometria.x
        datos["y"] = geometria.y
    return datos


def _esta_a_la_vista(geometria: Geometria, pantallas: list[Pantalla]) -> bool:
    if geometria.x is None or geometria.y is None:
        return False

    izquierda, arriba = geometria.x, geometria.y
    derecha = izquierda + geometria.ancho
    abajo = arriba + ALTO_AGARRE

    for pantalla in pantallas:
        solape_ancho = min(derecha, pantalla.x + pantalla.width) - max(izquierda, pantalla.x)
        solape_alto = min(abajo, pantalla.y + pantalla.height) - max(arriba, pantalla.y)
        if solape_ancho >= ANCHO_AGARRE and solape_alto >= ALTO_AGARRE:
            return True
    return False


def _pantalla_de(geometria: Geometria, pantallas: list[Pantalla]) -> Pantalla | None:
    """Pantalla donde está la esquina de la ventana, o la primera si no encaja."""
    if geometria.x is None or geometria.y is None:
        return pantallas[0] if pantallas else None
    for pantalla in pantallas:
        dentro_x = pantalla.x <= geometria.x < pantalla.x + pantalla.width
        dentro_y = pantalla.y <= geometria.y < pantalla.y + pantalla.height
        if dentro_x and dentro_y:
            return pantalla
    return pantallas[0] if pantallas else None


def _recortar(geometria: Geometria, pantallas: list[Pantalla]) -> Geometria:
    """Un config.json editado a mano puede pedir una ventana mayor que la pantalla.

    Se recorta contra **una** pantalla, no contra el máximo de cada eje: con un
    monitor horizontal y otro vertical, el máximo por eje da un cuadrado que no
    cabe en ninguno de los dos.
    """
    pantalla = _pantalla_de(geometria, pantallas)
    if pantalla is None:
        return geometria
    return replace(
        geometria,
        ancho=max(min(geometria.ancho, pantalla.width), ANCHO_MINIMO),
        alto=max(min(geometria.alto, pantalla.height), ALTO_MINIMO),
    )


def cargar(config: Path, pantallas: list[Pantalla]) -> Geometria:
    geometria = _recortar(desde_dict(archivo.leer_o_vacio(config).get(CLAVE)), pantallas)
    if _esta_a_la_vista(geometria, pantallas):
        return geometria
    # Sin x ni y, la ventana se queda donde la ponga pywebview, que centra.
    return replace(geometria, x=None, y=None)


def guardar(config: Path, geometria: Geometria) -> None:
    archivo.fusionar(config, CLAVE, a_dict(geometria))
