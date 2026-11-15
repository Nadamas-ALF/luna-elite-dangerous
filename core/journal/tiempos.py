"""Muestras de tiempo (sección 8.1) sacadas de los eventos del journal.

Los tramos encadenan el viaje sin huecos, para que su suma sea el tiempo real
(`docs/decisiones.md`, «Fase 6»):

- salida: `Undocked` → primer `FSDJump` (despegar, salir de la estación y saltar).
- salto: un `FSDJump` → el siguiente (cargar, alinear, repostar y saltar).
- supercrucero: `FSDJump` → `SupercruiseExit` seguido de `Docked`, con la distancia
  en ls de la estación. Sin salto previo no se sabe cuánto se recorrió.
- atraque orbital o aproximación planetaria: `SupercruiseExit` → `Docked`.
- comercio: `Docked` → `Undocked` en la misma estación.

`Cronometro` es inmutable, como `Estado`: `medir` devuelve uno nuevo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime

from core import estacion as clasificacion

SALIDA = "salida"
SALTO = "salto"
SUPERCRUCERO = "supercrucero"
ATRAQUE_ORBITAL = "atraque_orbital"
APROXIMACION_PLANETARIA = "aproximacion_planetaria"
COMERCIO = "comercio"
TRAMOS = (SALIDA, SALTO, SUPERCRUCERO, ATRAQUE_ORBITAL, APROXIMACION_PLANETARIA, COMERCIO)

# Tras estos eventos lo que estaba a medias no se puede medir: el juego se cerró,
# la nave se perdió o se movió sin volar (8.4).
INTERRUPCIONES = frozenset(
    {"Fileheader", "LoadGame", "Shutdown", "Died", "Resurrect", "CarrierJump"}
)


@dataclass(frozen=True, slots=True)
class Muestra:
    """`fin` es la marca del evento que la cierra: identifica la muestra al releer el journal."""

    tramo: str
    segundos: float
    fin: str
    distancia_ls: float | None = None


@dataclass(frozen=True, slots=True)
class Cronometro:
    desatraque: float | None = None
    ultimo_salto: float | None = None
    # Momento del `SupercruiseExit` y segundos de supercrucero desde el salto, si lo hubo.
    llegada: tuple[float, float | None] | None = None
    # Momento del `Docked` y su `MarketID`.
    atraque: tuple[float, object] | None = None


def _momento(evento: dict) -> float | None:
    marca = evento.get("timestamp")
    if not isinstance(marca, str):
        return None
    try:
        return datetime.fromisoformat(marca).timestamp()
    except ValueError:
        return None


def _muestra(tramo: str, desde: float | None, hasta: float, fin: str) -> list[Muestra]:
    if desde is None or hasta <= desde:
        return []
    return [Muestra(tramo, hasta - desde, fin)]


def _distancia(evento: dict) -> float | None:
    valor = evento.get("DistFromStarLS")
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    if not math.isfinite(valor) or valor < 0:
        return None
    return float(valor)


def _al_saltar(crono: Cronometro, t: float, fin: str) -> tuple[Cronometro, list[Muestra]]:
    muestras = _muestra(SALIDA, crono.desatraque, t, fin)
    muestras += _muestra(SALTO, crono.ultimo_salto, t, fin)
    return Cronometro(ultimo_salto=t), muestras


def _al_salir_de_supercrucero(crono: Cronometro, t: float) -> Cronometro:
    supercrucero = t - crono.ultimo_salto if crono.ultimo_salto is not None else None
    return Cronometro(llegada=(t, supercrucero))


def _al_atracar(
    crono: Cronometro, evento: dict, t: float, fin: str
) -> tuple[Cronometro, list[Muestra]]:
    muestras: list[Muestra] = []
    if crono.llegada is not None:
        salida_de_supercrucero, supercrucero = crono.llegada
        planetaria = clasificacion.es_planetaria(evento.get("StationType"))
        tramo = APROXIMACION_PLANETARIA if planetaria else ATRAQUE_ORBITAL
        muestras += _muestra(tramo, salida_de_supercrucero, t, fin)
        distancia = _distancia(evento)
        if supercrucero is not None and supercrucero > 0 and distancia is not None:
            muestras.append(Muestra(SUPERCRUCERO, supercrucero, fin, distancia))
    return Cronometro(atraque=(t, evento.get("MarketID"))), muestras


def _al_desatracar(
    crono: Cronometro, evento: dict, t: float, fin: str
) -> tuple[Cronometro, list[Muestra]]:
    muestras: list[Muestra] = []
    if crono.atraque is not None and crono.atraque[1] == evento.get("MarketID"):
        muestras = _muestra(COMERCIO, crono.atraque[0], t, fin)
    return Cronometro(desatraque=t), muestras


def medir(crono: Cronometro, evento: dict) -> tuple[Cronometro, tuple[Muestra, ...]]:
    """El cronómetro tras el evento y las muestras que cierra."""
    nombre = evento.get("event")
    # En un taxi de Apex o en la nave de otro, lo medido no es de tu nave.
    if nombre in INTERRUPCIONES or evento.get("Taxi") is True or evento.get("Multicrew") is True:
        return Cronometro(), ()
    if nombre not in ("FSDJump", "SupercruiseExit", "SupercruiseEntry", "Docked", "Undocked"):
        return crono, ()
    t = _momento(evento)
    if t is None:
        return Cronometro(), ()
    fin = evento["timestamp"]
    muestras: list[Muestra] = []
    if nombre == "FSDJump":
        crono, muestras = _al_saltar(crono, t, fin)
    elif nombre == "SupercruiseExit":
        crono = _al_salir_de_supercrucero(crono, t)
    elif nombre == "SupercruiseEntry":
        # Despegar y entrar en supercrucero antes de saltar sigue siendo la salida;
        # volver a entrar tras una parada anula la llegada a medias.
        crono = replace(crono, llegada=None)
    elif nombre == "Docked":
        crono, muestras = _al_atracar(crono, evento, t, fin)
    else:
        crono, muestras = _al_desatracar(crono, evento, t, fin)
    return crono, tuple(muestras)
