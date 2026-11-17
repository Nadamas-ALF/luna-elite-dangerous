"""Modos Un salto y Bucle A↔B (sección 7.3).

Un salto empareja, por mercancía, los K vendedores más baratos con los K
compradores que más pagan por una bodega. Probar todos los pares de una esfera
de 50 ly serían millones; los mejores tratos salen casi siempre de esos
extremos, y la distancia decide entre ellos.

El bucle parte de los mejores tramos de ida y busca la vuelta entre todo lo que
B vende y A compra, no solo entre los K de cada mercancía: la vuelta rara vez es
el mejor trato de su mercancía.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterator
from dataclasses import dataclass

from modules.comercio.engine import calculo
from modules.comercio.engine.calculo import Curva
from modules.comercio.engine.candidatos import Candidatos, Precio
from modules.comercio.engine.perfil import Perfil
from modules.comercio.engine.tramo import Tramo, evaluar, mejores
from modules.comercio.timing import Tiempos

K_POR_MERCANCIA = 25
TRAMOS_PARA_BUCLE = 3_000


def _mas_baratos(ofertas: list[Precio]) -> list[Precio]:
    return heapq.nsmallest(K_POR_MERCANCIA, ofertas, key=lambda p: p.precio)


def _mejores_compradores(demandas: list[Precio], capacidad: int) -> list[Precio]:
    """Por lo que pagan por una bodega: un precio alto con demanda de 3 t no sirve."""
    return heapq.nlargest(
        K_POR_MERCANCIA, demandas, key=lambda p: p.precio * min(p.cantidad, capacidad)
    )


def _pares(
    candidatos: Candidatos, perfil: Perfil, curva: Curva, tiempos: Tiempos
) -> Iterator[Tramo]:
    for mercancia, ofertas in candidatos.ofertas.items():
        demandas = candidatos.demandas.get(mercancia)
        if not demandas:
            continue
        compradores = _mejores_compradores(demandas, perfil.capacidad)
        for compra in _mas_baratos(ofertas):
            for venta in compradores:
                tramo = evaluar(compra, venta, perfil, curva, tiempos)
                if tramo is not None:
                    yield tramo


def pares(
    candidatos: Candidatos, perfil: Perfil, curva: Curva, tiempos: Tiempos
) -> Iterator[Tramo]:
    """Los tramos que Un salto compara, sin quedarse con los mejores (recuentos de descarte)."""
    return _pares(candidatos, perfil, curva, tiempos)


def un_salto(candidatos: Candidatos, perfil: Perfil, curva: Curva, tiempos: Tiempos) -> list[Tramo]:
    return mejores(_pares(candidatos, perfil, curva, tiempos), perfil.orden)


@dataclass(frozen=True, slots=True)
class Bucle:
    ida: Tramo
    vuelta: Tramo

    @property
    def segundos(self) -> float:
        return self.ida.segundos + self.vuelta.segundos

    @property
    def ganancia_viaje(self) -> int:
        return self.ida.ganancia_viaje + self.vuelta.ganancia_viaje

    @property
    def ganancia_tonelada(self) -> int:
        return self.ida.ganancia_tonelada + self.vuelta.ganancia_tonelada

    @property
    def ganancia_hora(self) -> float:
        return calculo.por_hora(self.ganancia_viaje, self.segundos)

    @property
    def confianza(self) -> float:
        return min(self.ida.confianza, self.vuelta.confianza)

    @property
    def puntuacion(self) -> float:
        return self.ganancia_hora * self.confianza

    @property
    def distancia_ly(self) -> float:
        return self.ida.distancia_ly


def mejor_entre(
    candidatos: Candidatos,
    origen: int,
    destino: int,
    perfil: Perfil,
    curva: Curva,
    tiempos: Tiempos,
) -> Tramo | None:
    """El mejor trato de `origen` a `destino` con cualquier mercancía.

    El tiempo depende solo de las dos estaciones, así que gana la mayor ganancia
    por viaje corregida por la confianza, es decir, la puntuación.
    """
    ofertas = candidatos.ofertas_de.get(origen, {})
    demandas = candidatos.demandas_de.get(destino, {})
    tramos = (
        evaluar(oferta, demandas[mercancia], perfil, curva, tiempos)
        for mercancia, oferta in ofertas.items()
        if mercancia in demandas
    )
    return max((t for t in tramos if t is not None), key=lambda t: t.puntuacion, default=None)


def _pares_de_estaciones(
    candidatos: Candidatos, perfil: Perfil, curva: Curva, tiempos: Tiempos
) -> list[tuple[int, int]]:
    """Las parejas de los mejores tramos de ida, sin repetir la misma en sentido contrario."""
    tramos = heapq.nlargest(
        TRAMOS_PARA_BUCLE, _pares(candidatos, perfil, curva, tiempos), key=lambda t: t.puntuacion
    )
    vistas: set[frozenset[int]] = set()
    parejas = []
    for tramo in tramos:
        a, b = tramo.compra.estacion.market_id, tramo.venta.estacion.market_id
        if frozenset((a, b)) not in vistas:
            vistas.add(frozenset((a, b)))
            parejas.append((a, b))
    return parejas


def _bucles(
    candidatos: Candidatos, perfil: Perfil, curva: Curva, tiempos: Tiempos
) -> Iterator[Bucle]:
    for a, b in _pares_de_estaciones(candidatos, perfil, curva, tiempos):
        ida = mejor_entre(candidatos, a, b, perfil, curva, tiempos)
        vuelta = mejor_entre(candidatos, b, a, perfil, curva, tiempos)
        if ida is not None and vuelta is not None:
            yield Bucle(ida, vuelta)


def bucle(candidatos: Candidatos, perfil: Perfil, curva: Curva, tiempos: Tiempos) -> list[Bucle]:
    return mejores(_bucles(candidatos, perfil, curva, tiempos), perfil.orden)


def tramos_con(
    candidatos: Candidatos, market_id: int, perfil: Perfil, curva: Curva, tiempos: Tiempos
) -> list[Tramo]:
    """Todos los tramos de un salto que compran o venden en `market_id` (alertas, 7.4).

    Sin el recorte de los K mejores por mercancía: un trato que pasa los umbrales del
    usuario cuenta aunque haya otros mejores.
    """
    tramos = []
    for mercancia, oferta in candidatos.ofertas_de.get(market_id, {}).items():
        for venta in candidatos.demandas.get(mercancia, ()):
            tramos.append(evaluar(oferta, venta, perfil, curva, tiempos))
    for mercancia, demanda in candidatos.demandas_de.get(market_id, {}).items():
        for compra in candidatos.ofertas.get(mercancia, ()):
            tramos.append(evaluar(compra, demanda, perfil, curva, tiempos))
    return [t for t in tramos if t is not None]


def bucles_con(
    candidatos: Candidatos, market_id: int, perfil: Perfil, curva: Curva, tiempos: Tiempos
) -> list[Bucle]:
    """Los bucles A↔B con `market_id` en una punta, uno por cada otra estación."""
    otras = (set(candidatos.ofertas_de) | set(candidatos.demandas_de)) - {market_id}
    bucles = []
    for otra in otras:
        ida = mejor_entre(candidatos, market_id, otra, perfil, curva, tiempos)
        vuelta = mejor_entre(candidatos, otra, market_id, perfil, curva, tiempos) if ida else None
        if ida is not None and vuelta is not None:
            bucles.append(Bucle(ida, vuelta))
    return bucles
