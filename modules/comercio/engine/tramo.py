"""Un trato completo: comprar en A, llevarlo a B y venderlo (sección 7.2, pasos 1 a 8)."""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from modules.comercio.engine import calculo
from modules.comercio.engine.calculo import Curva
from modules.comercio.engine.candidatos import Precio
from modules.comercio.engine.perfil import Perfil
from modules.comercio.timing import Tiempos

RESULTADOS = 50


@dataclass(frozen=True, slots=True)
class Tramo:
    compra: Precio
    venta: Precio
    toneladas: int
    distancia_ly: float
    saltos: int
    segundos: float
    confianza: float

    @property
    def ganancia_tonelada(self) -> int:
        return self.venta.precio - self.compra.precio

    @property
    def ganancia_viaje(self) -> int:
        return self.toneladas * self.ganancia_tonelada

    @property
    def ganancia_hora(self) -> float:
        return calculo.por_hora(self.ganancia_viaje, self.segundos)

    @property
    def puntuacion(self) -> float:
        return self.ganancia_hora * self.confianza


def evaluar(
    compra: Precio, venta: Precio, perfil: Perfil, curva: Curva, tiempos: Tiempos
) -> Tramo | None:
    """None si no deja la ganancia mínima del perfil o no cabe ni una tonelada."""
    if venta.precio <= compra.precio or venta.estacion.market_id == compra.estacion.market_id:
        return None
    if venta.precio - compra.precio < perfil.ganancia_min:
        return None
    toneladas = calculo.toneladas(
        perfil.capacidad, compra.cantidad, venta.cantidad, perfil.creditos, compra.precio
    )
    if toneladas == 0:
        return None
    distancia = math.dist(compra.estacion.posicion, venta.estacion.posicion)
    saltos = calculo.saltos(distancia, perfil.rango)
    destino = venta.estacion
    return Tramo(
        compra=compra,
        venta=venta,
        toneladas=toneladas,
        distancia_ly=distancia,
        saltos=saltos,
        segundos=tiempos.tramo(saltos, destino.distancia_ls, destino.planetaria),
        confianza=calculo.confianza(max(compra.horas, venta.horas), curva),
    )


class Ordenable(Protocol):
    puntuacion: float
    ganancia_viaje: float
    ganancia_tonelada: float
    distancia_ly: float


# «Ganancia por hora» ordena por la puntuación: la 7.2 (paso 8) la define como el criterio.
CLAVES: dict[str, Callable[[Ordenable], tuple]] = {
    "ganancia_hora": lambda r: (-r.puntuacion,),
    "ganancia_viaje": lambda r: (-r.ganancia_viaje, -r.puntuacion),
    "ganancia_tonelada": lambda r: (-r.ganancia_tonelada, -r.puntuacion),
    "distancia": lambda r: (r.distancia_ly, -r.puntuacion),
}


def mejores[T: Ordenable](
    resultados: Iterable[T], orden: str, cuantos: int = RESULTADOS
) -> list[T]:
    return heapq.nsmallest(cuantos, resultados, key=CLAVES[orden])
