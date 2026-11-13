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


class EsferaViva:
    """La esfera vigente, compartida por quien la consulta (EDDN, núcleo, retención).

    Cambiar el centro o el radio no obliga a reiniciar: quien la consulta lee
    siempre la actual. Asignar una referencia es atómico, así que no hace falta
    candado.
    """

    def __init__(self, esfera: Esfera, fiable: bool = True) -> None:
        self._actual = esfera
        self._version = 0
        # False si se leyó de un config.json ilegible: es el valor por defecto, no el del usuario.
        self.fiable = fiable

    @property
    def actual(self) -> Esfera:
        return self._actual

    @property
    def version(self) -> int:
        """Sube con cada cambio: quien guarda algo calculado con la esfera sabe cuándo olvidarlo."""
        return self._version

    def cambiar(self, esfera: Esfera) -> None:
        self._actual = esfera
        self.fiable = True
        self._version += 1

    def distancia(self, posicion: Posicion) -> float:
        return self._actual.distancia(posicion)

    def contiene(self, posicion: Posicion) -> bool:
        return self._actual.contiene(posicion)
