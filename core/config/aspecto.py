"""Ajustes de lectura de la interfaz (prefase 8, bloque 2): tamaño de letra, densidad,
filas por página y qué columnas enseña cada tabla de Rutas.

Viven en la sección `interfaz` de `config.json`, junto a «siempre encima». Cada campo se guarda
por separado con `fusionar_campo` para que dos guardados a la vez no se pisen. Lo que se lee
y no es válido vuelve al valor de fábrica: un `config.json` editado a mano no rompe la interfaz.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from core.config import archivo
from core.config.ajustes import CLAVE_INTERFAZ

registro = logging.getLogger("luna.config")

TAMANOS_DE_LETRA = ("pequeno", "normal", "grande", "muy_grande")
TAMANO_POR_DEFECTO = "normal"
DENSIDADES = ("comoda", "compacta")
DENSIDAD_POR_DEFECTO = "comoda"
FILAS_POR_PAGINA = (5, 10, 25)
FILAS_POR_DEFECTO = 10
TEMAS = ("sobrio", "lunar")
TEMA_POR_DEFECTO = "sobrio"
VIDRIOS = ("desenfocado", "liso")
VIDRIO_POR_DEFECTO = "desenfocado"

# Los nombres coinciden con las columnas de `ui/js/rutas.js`; `test_aspecto.py` lo comprueba.
# El orden de cada lista es el orden en que salen en la tabla.
COLUMNAS_DISPONIBLES = {
    "un_salto": (
        "mercancia", "comprar", "vender", "ganancia_hora", "antiguedad", "precio_compra",
        "precio_venta", "ganancia_tonelada", "toneladas", "ganancia_viaje", "saltos",
        "distancia_ly", "distancia_ls", "tiempo", "ganancia_sesion", "origen",
    ),
    "bucle": (
        "ida", "vuelta", "estacion_a", "estacion_b", "ganancia_hora", "antiguedad",
        "ganancia_viaje", "distancia_ly", "tiempo", "ganancia_sesion", "origen",
    ),
    "cadena": (
        "ruta", "mercancias", "paradas", "ganancia_hora", "antiguedad", "ganancia_viaje",
        "tiempo", "saltos", "distancia_ly", "ganancia_sesion", "origen",
    ),
    "circuito": (
        "ruta", "mercancias", "paradas", "ganancia_hora", "antiguedad", "ganancia_viaje",
        "tiempo", "saltos", "distancia_ly", "ganancia_sesion", "origen",
    ),
}  # fmt: skip
COLUMNAS_POR_DEFECTO = {
    "un_salto": (
        "mercancia", "comprar", "vender", "ganancia_hora", "antiguedad", "toneladas",
        "ganancia_viaje", "tiempo",
    ),
    "bucle": (
        "ida", "vuelta", "estacion_a", "estacion_b", "ganancia_hora", "antiguedad",
        "ganancia_viaje", "tiempo",
    ),
    "cadena": ("ruta", "mercancias", "ganancia_hora", "antiguedad", "ganancia_viaje", "tiempo"),
    "circuito": ("ruta", "mercancias", "ganancia_hora", "antiguedad", "ganancia_viaje", "tiempo"),
}  # fmt: skip


@dataclass(frozen=True)
class Aspecto:
    tamano_letra: str
    densidad: str
    filas_por_pagina: int
    columnas: dict[str, tuple[str, ...]]
    tema: str
    vidrio: str


def es_tema(valor: object) -> bool:
    return isinstance(valor, str) and valor in TEMAS


def es_vidrio(valor: object) -> bool:
    return isinstance(valor, str) and valor in VIDRIOS


def es_tamano_de_letra(valor: object) -> bool:
    return isinstance(valor, str) and valor in TAMANOS_DE_LETRA


def es_densidad(valor: object) -> bool:
    return isinstance(valor, str) and valor in DENSIDADES


def es_filas_por_pagina(valor: object) -> bool:
    return type(valor) is int and valor in FILAS_POR_PAGINA


def columnas_validas(modo: object, columnas: object) -> tuple[str, ...] | None:
    """Las columnas en el orden de la tabla, o `None` si algo de lo pedido no vale."""
    if not isinstance(modo, str) or modo not in COLUMNAS_DISPONIBLES:
        return None
    if not isinstance(columnas, list | tuple) or not columnas:
        return None
    if not all(isinstance(nombre, str) for nombre in columnas):
        return None
    disponibles = COLUMNAS_DISPONIBLES[modo]
    if not set(columnas) <= set(disponibles):
        return None
    return tuple(nombre for nombre in disponibles if nombre in columnas)


def _columnas(seccion: dict, modo: str) -> tuple[str, ...]:
    elegidas = columnas_validas(modo, seccion.get(f"columnas_{modo}"))
    return elegidas or COLUMNAS_POR_DEFECTO[modo]


def leer(config: Path) -> Aspecto:
    seccion = archivo.leer_o_vacio(config).get(CLAVE_INTERFAZ)
    seccion = seccion if isinstance(seccion, dict) else {}
    tamano, densidad = seccion.get("tamano_letra"), seccion.get("densidad")
    filas = seccion.get("filas_por_pagina")
    tema, vidrio = seccion.get("tema"), seccion.get("vidrio")
    return Aspecto(
        tema=tema if es_tema(tema) else TEMA_POR_DEFECTO,
        vidrio=vidrio if es_vidrio(vidrio) else VIDRIO_POR_DEFECTO,
        tamano_letra=tamano if es_tamano_de_letra(tamano) else TAMANO_POR_DEFECTO,
        densidad=densidad if es_densidad(densidad) else DENSIDAD_POR_DEFECTO,
        filas_por_pagina=filas if es_filas_por_pagina(filas) else FILAS_POR_DEFECTO,
        columnas={modo: _columnas(seccion, modo) for modo in COLUMNAS_DISPONIBLES},
    )


def _guardar(config: Path, campo: str, valor: object) -> bool:
    try:
        return archivo.fusionar_campo(config, CLAVE_INTERFAZ, campo, valor)
    except OSError:
        registro.exception("no se pudo escribir %s", config)
        return False


def guardar_tamano_de_letra(config: Path, tamano: str) -> bool:
    return _guardar(config, "tamano_letra", tamano)


def guardar_densidad(config: Path, densidad: str) -> bool:
    return _guardar(config, "densidad", densidad)


def guardar_tema(config: Path, tema: str) -> bool:
    return _guardar(config, "tema", tema)


def guardar_vidrio(config: Path, vidrio: str) -> bool:
    return _guardar(config, "vidrio", vidrio)


def guardar_filas_por_pagina(config: Path, filas: int) -> bool:
    return _guardar(config, "filas_por_pagina", filas)


def guardar_columnas(config: Path, modo: str, columnas: tuple[str, ...]) -> bool:
    return _guardar(config, f"columnas_{modo}", list(columnas))
