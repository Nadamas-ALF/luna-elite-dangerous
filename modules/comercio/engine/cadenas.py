"""Modos Varias paradas y Circuito (sección 7.3, fase 8).

Búsqueda en haz: se parte de los mejores tramos de un salto y, nivel a nivel, cada
camino se alarga con los mejores tramos que salen de su última estación. Probar todas
las secuencias de una esfera con cientos de mercados es imposible; el haz recorta cada
nivel a los `ANCHO` mejores caminos y no garantiza el óptimo.

Cada tramo es el `mejor_entre` de sus dos estaciones, igual que lo recalcula Fijadas.
"""

from __future__ import annotations

import heapq
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from modules.comercio.engine import calculo, rutas
from modules.comercio.engine.calculo import Curva
from modules.comercio.engine.candidatos import BusquedaCancelada, Candidatos, Precio
from modules.comercio.engine.perfil import Perfil
from modules.comercio.engine.tramo import Tramo, evaluar, mejores
from modules.comercio.timing import Tiempos

ANCHO = 800
VECINOS = 30
POR_SALIDA = 30
# Cada cuántos tramos se mira el reloj mientras se arma el haz inicial.
REVISAR_CADA = 1_000


@dataclass(frozen=True, slots=True)
class Cadena:
    tramos: tuple[Tramo, ...]
    cerrada: bool = False

    @property
    def estaciones(self) -> tuple[int, ...]:
        ids = tuple(t.compra.estacion.market_id for t in self.tramos)
        return ids if self.cerrada else (*ids, self.tramos[-1].venta.estacion.market_id)

    @property
    def ganancia_viaje(self) -> int:
        return sum(t.ganancia_viaje for t in self.tramos)

    @property
    def ganancia_tonelada(self) -> int:
        return sum(t.ganancia_tonelada for t in self.tramos)

    @property
    def segundos(self) -> float:
        return sum(t.segundos for t in self.tramos)

    @property
    def distancia_ly(self) -> float:
        return sum(t.distancia_ly for t in self.tramos)

    @property
    def saltos(self) -> int:
        return sum(t.saltos for t in self.tramos)

    @property
    def ganancia_hora(self) -> float:
        return calculo.por_hora(self.ganancia_viaje, self.segundos)

    @property
    def confianza(self) -> float:
        return min(t.confianza for t in self.tramos)

    @property
    def puntuacion(self) -> float:
        return self.ganancia_hora * self.confianza


@dataclass
class Limite:
    """Cuándo se acaba el tiempo y si la pantalla canceló la búsqueda (E-16)."""

    fin: float
    parar: threading.Event = field(default_factory=threading.Event)
    reloj: Callable[[], float] = time.monotonic
    cortado: bool = False

    def comprobar(self) -> None:
        if self.parar.is_set():
            raise BusquedaCancelada

    def agotado(self) -> bool:
        """Una vez que se acaba el tiempo, sigue acabado aunque el reloj retroceda."""
        self.comprobar()
        if not self.cortado and self.reloj() >= self.fin:
            self.cortado = True
        return self.cortado


class Grafo:
    """Los tramos que salen de cada estación, calculados la primera vez que se piden."""

    def __init__(self, candidatos: Candidatos, perfil: Perfil, curva: Curva, tiempos: Tiempos):
        self.candidatos = candidatos
        self.perfil = perfil
        self.curva = curva
        self.tiempos = tiempos
        self._compradores: dict[str, list[Precio]] = {}
        self._vecinos: dict[int, tuple[Tramo, ...]] = {}
        self._entre: dict[tuple[int, int], Tramo | None] = {}

    def entre(self, origen: int, destino: int) -> Tramo | None:
        clave = (origen, destino)
        if clave not in self._entre:
            self._entre[clave] = rutas.mejor_entre(
                self.candidatos, origen, destino, self.perfil, self.curva, self.tiempos
            )
        return self._entre[clave]

    def vecinos(self, origen: int, solo_cache: bool = False) -> tuple[Tramo, ...]:
        if origen not in self._vecinos:
            if solo_cache:
                return ()
            self._vecinos[origen] = self._calcular(origen)
        return self._vecinos[origen]

    def _compradores_de(self, mercancia: str) -> list[Precio]:
        if mercancia not in self._compradores:
            self._compradores[mercancia] = rutas.mejores_compradores(
                self.candidatos.demandas.get(mercancia, []), self.perfil.capacidad
            )
        return self._compradores[mercancia]

    def _calcular(self, origen: int) -> tuple[Tramo, ...]:
        mejor: dict[int, Tramo] = {}
        for mercancia, oferta in self.candidatos.ofertas_de.get(origen, {}).items():
            for venta in self._compradores_de(mercancia):
                tramo = evaluar(oferta, venta, self.perfil, self.curva, self.tiempos)
                if tramo is None:
                    continue
                destino = venta.estacion.market_id
                if destino not in mejor or tramo.puntuacion > mejor[destino].puntuacion:
                    mejor[destino] = tramo
        destinos = heapq.nsmallest(VECINOS, mejor.values(), key=_orden_de_tramo)
        # `mejor_entre` mira todas las mercancías, no solo los extremos: es igual o mejor.
        tramos = (self.entre(origen, t.venta.estacion.market_id) for t in destinos)
        return tuple(sorted((t for t in tramos if t is not None), key=_orden_de_tramo))


