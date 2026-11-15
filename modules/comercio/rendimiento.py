"""Rendimiento (sección 7.5): lo ganado de verdad y cuánto se acercó la estimación.

Lee lo que el núcleo guarda del journal: `sessions` (bloques de actividad),
`trade_legs` (tramos de despegue a despegue con su ganancia real) y `trades`.

- Una sesión son los bloques seguidos de una partida separados por pausas más
  cortas que el umbral del usuario, o la partida entera si elige «por partida».
- El tiempo estimado de un tramo se recalcula con el modelo de tiempos de la nave
  del tramo (`docs/decisiones.md`, «Fase 7»). La comparación usa solo los tramos
  que tienen estimación, en los dos lados.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime

from modules.comercio import salida, timing
from modules.comercio.engine import calculo

SEGUNDOS_POR_HORA = 3600.0


@dataclass(frozen=True, slots=True)
class Bloque:
    inicio: str
    fin: str
    partida: str
    pausa_previa: float | None
    saldo_inicio: int | None
    saldo_fin: int | None
    ganancia: int
    toneladas: int
    saltos: int
    cerrado: bool


@dataclass(frozen=True, slots=True)
class Sesion:
    inicio: str
    fin: str
    saldo_inicio: int | None
    saldo_fin: int | None
    ganancia: int
    toneladas: int
    saltos: int
    # Segundos con el juego en marcha: las pausas que quedan dentro de la sesión cuentan.
    segundos: float
    abierta: bool
    bloques: int = 1


@dataclass(frozen=True, slots=True)
class Comparacion:
    """Real contra estimado sobre los mismos tramos: los que tienen estimación."""

    tramos: int = 0
    ganancia: int = 0
    segundos_reales: float = 0.0
    segundos_estimados: float = 0.0

    def sumar(self, ganancia: int, real: float, estimado: float) -> Comparacion:
        return Comparacion(
            self.tramos + 1,
            self.ganancia + ganancia,
            self.segundos_reales + real,
            self.segundos_estimados + estimado,
        )


@dataclass(frozen=True, slots=True)
class Ruta:
    origen: tuple[str, str]
    destino: tuple[str, str]
    viajes: int = 0
    ganancia: int = 0
    segundos: float = 0.0
    mercancias: tuple[str, ...] = ()
    comparacion: Comparacion = field(default_factory=Comparacion)


@dataclass(frozen=True, slots=True)
class Mercancia:
    simbolo: str
    ventas: int
    toneladas: int
    # Solo de las ventas en que el juego sabe lo que pagaste.
    ganancia: int
    sin_precio_de_compra: int


def por_hora(ganancia: float, segundos: float) -> float | None:
    return calculo.por_hora(ganancia, segundos) if segundos > 0 else None


def leer_bloques(conexion: sqlite3.Connection, fid: str) -> list[Bloque]:
    filas = conexion.execute(
        "SELECT inicio, fin, partida, pausa_previa, saldo_inicio, saldo_fin, ganancia, "
        "toneladas, saltos, cerrado FROM sessions WHERE fid = ? ORDER BY inicio",
        (fid,),
    )
    return [Bloque(*fila[:9], bool(fila[9])) for fila in filas]


def unir(bloques: list[Bloque], pausa_horas: int, por_partida: bool) -> list[Sesion]:
    """Las sesiones en orden; `bloques` en orden de inicio."""
    sesiones: list[Sesion] = []
    anterior: Bloque | None = None
    for bloque in bloques:
        if anterior is not None and _sigue(anterior, bloque, pausa_horas, por_partida):
            sesiones[-1] = _alargar(sesiones[-1], bloque)
        else:
            sesiones.append(_sesion(bloque))
        anterior = bloque
    return sesiones


def _sigue(anterior: Bloque, bloque: Bloque, pausa_horas: int, por_partida: bool) -> bool:
    if bloque.partida != anterior.partida or bloque.pausa_previa is None:
        return False
    return por_partida or bloque.pausa_previa < pausa_horas * SEGUNDOS_POR_HORA


def _sesion(bloque: Bloque) -> Sesion:
    return Sesion(
        inicio=bloque.inicio,
        fin=bloque.fin,
        saldo_inicio=bloque.saldo_inicio,
        saldo_fin=bloque.saldo_fin,
        ganancia=bloque.ganancia,
        toneladas=bloque.toneladas,
        saltos=bloque.saltos,
        segundos=_entre(bloque.inicio, bloque.fin),
        abierta=not bloque.cerrado,
    )


def _alargar(sesion: Sesion, bloque: Bloque) -> Sesion:
    return replace(
        sesion,
        fin=bloque.fin,
        saldo_fin=bloque.saldo_fin,
        ganancia=sesion.ganancia + bloque.ganancia,
        toneladas=sesion.toneladas + bloque.toneladas,
        saltos=sesion.saltos + bloque.saltos,
        segundos=_entre(sesion.inicio, bloque.fin),
        abierta=not bloque.cerrado,
        bloques=sesion.bloques + 1,
    )


def estimar(
    distancia_ly: float | None,
    rango: float | None,
    distancia_ls: float,
    planetaria: bool,
    tiempos: timing.Tiempos,
) -> float | None:
    """Segundos que LUNA estimaría para el tramo (7.2, paso 5); None sin posición o rango."""
    if distancia_ly is None or not rango:
        return None
    return tiempos.tramo(calculo.saltos(distancia_ly, rango), distancia_ls, planetaria)


def rutas(
    conexion: sqlite3.Connection,
    fid: str,
    periodo: tuple[str, str] | None,
    tiempos_de: Callable[[int | None], timing.Tiempos],
) -> list[Ruta]:
    """Los tramos del periodo por estación de origen y de destino, de más a menos ganancia."""
    sql = (
        "SELECT ship_id, segundos, origen_estacion, origen_sistema, destino_estacion, "
        "destino_sistema, distancia_ly, rango, distancia_ls, planetaria, ganancia, mercancia "
        "FROM trade_legs WHERE fid = ?"
    )
    parametros: tuple = (fid,)
    if periodo is not None:
        sql += " AND salida >= ? AND salida <= ?"
        parametros += periodo
    agrupadas: dict[tuple, Ruta] = {}
    for fila in conexion.execute(sql + " ORDER BY salida", parametros):
        ship_id, segundos, *lugares, distancia_ly, rango, ls, planetaria, ganancia, mercancia = fila
        origen, destino = tuple(lugares[:2]), tuple(lugares[2:])
        ruta = agrupadas.get((origen, destino)) or Ruta(origen, destino)
        estimado = estimar(distancia_ly, rango, ls, bool(planetaria), tiempos_de(ship_id))
        agrupadas[(origen, destino)] = _sumar(ruta, segundos, ganancia, mercancia, estimado)
    return sorted(agrupadas.values(), key=lambda r: r.ganancia, reverse=True)


def _sumar(
    ruta: Ruta, segundos: float, ganancia: int, mercancia: str | None, estimado: float | None
) -> Ruta:
    mercancias = ruta.mercancias
    if mercancia and mercancia not in mercancias:
        mercancias = (*mercancias, mercancia)
    comparacion = ruta.comparacion
    if estimado is not None:
        comparacion = comparacion.sumar(ganancia, segundos, estimado)
    return replace(
        ruta,
        viajes=ruta.viajes + 1,
        ganancia=ruta.ganancia + ganancia,
        segundos=ruta.segundos + segundos,
        mercancias=mercancias,
        comparacion=comparacion,
    )


def mercancias(
    conexion: sqlite3.Connection, fid: str, periodo: tuple[str, str] | None
) -> list[Mercancia]:
    """Lo vendido en el periodo por mercancía, de más a menos ganancia."""
    sql = (
        "SELECT commodity, COUNT(*), SUM(cantidad), "
        "SUM(CASE WHEN precio_medio_compra > 0 "
        "THEN cantidad * (precio - precio_medio_compra) ELSE 0 END), "
        "SUM(CASE WHEN precio_medio_compra > 0 THEN 0 ELSE 1 END) "
        "FROM trades WHERE fid = ? AND venta = 1"
    )
    parametros: tuple = (fid,)
    if periodo is not None:
        sql += " AND marca >= ? AND marca <= ?"
        parametros += periodo
    filas = conexion.execute(sql + " GROUP BY commodity", parametros).fetchall()
    return sorted((Mercancia(*fila) for fila in filas), key=lambda m: m.ganancia, reverse=True)


def _entre(inicio: str, fin: str) -> float:
    return datetime.fromisoformat(fin).timestamp() - datetime.fromisoformat(inicio).timestamp()


TODO = "todo"
# Sin un evento en este tiempo, el siguiente abriría otro bloque: la sesión ya no sigue.
EN_CURSO_SEGUNDOS = 3600.0
LIMITE_DE_SESIONES = 200


class SesionDesconocida(LookupError):
    """La interfaz pidió una sesión que no está (otro umbral, otro comandante)."""


def informe(
    conexion: sqlite3.Connection,
    fid: str,
    sesion: str | None,
    ajuste: tuple[int, bool],
    ahora: datetime,
) -> dict:
    """Lo que enseña la pantalla: las sesiones y, de la elegida, rutas y mercancías.

    `sesion` es el inicio de una sesión, `TODO` para todo el historial o None para la última.
    """
    sesiones = unir(leer_bloques(conexion, fid), *ajuste)
    elegida = _elegir(sesiones, sesion)
    periodo = None if elegida is None else (elegida.inicio, elegida.fin)
    tiempos: dict[int | None, timing.Tiempos] = {}

    def tiempos_de(ship_id: int | None) -> timing.Tiempos:
        if ship_id not in tiempos:
            tiempos[ship_id] = timing.cargar(conexion, fid, ship_id)
        return tiempos[ship_id]

    nombres = salida.nombres_de_mercancias(conexion)
    agrupadas = rutas(conexion, fid, periodo, tiempos_de) if sesiones else []
    vendidas = mercancias(conexion, fid, periodo) if sesiones else []
    incluidas = sesiones if elegida is None else [elegida]
    return {
        "ajuste": {"pausa_horas": ajuste[0], "por_partida": ajuste[1]},
        "sesiones": [_sesion_a_dict(s, ahora) for s in reversed(sesiones[-LIMITE_DE_SESIONES:])],
        "seleccion": None if not sesiones else (elegida.inicio if elegida else TODO),
        "resumen": _resumen(incluidas, agrupadas) if sesiones else None,
        "rutas": [_ruta_a_dict(r, nombres) for r in agrupadas],
        "mercancias": [_mercancia_a_dict(m, nombres) for m in vendidas],
    }


def _elegir(sesiones: list[Sesion], sesion: str | None) -> Sesion | None:
    if sesion == TODO or not sesiones:
        return None
    if sesion is None:
        return sesiones[-1]
    for candidata in sesiones:
        if candidata.inicio == sesion:
            return candidata
    raise SesionDesconocida(sesion)


def _sesion_a_dict(sesion: Sesion, ahora: datetime) -> dict:
    parada = ahora.timestamp() - datetime.fromisoformat(sesion.fin).timestamp()
    return {
        "inicio": sesion.inicio,
        "fin": sesion.fin,
        "segundos": sesion.segundos,
        "ganancia": sesion.ganancia,
        "por_hora": por_hora(sesion.ganancia, sesion.segundos),
        "toneladas": sesion.toneladas,
        "saltos": sesion.saltos,
        "saldo_inicio": sesion.saldo_inicio,
        "saldo_fin": sesion.saldo_fin,
        "bloques": sesion.bloques,
        "en_curso": sesion.abierta and parada < EN_CURSO_SEGUNDOS,
    }


def _resumen(sesiones: list[Sesion], agrupadas: list[Ruta]) -> dict:
    ganancia = sum(s.ganancia for s in sesiones)
    segundos = sum(s.segundos for s in sesiones)
    comparacion = Comparacion()
    for ruta in agrupadas:
        c = ruta.comparacion
        comparacion = Comparacion(
            comparacion.tramos + c.tramos,
            comparacion.ganancia + c.ganancia,
            comparacion.segundos_reales + c.segundos_reales,
            comparacion.segundos_estimados + c.segundos_estimados,
        )
    return {
        "sesiones": len(sesiones),
        "ganancia": ganancia,
        "segundos": segundos,
        "por_hora": por_hora(ganancia, segundos),
        "toneladas": sum(s.toneladas for s in sesiones),
        "saltos": sum(s.saltos for s in sesiones),
        "comparacion": _comparacion_a_dict(comparacion),
    }


def _comparacion_a_dict(comparacion: Comparacion) -> dict | None:
    """None sin tramos comparables: no se afirma una desviación sin muestra (DESIGN 4.4)."""
    if not comparacion.tramos:
        return None
    real = por_hora(comparacion.ganancia, comparacion.segundos_reales)
    estimada = por_hora(comparacion.ganancia, comparacion.segundos_estimados)
    return {
        "tramos": comparacion.tramos,
        "por_hora_real": real,
        "por_hora_estimada": estimada,
        "desviacion": (estimada - real) / real if real and estimada is not None else None,
    }


def _ruta_a_dict(ruta: Ruta, nombres: dict[str, str]) -> dict:
    return {
        "origen": {"estacion": ruta.origen[0], "sistema": ruta.origen[1]},
        "destino": {"estacion": ruta.destino[0], "sistema": ruta.destino[1]},
        "mercancias": [salida.mercancia(m, nombres) for m in ruta.mercancias],
        "viajes": ruta.viajes,
        "ganancia": ruta.ganancia,
        "segundos": ruta.segundos,
        "por_hora": por_hora(ruta.ganancia, ruta.segundos),
        "comparacion": _comparacion_a_dict(ruta.comparacion),
    }


def _mercancia_a_dict(vendida: Mercancia, nombres: dict[str, str]) -> dict:
    return {
        "mercancia": salida.mercancia(vendida.simbolo, nombres),
        "ventas": vendida.ventas,
        "toneladas": vendida.toneladas,
        "ganancia": vendida.ganancia,
        "sin_precio_de_compra": vendida.sin_precio_de_compra,
    }
