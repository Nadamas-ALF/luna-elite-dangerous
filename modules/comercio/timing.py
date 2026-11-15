"""Modelo de tiempos (sección 8): por ahora, solo los valores por defecto de la 8.2.

Las muestras propias y la jerarquía nave → comandante → por defecto llegan con
la fase 6. El supercrucero se ajustó con `tools/ajustar_supercrucero.py` sobre
journals reales (docs/decisiones.md, «Fase 5»).
"""

from __future__ import annotations

import math

SALTO = 50.0
ATRAQUE_ORBITAL = 90.0
APROXIMACION_PLANETARIA = 180.0
COMERCIO = 60.0

SUPERCRUCERO_A = 110.0
SUPERCRUCERO_B = 32.0
SUPERCRUCERO_C = 100.0


def supercrucero(distancia_ls: float) -> float:
    return SUPERCRUCERO_A + SUPERCRUCERO_B * math.log1p(distancia_ls / SUPERCRUCERO_C)


def atraque(planetaria: bool) -> float:
    return APROXIMACION_PLANETARIA if planetaria else ATRAQUE_ORBITAL


FUENTE_POR_DEFECTO = "por_defecto"


def desglose(saltos: int, distancia_ls: float, planetaria: bool) -> dict[str, float]:
    """Segundos de cada parte de un tramo, para enseñar de dónde sale el tiempo (9.2)."""
    return {
        "saltos": saltos * SALTO,
        "supercrucero": supercrucero(distancia_ls),
        "atraque": atraque(planetaria),
        "comercio": COMERCIO,
    }


def tramo(saltos: int, distancia_ls: float, planetaria: bool) -> float:
    """Segundos de un tramo (7.2, paso 5): saltar, llegar a la estación, atracar y comerciar."""
    return sum(desglose(saltos, distancia_ls, planetaria).values())