def _orden_de_tramo(tramo: Tramo) -> tuple[float, int]:
    return (-tramo.puntuacion, tramo.venta.estacion.market_id)


def _haz_inicial(grafo: Grafo, limite: Limite) -> list[Cadena]:
    mejor_por_pareja: dict[tuple[int, int], Tramo] = {}
    pares = rutas.pares(grafo.candidatos, grafo.perfil, grafo.curva, grafo.tiempos)
    for i, tramo in enumerate(pares):
        if i % REVISAR_CADA == 0 and limite.agotado():
            break
        pareja = (tramo.compra.estacion.market_id, tramo.venta.estacion.market_id)
        if pareja not in mejor_por_pareja or tramo.puntuacion > mejor_por_pareja[pareja].puntuacion:
            mejor_por_pareja[pareja] = tramo
    elegidas = heapq.nsmallest(
        ANCHO, mejor_por_pareja.items(), key=lambda p: (-p[1].puntuacion, p[0])
    )
    tramos = (grafo.entre(*pareja) for pareja, _ in elegidas)
    return _podar(Cadena((t,)) for t in tramos if t is not None)


def _podar(caminos: Iterable[Cadena]) -> list[Cadena]:
    """Los `ANCHO` mejores, con pocos por salida: si no, el haz se llena de variantes."""
    elegidos: list[Cadena] = []
    por_salida: Counter[int] = Counter()
    for camino in sorted(caminos, key=lambda c: (-c.puntuacion, c.estaciones)):
        salida = camino.estaciones[0]
        if por_salida[salida] < POR_SALIDA:
            por_salida[salida] += 1
            elegidos.append(camino)
            if len(elegidos) == ANCHO:
                break
    return elegidos


def _expandir(haz: list[Cadena], grafo: Grafo, limite: Limite, *, completar: bool) -> list[Cadena]:
    """Un nivel más. Sin tiempo: `completar` sigue con lo que ya hay en la caché; si no, para."""
    nuevos = []
    for camino in haz:
        agotado = limite.agotado()
        if agotado and not completar:
            break
        for tramo in grafo.vecinos(camino.estaciones[-1], solo_cache=agotado):
            if tramo.venta.estacion.market_id not in camino.estaciones:
                nuevos.append(Cadena((*camino.tramos, tramo)))
    return nuevos


def cadena(
    candidatos: Candidatos,
    perfil: Perfil,
    curva: Curva,
    tiempos: Tiempos,
    paradas: int,
    limite: Limite,
) -> tuple[list[Cadena], bool]:
    """Rutas abiertas de exactamente `paradas` estaciones. El `bool` dice si se cortó por tiempo."""
    grafo = Grafo(candidatos, perfil, curva, tiempos)
    haz = _haz_inicial(grafo, limite)
    for _ in range(paradas - 2):
        haz = _podar(_expandir(haz, grafo, limite, completar=True))
    return mejores(haz, perfil.orden), limite.cortado


def _clave_de_ciclo(estaciones: tuple[int, ...]) -> tuple[int, ...]:
    """A→B→C, B→C→A y C→A→B son el mismo circuito: se toma la rotación menor."""
    return min(estaciones[i:] + estaciones[:i] for i in range(len(estaciones)))


def circuito(
    candidatos: Candidatos,
    perfil: Perfil,
    curva: Curva,
    tiempos: Tiempos,
    paradas: int,
    limite: Limite,
) -> tuple[list[Cadena], bool]:
    """Circuitos de 3 a `paradas` estaciones que vuelven a la primera."""
    grafo = Grafo(candidatos, perfil, curva, tiempos)
    haz = _haz_inicial(grafo, limite)
    ciclos: dict[tuple[int, ...], Cadena] = {}
    for _ in range(paradas - 2):
        haz = _podar(_expandir(haz, grafo, limite, completar=False))
        for camino in haz:
            if limite.agotado():
                break
            _cerrar(camino, grafo, ciclos)
        if limite.cortado:
            break
    return mejores(ciclos.values(), perfil.orden), limite.cortado


def _cerrar(camino: Cadena, grafo: Grafo, ciclos: dict[tuple[int, ...], Cadena]) -> None:
    """La vuelta es `mejor_entre`, no un vecino: rara vez es el mejor trato de su mercancía."""
    vuelta = grafo.entre(camino.estaciones[-1], camino.estaciones[0])
    if vuelta is None:
        return
    ciclo = Cadena((*camino.tramos, vuelta), cerrada=True)
    clave = _clave_de_ciclo(ciclo.estaciones)
    if clave not in ciclos or ciclo.puntuacion > ciclos[clave].puntuacion:
        ciclos[clave] = ciclo
