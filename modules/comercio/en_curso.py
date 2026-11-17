"""La ruta que haces ahora, deducida de tus últimos tramos de comercio (prefase 8, bloque 5).

El usuario no la marca: sale de `trade_legs`. Si los últimos tramos dan vueltas a un ciclo de
estaciones, la ruta en curso es ese ciclo cerrado; si no, es el último tramo. Son funciones
puras sobre tramos ya leídos, más una lectura de la base.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from modules.comercio import fijadas
from modules.comercio.engine.rutas import Bucle
from modules.comercio.engine.tramo import Tramo
from modules.comercio.paradas import MODO_BUCLE

TRAMOS_LEIDOS = 50


@dataclass(frozen=True, slots=True)
class Leg:
    """Un tramo de despegue a despegue (`trade_legs`), con lo que hace falta para encadenarlo."""

    salida: str
    llegada: str
    origen: int | None
    origen_estacion: str
    origen_sistema: str
    destino: int | None
    destino_estacion: str
    destino_sistema: str
    ganancia: int
    segundos: float
    mercancia: str | None


@dataclass(frozen=True, slots=True)
class RutaEnCurso:
    cerrada: bool
    paradas: tuple[dict, ...]
    clave: str
    viajes: int
    ganancia: int
    segundos: float

    @property
    def por_hora_real(self) -> float:
        return self.ganancia * 3600.0 / self.segundos if self.segundos > 0 else 0.0

    def a_dict(self) -> dict:
        return {
            "cerrada": self.cerrada,
            "paradas": list(self.paradas),
            "clave": self.clave,
            "viajes": self.viajes,
            "ganancia": self.ganancia,
            "segundos": self.segundos,
            "por_hora_real": self.por_hora_real,
        }


def leer(conexion: sqlite3.Connection, fid: str) -> list[Leg]:
    """Los últimos tramos del comandante, del más viejo al más nuevo."""
    filas = conexion.execute(
        "SELECT salida, llegada, origen_market_id, origen_estacion, origen_sistema, "
        "destino_market_id, destino_estacion, destino_sistema, ganancia, segundos, mercancia "
        "FROM trade_legs WHERE fid = ? ORDER BY salida DESC LIMIT ?",
        (fid, TRAMOS_LEIDOS),
    ).fetchall()
    return [Leg(*fila) for fila in reversed(filas)]


def deducir(tramos: list[Leg], ahora: datetime, pausa_horas: float) -> RutaEnCurso | None:
    """None si no hay tramos, el último acabó hace más que la pausa o no sirve de ruta."""
    if not tramos or _caducado(tramos[-1], ahora, pausa_horas):
        return None
    cadena = _cadena(tramos)
    if not cadena or cadena[-1].origen == cadena[-1].destino:
        return None
    estaciones = [cadena[0].origen, *(t.destino for t in cadena)]
    inicio = _inicio_del_ciclo(estaciones)
    if inicio is None:
        return _de_tramos(cadena[-1:], cerrada=False)
    largo = len(estaciones) - 1 - inicio
    return _de_tramos(cadena[-_repetidos(estaciones, largo) :], cerrada=True, largo=largo)


def _caducado(ultimo: Leg, ahora: datetime, pausa_horas: float) -> bool:
    try:
        llegada = datetime.fromisoformat(ultimo.llegada)
    except ValueError:
        return True
    if llegada.tzinfo is None:
        return True
    return ahora - llegada > timedelta(hours=pausa_horas)


def _cadena(tramos: list[Leg]) -> list[Leg]:
    """Los últimos tramos encadenados: el origen de uno es el destino del anterior.

    Un tramo sin estación conocida corta la cadena; si es el último, no hay ruta.
    """
    ultimo = tramos[-1]
    if ultimo.origen is None or ultimo.destino is None:
        return []
    cadena = [ultimo]
    for anterior in reversed(tramos[:-1]):
        primero = cadena[0]
        # Un hueco entre la llegada y la salida siguiente es otra sesión: la cadena se corta.
        if anterior.origen is None or anterior.destino != primero.origen:
            break
        if anterior.llegada != primero.salida:
            break
        cadena.insert(0, anterior)
    return cadena


def _inicio_del_ciclo(estaciones: list[int | None]) -> int | None:
    """Posición donde empieza el ciclo que cierra la última estación; None si no hay."""
    final = len(estaciones) - 1
    anteriores = [i for i in range(final) if estaciones[i] == estaciones[final]]
    if not anteriores:
        return None
    inicio = anteriores[-1]
    ciclo = estaciones[inicio:final]
    return inicio if len(set(ciclo)) == len(ciclo) else None


def _repetidos(estaciones: list[int | None], largo: int) -> int:
    """Cuántos tramos del final siguen dando vueltas al mismo ciclo."""
    final = len(estaciones) - 1
    tramos = 0
    for atras in range(1, final + 1):
        if estaciones[final - atras] != estaciones[final - atras % largo]:
            break
        tramos = atras
    return tramos


def _de_tramos(tramos: list[Leg], cerrada: bool, largo: int = 0) -> RutaEnCurso:
    if cerrada:
        ciclo = tramos[-largo:]
        paradas = [_parada(t, t.mercancia) for t in ciclo]
    else:
        paradas = [_parada(tramos[-1], tramos[-1].mercancia), _destino(tramos[-1])]
    ids = [p["market_id"] for p in paradas]
    return RutaEnCurso(
        cerrada=cerrada,
        paradas=tuple(paradas),
        clave=fijadas.clave(cerrada, ids),
        viajes=len(tramos),
        ganancia=sum(t.ganancia for t in tramos),
        segundos=sum(t.segundos for t in tramos),
    )


def _parada(tramo: Leg, mercancia: str | None) -> dict:
    return {
        "market_id": tramo.origen,
        "estacion": tramo.origen_estacion,
        "sistema": tramo.origen_sistema,
        "mercancia": mercancia,
    }


def _destino(tramo: Leg) -> dict:
    return {
        "market_id": tramo.destino,
        "estacion": tramo.destino_estacion,
        "sistema": tramo.destino_sistema,
        "mercancia": None,
    }


def siguiente(ruta: RutaEnCurso, market_id: int) -> dict | None:
    """La parada que sigue a `market_id` en una ruta cerrada; None si es abierta o no está."""
    if not ruta.cerrada:
        return None
    ids = [p["market_id"] for p in ruta.paradas]
    if market_id not in ids:
        return None
    return ruta.paradas[(ids.index(market_id) + 1) % len(ids)]


def _estaciones_de(modo: str, ruta: Tramo | Bucle) -> tuple[bool, list[int]]:
    if modo == MODO_BUCLE:
        return True, [ruta.ida.compra.estacion.market_id, ruta.ida.venta.estacion.market_id]
    return False, [ruta.compra.estacion.market_id, ruta.venta.estacion.market_id]


def mejor_que(
    candidatas: Iterable[tuple[str, Tramo | Bucle]],
    propia: str,
    referencia: float,
    margen_pct: float,
) -> tuple[str, Tramo | Bucle] | None:
    """La candidata de más Cr/h que supera a `referencia` por más del margen.

    `propia` es la clave de la ruta en curso: la misma ruta no compite consigo misma.
    """
    ajenas = [
        (modo, ruta)
        for modo, ruta in candidatas
        if fijadas.clave(*_estaciones_de(modo, ruta)) != propia
    ]
    if not ajenas:
        return None
    mejor = max(ajenas, key=lambda candidata: candidata[1].ganancia_hora)
    if mejor[1].ganancia_hora > referencia * (1 + margen_pct / 100):
        return mejor
    return None
