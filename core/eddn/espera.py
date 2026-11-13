"""Mercados en espera de las coordenadas de su sistema (sección 4.2).

Un mercado de EDDN cuyo sistema no se conoce espera a que llegue su posición por
`journal/1`. Con tope de tamaño y de tiempo: es memoria de un canal público.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable

from core.eddn.mensaje import MercadoDeRed

CAPACIDAD = 500
# Un jugador atraca poco después de llegar al sistema, que es cuando EDMC envía su posición.
VIDA = 600.0


class Espera:
    def __init__(
        self,
        capacidad: int = CAPACIDAD,
        vida: float = VIDA,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._capacidad = capacidad
        self._vida = vida
        self._reloj = reloj
        # market_id -> (instante, mercado), del más antiguo al más nuevo
        self._pendientes: OrderedDict[int, tuple[float, MercadoDeRed]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._pendientes)

    def guardar(self, mercado: MercadoDeRed) -> None:
        """Por estación solo queda el mercado más reciente."""
        self._caducar()
        anterior = self._pendientes.get(mercado.estacion.market_id)
        if anterior is not None and anterior[1].observado >= mercado.observado:
            return
        self._pendientes[mercado.estacion.market_id] = (self._reloj(), mercado)
        self._pendientes.move_to_end(mercado.estacion.market_id)
        while len(self._pendientes) > self._capacidad:
            self._pendientes.popitem(last=False)

    def liberar(self, sistema: str) -> list[MercadoDeRed]:
        """Saca los mercados que esperaban a este sistema."""
        self._caducar()
        listos = [m for _, m in self._pendientes.values() if m.sistema == sistema]
        for mercado in listos:
            del self._pendientes[mercado.estacion.market_id]
        return listos

    def _caducar(self) -> None:
        limite = self._reloj() - self._vida
        while self._pendientes:
            primero = next(iter(self._pendientes.values()))
            if primero[0] > limite:
                return
            self._pendientes.popitem(last=False)
