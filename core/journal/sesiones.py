"""Bloques de actividad (sección 7.5): el material de las sesiones de Rendimiento.

Un bloque empieza al cargar la partida y se corta al cerrar el juego y en cada pausa
sin eventos de `PAUSA_MINIMA` o más. Guarda la pausa que lo separa del anterior de
la misma partida: Rendimiento une los bloques según el umbral que elija el usuario,
sin releer el journal (`docs/decisiones.md`, «Fase 7»).

`Actividad` es inmutable, como `Estado`: `anotar` devuelve una nueva.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from core.journal.comercio import Operacion, segundos
from core.state.estado import Estado

# El umbral más bajo que se puede elegir en Configuración: ningún ajuste necesita
# un corte más fino.
PAUSA_MINIMA = 3600.0


@dataclass(frozen=True, slots=True)
class Bloque:
    """`inicio` identifica el bloque al releer el journal; `partida`, su partida."""

    fid: str
    inicio: str
    fin: str
    partida: str
    # Segundos sin actividad desde el bloque anterior de la misma partida; None si la abre.
    pausa_previa: float | None
    saldo_inicio: int | None
    saldo_fin: int | None
    ganancia: int = 0
    toneladas: int = 0
    saltos: int = 0
    cerrado: bool = False


@dataclass(frozen=True, slots=True)
class Actividad:
    bloque: Bloque | None = None
    ultima: float | None = None
    # Tras un journal nuevo o un cierre, lo que llega antes de `LoadGame` es el menú.
    en_menu: bool = False


def anotar(
    actividad: Actividad, estado: Estado, evento: dict, hecha: Operacion | None
) -> tuple[Actividad, Bloque | None]:
    """La actividad tras el evento y el bloque que cierra, si cierra uno.

    `estado` es el de después de aplicar el evento; `hecha`, su compra o venta.
    """
    marca = evento.get("timestamp")
    t = segundos(marca)
    if t is None or estado.legacy:
        return actividad, None
    nombre = evento.get("event")
    pausa = t - actividad.ultima if actividad.ultima is not None else None
    actividad = replace(actividad, ultima=t)
    if nombre == "Shutdown":
        bloque = _sumar(actividad.bloque, estado, evento, hecha, marca)
        return _cerrar(replace(actividad, en_menu=True), bloque)
    if nombre == "Fileheader" and evento.get("part", 1) == 1:
        # Un journal nuevo sin `Shutdown` antes es un juego que se cerró de golpe:
        # el bloque acaba en su último evento.
        return _cerrar(replace(actividad, en_menu=True), actividad.bloque)
    bloque = actividad.bloque
    if nombre == "LoadGame" or (bloque is None and not actividad.en_menu):
        actividad, cerrado = _cerrar(replace(actividad, en_menu=False), bloque)
        nuevo = _nuevo(estado, marca, marca, None)
        return replace(actividad, bloque=_sumar(nuevo, estado, evento, hecha, marca)), cerrado
    if bloque is None:
        return actividad, None
    if pausa is not None and pausa >= PAUSA_MINIMA:
        actividad, cerrado = _cerrar(actividad, bloque)
        siguiente = _nuevo(estado, marca, bloque.partida, pausa)
        return replace(actividad, bloque=_sumar(siguiente, estado, evento, hecha, marca)), cerrado
    return replace(actividad, bloque=_sumar(bloque, estado, evento, hecha, marca)), None


def _cerrar(actividad: Actividad, bloque: Bloque | None) -> tuple[Actividad, Bloque | None]:
    cerrado = replace(bloque, cerrado=True) if bloque is not None else None
    return replace(actividad, bloque=None), cerrado


def _nuevo(estado: Estado, marca: str, partida: str, pausa: float | None) -> Bloque | None:
    if not estado.fid:
        return None
    return Bloque(
        fid=estado.fid,
        inicio=marca,
        fin=marca,
        partida=partida,
        pausa_previa=pausa,
        saldo_inicio=estado.creditos,
        saldo_fin=estado.creditos,
    )


def _sumar(
    bloque: Bloque | None, estado: Estado, evento: dict, hecha: Operacion | None, marca: str
) -> Bloque | None:
    if bloque is None:
        return None
    bloque = replace(bloque, fin=marca, saldo_fin=estado.creditos)
    if evento.get("event") == "FSDJump":
        bloque = replace(bloque, saltos=bloque.saltos + 1)
    if hecha is not None and hecha.venta:
        bloque = replace(
            bloque,
            ganancia=bloque.ganancia + (hecha.ganancia or 0),
            toneladas=bloque.toneladas + hecha.cantidad,
        )
    return bloque
