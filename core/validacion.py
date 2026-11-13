"""Comprobaciones de datos ajenos (EDDN y Spansh), antes de que lleguen a la base.

Ambas fuentes son públicas y no están autenticadas: un valor dudoso descarta el
elemento entero con `Descartado`, nunca se corrige en silencio.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime

LARGO_MAXIMO = 100
VALOR_MAXIMO = 2**53
COORDENADA_MAXIMA = 200_000.0

MOTIVO_MAL_FORMADO = "mal_formado"

_MARCA = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)")


class Descartado(Exception):  # noqa: N818 - no es un error: es el desenlace normal de un dato ajeno
    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


def fecha(valor: object) -> datetime | None:
    if not isinstance(valor, str) or not _MARCA.fullmatch(valor):
        return None
    try:
        resultado = datetime.fromisoformat(valor)
    except ValueError:
        return None
    return resultado.astimezone(UTC) if resultado.tzinfo else None


def texto(valor: object) -> str:
    if not isinstance(valor, str):
        raise Descartado(MOTIVO_MAL_FORMADO)
    limpio = valor.strip()
    if not limpio or len(limpio) > LARGO_MAXIMO or not limpio.isprintable():
        raise Descartado(MOTIVO_MAL_FORMADO)
    return limpio


def entero(valor: object, minimo: int = 0, maximo: int = VALOR_MAXIMO) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int) or not minimo <= valor <= maximo:
        raise Descartado(MOTIVO_MAL_FORMADO)
    return valor


def _coordenada(eje: object) -> float:
    numero_valido = isinstance(eje, (int, float)) and not isinstance(eje, bool)
    if not numero_valido or not math.isfinite(eje) or abs(eje) > COORDENADA_MAXIMA:
        raise Descartado(MOTIVO_MAL_FORMADO)
    return float(eje)


def posicion(valor: object) -> tuple[float, float, float]:
    if not isinstance(valor, list) or len(valor) != 3:
        raise Descartado(MOTIVO_MAL_FORMADO)
    x, y, z = (_coordenada(eje) for eje in valor)
    return x, y, z


def distancia_ls(valor: object) -> float | None:
    numero_valido = isinstance(valor, (int, float)) and not isinstance(valor, bool)
    return float(valor) if numero_valido and 0 <= valor <= 1e9 else None
