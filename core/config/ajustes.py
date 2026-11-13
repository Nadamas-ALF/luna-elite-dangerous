"""Ajustes del usuario que lee el núcleo, con valores por defecto validados.

config.json lo puede editar el usuario a mano, así que cada valor se comprueba:
uno con el tipo equivocado cae al valor por defecto en lugar de romper el
arranque.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from core.config import archivo
from core.esfera import Esfera

registro = logging.getLogger("luna.ajustes")

CLAVE_JOURNAL = "journal"

DIAS_POR_DEFECTO = 7
DIAS_MINIMOS = 1
DIAS_MAXIMOS = 90

# Sol; elegir otro centro por nombre llega con la descarga (fase 4).
CENTRO_POR_DEFECTO = (0.0, 0.0, 0.0)
CENTRO_NOMBRE_POR_DEFECTO = "Sol"

CLAVE_ESFERA = "esfera"
RADIO_POR_DEFECTO = 100.0
# La galaxia mide unos 100 000 ly de diámetro: más que esto no es una esfera, es todo.
RADIO_MAXIMO = 100_000.0
COORDENADA_MAXIMA = 200_000.0

CLAVE_EDDN = "eddn"


def _seccion_journal(config: Path) -> dict:
    seccion = archivo.leer_o_vacio(config).get(CLAVE_JOURNAL)
    return seccion if isinstance(seccion, dict) else {}


def carpeta_journal(config: Path) -> str | None:
    """Carpeta elegida a mano, o None para la detección automática."""
    carpeta = _seccion_journal(config).get("carpeta")
    return carpeta if isinstance(carpeta, str) and carpeta else None


def dias_journal(config: Path) -> int:
    dias = _seccion_journal(config).get("dias")
    if isinstance(dias, bool) or not isinstance(dias, int):
        return DIAS_POR_DEFECTO
    return min(max(dias, DIAS_MINIMOS), DIAS_MAXIMOS)


def guardar_carpeta_journal(config: Path, carpeta: str | None) -> bool:
    """None vuelve a la detección automática. False si no se pudo guardar."""
    seccion = dict(_seccion_journal(config))
    if carpeta is None:
        seccion.pop("carpeta", None)
    else:
        seccion["carpeta"] = carpeta
    try:
        return archivo.fusionar(config, CLAVE_JOURNAL, seccion)
    except OSError:
        registro.exception("no se pudo escribir %s", config)
        return False


def _numero(valor: object) -> float | None:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        return None
    return float(valor)


def _centro(seccion: dict) -> tuple[str, tuple[float, float, float]]:
    """Nombre y coordenadas; cualquier dato malo deja el Sol entero, nunca medio centro."""
    bruto = seccion.get("centro")
    if not isinstance(bruto, dict):
        return CENTRO_NOMBRE_POR_DEFECTO, CENTRO_POR_DEFECTO
    coordenadas = tuple(_numero(bruto.get(eje)) for eje in ("x", "y", "z"))
    nombre = bruto.get("nombre")
    if None in coordenadas or not isinstance(nombre, str) or not nombre.strip():
        return CENTRO_NOMBRE_POR_DEFECTO, CENTRO_POR_DEFECTO
    if any(abs(c) > COORDENADA_MAXIMA for c in coordenadas):
        return CENTRO_NOMBRE_POR_DEFECTO, CENTRO_POR_DEFECTO
    return nombre.strip(), coordenadas


def esfera(config: Path) -> Esfera:
    """Centro y radio de interés; el usuario los puede editar en config.json."""
    seccion = archivo.leer_o_vacio(config).get(CLAVE_ESFERA)
    seccion = seccion if isinstance(seccion, dict) else {}
    nombre, centro = _centro(seccion)
    radio = _numero(seccion.get("radio"))
    if radio is None or not 0 < radio <= RADIO_MAXIMO:
        radio = RADIO_POR_DEFECTO
    return Esfera(nombre, centro, radio)


def eddn_activado(config: Path) -> bool:
    seccion = archivo.leer_o_vacio(config).get(CLAVE_EDDN)
    activado = seccion.get("activado") if isinstance(seccion, dict) else None
    return activado if isinstance(activado, bool) else True
