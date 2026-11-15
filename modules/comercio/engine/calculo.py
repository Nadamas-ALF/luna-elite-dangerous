"""Los pasos de la sección 7.2 como funciones puras: sin base de datos ni journal."""

from __future__ import annotations

import math
from dataclasses import dataclass

SEGUNDOS_POR_HORA = 3600.0


@dataclass(frozen=True)
class Curva:
    """Confianza según la antigüedad del dato más viejo (7.2, paso 7)."""

    horas_plena: float = 1.0
    horas_minima: float = 24.0
    minimo: float = 0.5

    def __post_init__(self) -> None:
        if not 0 <= self.horas_plena < self.horas_minima:
            raise ValueError("la confianza tiene que empezar a bajar antes de llegar al minimo")
        if not 0 < self.minimo <= 1:
            raise ValueError("el minimo de confianza va de 0 a 1")


def toneladas(capacidad: int, stock: int, demanda: int, creditos: int | None, precio: int) -> int:
    """Paso 2. `creditos` None es «sin límite» (el perfil no lo conoce o el usuario lo quitó)."""
    limite = min(capacidad, stock, demanda)
    if creditos is not None and precio > 0:
        limite = min(limite, creditos // precio)
    return max(limite, 0)


def saltos(distancia_ly: float, rango_ly: float) -> int:
    """Paso 4: en línea recta; en el mismo sistema no hay salto."""
    if distancia_ly <= 0:
        return 0
    return math.ceil(distancia_ly / rango_ly)


def por_hora(ganancia: float, segundos: float) -> float:
    return ganancia * SEGUNDOS_POR_HORA / segundos


def confianza(horas: float, curva: Curva) -> float:
    if horas <= curva.horas_plena:
        return 1.0
    if horas >= curva.horas_minima:
        return curva.minimo
    avance = (horas - curva.horas_plena) / (curva.horas_minima - curva.horas_plena)
    return 1.0 - avance * (1.0 - curva.minimo)
