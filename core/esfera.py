"""La esfera de interés: un centro y un radio en años luz (secciones 2 y 6.3).

La comparten EDDN y Spansh. Solo hace geometría; de dónde sale el centro y el
radio lo decide `core/config/ajustes.py`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Posicion = tuple[float, float, float]


@dataclass(frozen=True)
class Esfera:
    nombre: str
    centro: Posicion
    radio: float

    def distancia(self, posicion: Posicion) -> float:
        return math.dist(posicion, self.centro)

    def contiene(self, posicion: Posicion) -> bool:
        return self.distancia(posicion) <= self.radio
