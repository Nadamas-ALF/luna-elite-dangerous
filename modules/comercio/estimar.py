"""Recalcular una ruta de estaciones con los precios de hoy (prefase 8, bloque 5).

Lo comparten Fijadas, «Estimar una ruta», la ruta en curso y el aviso de ruta mejor. En cada
tramo se toma la mejor mercancía de hoy (`rutas.mejor_entre`); si no es la que se fijó, el
tramo lo dice. El perfil es el de tu nave, sin los filtros de búsqueda: la ruta ya está
elegida y un filtro que la vacíe no informa.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from modules.comercio import paradas as modelo_paradas
from modules.comercio import salida, timing
from modules.comercio.engine import calculo, candidatos, rutas
from modules.comercio.engine.calculo import Curva
from modules.comercio.engine.candidatos import Candidatos, Posicion
from modules.comercio.engine.perfil import (
    ORIGENES,
    PLATAFORMAS,
    TIPOS,
    Perfil,
    desde_dict,
)
from modules.comercio.engine.tramo import Tramo

ESTADO_OK = "ok"
ESTADO_INCOMPLETA = "incompleta"
TRAMO_SIN_PRECIOS = "sin_precios"
TRAMO_SIN_TRATO = "sin_trato"


def perfil_de_la_nave(
    datos: dict, tope_dias: int, sistema: str | None, saldo: int | None
) -> Perfil:
    """El perfil de la nave sin filtros; `PerfilInvalido` si no se conoce la nave (7.1)."""
    sin_filtros = {
        **datos,
        "origen": sistema or "-",
        "antiguedad_max_h": tope_dias * 24.0,
        "stock_minimo": 1,
        "ganancia_min": 0,
        "tipos": list(TIPOS),
        "origenes": list(ORIGENES),
        "raras": True,
    }
    return desde_dict(sin_filtros, tope_dias, saldo=saldo)


def posiciones_de(ruta: dict) -> list[tuple[int, int]]:
    """Los tramos de la ruta como parejas de posiciones de parada (i, j)."""
    n = len(ruta["paradas"])
    return [(i, (i + 1) % n) for i in range(n if ruta["cerrada"] else n - 1)]


@dataclass(frozen=True, slots=True)
class Contexto:
    """Lo leído una sola vez para estimar varias rutas: estaciones, precios y tiempos."""

    cargados: Candidatos
    plataformas: dict[int, str | None]
    perfil: Perfil
    curva: Curva
    tiempos: timing.Tiempos
    nombres: dict[str, str]


def leer_contexto(
    conexion: sqlite3.Connection,
    market_ids: set[int],
    ahora: datetime,
    desde: Posicion | None,
    perfil: Perfil,
    curva: Curva,
    tiempos: timing.Tiempos,
) -> Contexto:
    cargados, plataformas = candidatos.de_estaciones(conexion, market_ids, ahora, desde)
    nombres = salida.nombres_de_mercancias(conexion)
    return Contexto(cargados, plataformas, perfil, curva, tiempos, nombres)


def estimar(contexto: Contexto, ruta: dict) -> dict:
    """`ruta` es `{"cerrada", "paradas": [{market_id, estacion, sistema, mercancia}]}`."""
    entradas = [_tramo(contexto, ruta["paradas"], i, j) for i, j in posiciones_de(ruta)]
    completa = all(estado == ESTADO_OK for _, estado in entradas)
    tramos = [tramo for tramo, _ in entradas if tramo is not None]
    resumen = _resumen(tramos) if completa else None
    return {
        "estado": ESTADO_OK if completa else ESTADO_INCOMPLETA,
        "tramos": [
            _informe(i, j, estado, ruta["paradas"][i]["mercancia"], tramo, contexto.nombres)
            for (i, j), (tramo, estado) in zip(posiciones_de(ruta), entradas, strict=True)
        ],
        "paradas": [_parada(p, contexto) for p in ruta["paradas"]],
        "detalle": _detalle(tramos, ruta["cerrada"], resumen, contexto) if resumen else None,
        "resumen": resumen,
    }


def _tramo(contexto: Contexto, paradas: list[dict], i: int, j: int) -> tuple[Tramo | None, str]:
    cargados = contexto.cargados
    origen, destino = paradas[i]["market_id"], paradas[j]["market_id"]
    if not _tiene_precios(cargados, origen) or not _tiene_precios(cargados, destino):
        return None, TRAMO_SIN_PRECIOS
    tramo = rutas.mejor_entre(
        cargados, origen, destino, contexto.perfil, contexto.curva, contexto.tiempos
    )
    return (tramo, ESTADO_OK) if tramo is not None else (None, TRAMO_SIN_TRATO)


def _tiene_precios(cargados: Candidatos, market_id: int) -> bool:
    if market_id not in cargados.estaciones:
        return False
    return market_id in cargados.ofertas_de or market_id in cargados.demandas_de


def _informe(
    i: int, j: int, estado: str, fijada: str | None, tramo: Tramo | None, nombres: dict
) -> dict:
    hoy = tramo.compra.mercancia if tramo is not None else None
    return {
        "desde": i,
        "hasta": j,
        "estado": estado,
        "mercancia": salida.mercancia(hoy, nombres) if hoy else None,
        "mercancia_fijada": salida.mercancia(fijada, nombres) if fijada else None,
        "cambiada": bool(fijada and hoy and fijada != hoy),
    }


def _parada(parada: dict, contexto: Contexto) -> dict:
    """El nombre de la base si la estación sigue en ella; si no, el guardado."""
    market_id = parada["market_id"]
    en_la_base = contexto.cargados.estaciones.get(market_id)
    plataforma = contexto.plataformas.get(market_id)
    return {
        "market_id": market_id,
        "estacion": en_la_base.nombre if en_la_base else parada["estacion"],
        "sistema": en_la_base.sistema if en_la_base else parada["sistema"],
        "plataforma": plataforma,
        "no_cabe": _no_cabe(plataforma, contexto.perfil.plataforma),
    }


def _no_cabe(de_la_estacion: str | None, de_la_nave: str) -> bool:
    if de_la_estacion not in PLATAFORMAS:
        return False
    return PLATAFORMAS.index(de_la_estacion) < PLATAFORMAS.index(de_la_nave)


def _detalle(tramos: list[Tramo], cerrada: bool, resumen: dict, contexto: Contexto) -> dict:
    perfil = contexto.perfil
    datos = [
        salida.tramo(t, contexto.nombres, perfil.horas_sesion, contexto.tiempos) for t in tramos
    ]
    totales = {
        "ganancia_hora": resumen["ganancia_hora"],
        "ganancia_viaje": resumen["ganancia_viaje"],
        "ganancia_sesion": resumen["ganancia_hora"] * perfil.horas_sesion,
        "segundos": resumen["segundos"],
        "distancia_ly": resumen["distancia_ly"],
        "confianza": resumen["confianza"],
    }
    return modelo_paradas.de_tramos(datos, cerrada, totales)


def _resumen(tramos: list[Tramo]) -> dict:
    """Sumas de ganancia, tiempo y distancia; la confianza es la del dato más viejo."""
    ganancia = sum(t.ganancia_viaje for t in tramos)
    segundos = sum(t.segundos for t in tramos)
    return {
        "ganancia_hora": calculo.por_hora(ganancia, segundos),
        "ganancia_viaje": ganancia,
        "segundos": segundos,
        "distancia_ly": sum(t.distancia_ly for t in tramos),
        "confianza": min(t.confianza for t in tramos),
        "horas_max": max(max(t.compra.horas, t.venta.horas) for t in tramos),
    }
