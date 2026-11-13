"""Datos estáticos de naves y mercancías: nombres y plataforma (sección 4.4).

Las tablas salen de `tools/generar_tabla_*.py`. Una nave que no esté en ella no
es un error: el llamador decide qué mostrar cuando devuelve None.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from core import recursos


@dataclass(frozen=True)
class FichaCatalogo:
    nombre: str
    plataforma: str


@lru_cache(maxsize=1)
def _naves() -> dict:
    return json.loads(recursos.ruta("data", "naves.json").read_text(encoding="utf-8"))["naves"]


@lru_cache(maxsize=1)
def mercancias() -> dict[str, tuple[str | None, str | None]]:
    """Símbolo de EDDN -> (nombre inglés, nombre español); cualquiera puede faltar."""
    tabla = json.loads(recursos.ruta("data", "mercancias.json").read_text(encoding="utf-8"))
    return {k: (v["en"], v["es"]) for k, v in tabla["mercancias"].items()}


def nave(simbolo: str) -> FichaCatalogo | None:
    ficha = _naves().get(simbolo.lower())
    return FichaCatalogo(ficha["nombre"], ficha["plataforma"]) if ficha else None
