"""Modelo de tiempos (sección 8): muestras propias, limpieza y jerarquía de valores.

Cada tramo sale de la nave si tiene al menos 10 muestras limpias, si no del
comandante (todas sus naves) y si no del valor por defecto (8.3). Limpiar es
quitar lo que pase de 3 veces la mediana y quedarse con la mediana del resto (8.4).

El viaje se parte en salida + saltos encadenados + supercrucero + atraque +
comercio, que suman el tiempo real sin huecos (`core/journal/tiempos.py`).

El supercrucero se calibra con un factor sobre la curva por defecto (mediana de
real ÷ curva): con pocas distancias distintas, reajustar `a` y `b` sale inestable.
"""

from __future__ import annotations

import math
import sqlite3
import statistics
from dataclasses import dataclass, replace

from core.journal import tiempos as tramos

# Medidos en los journals del usuario (docs/verificaciones.md, «Fase 6»): la salida
# lleva despegar y el primer salto; un salto, cargar, alinear y repostar.
SALIDA = 100.0
SALTO = 60.0
ATRAQUE_ORBITAL = 90.0
APROXIMACION_PLANETARIA = 180.0
COMERCIO = 60.0

SUPERCRUCERO_A = 110.0
SUPERCRUCERO_B = 32.0
SUPERCRUCERO_C = 100.0

MINIMO_DE_MUESTRAS = 10
LIMITE_SOBRE_LA_MEDIANA = 3

FUENTE_POR_DEFECTO = "por_defecto"
FUENTE_COMANDANTE = "comandante"
FUENTE_NAVE = "nave"
FUENTES = (FUENTE_POR_DEFECTO, FUENTE_COMANDANTE, FUENTE_NAVE)


def supercrucero_por_defecto(distancia_ls: float) -> float:
    return SUPERCRUCERO_A + SUPERCRUCERO_B * math.log1p(distancia_ls / SUPERCRUCERO_C)


@dataclass(frozen=True, slots=True)
class Valor:
    """Segundos de un tramo; en el supercrucero, el factor sobre la curva por defecto."""

    valor: float
    fuente: str = FUENTE_POR_DEFECTO
    muestras: int = 0


@dataclass(frozen=True, slots=True)
class Tiempos:
    salida: Valor = Valor(SALIDA)
    salto: Valor = Valor(SALTO)
    supercrucero: Valor = Valor(1.0)
    atraque_orbital: Valor = Valor(ATRAQUE_ORBITAL)
    aproximacion_planetaria: Valor = Valor(APROXIMACION_PLANETARIA)
    comercio: Valor = Valor(COMERCIO)

    def partes(self, saltos: int, distancia_ls: float, planetaria: bool) -> dict[str, tuple]:
        """(segundos, Valor) de cada parte de un tramo, para enseñar de dónde sale (8.4)."""
        atraque = self.aproximacion_planetaria if planetaria else self.atraque_orbital
        salida = self.salida.valor if saltos > 0 else 0.0
        return {
            "salida": (salida, self.salida),
            "saltos": (max(saltos - 1, 0) * self.salto.valor, self.salto),
            "supercrucero": (self._supercrucero(distancia_ls), self.supercrucero),
            "atraque": (atraque.valor, atraque),
            "comercio": (self.comercio.valor, self.comercio),
        }

    def tramo(self, saltos: int, distancia_ls: float, planetaria: bool) -> float:
        """Segundos de un tramo (7.2, paso 5). Se llama por cada par candidato: sin diccionarios."""
        segundos = self._supercrucero(distancia_ls) + self.comercio.valor
        segundos += self.aproximacion_planetaria.valor if planetaria else self.atraque_orbital.valor
        if saltos > 0:
            segundos += self.salida.valor + (saltos - 1) * self.salto.valor
        return segundos

    def _supercrucero(self, distancia_ls: float) -> float:
        return self.supercrucero.valor * supercrucero_por_defecto(distancia_ls)


POR_DEFECTO = Tiempos()


def limpiar(valores: list[float]) -> list[float]:
    """Sin lo que pase de 3 veces la mediana: interdicciones, menús abiertos, ausencias."""
    if not valores:
        return []
    tope = LIMITE_SOBRE_LA_MEDIANA * statistics.median(valores)
    return [v for v in valores if v <= tope]


def calibrar(de_la_nave: list[float], del_comandante: list[float], por_defecto: Valor) -> Valor:
    for valores, fuente in ((de_la_nave, FUENTE_NAVE), (del_comandante, FUENTE_COMANDANTE)):
        limpios = limpiar(valores)
        if len(limpios) >= MINIMO_DE_MUESTRAS:
            return Valor(statistics.median(limpios), fuente, len(limpios))
    return por_defecto


def _valor_de(tramo: str, segundos: float, distancia_ls: float | None) -> float | None:
    if tramo != tramos.SUPERCRUCERO:
        return segundos
    return None if distancia_ls is None else segundos / supercrucero_por_defecto(distancia_ls)


def cargar(conexion: sqlite3.Connection, fid: str | None, ship_id: int | None) -> Tiempos:
    """Los tiempos de esta nave y este comandante; sin comandante, los de por defecto."""
    if fid is None:
        return POR_DEFECTO
    nave: dict[str, list[float]] = {t: [] for t in tramos.TRAMOS}
    comandante: dict[str, list[float]] = {t: [] for t in tramos.TRAMOS}
    filas = conexion.execute(
        "SELECT ship_id, tramo, segundos, distancia_ls FROM timing_samples WHERE fid = ?", (fid,)
    )
    for nave_de_la_muestra, tramo, segundos, distancia_ls in filas:
        valor = _valor_de(tramo, segundos, distancia_ls)
        if tramo not in comandante or valor is None or valor <= 0:
            continue
        comandante[tramo].append(valor)
        if nave_de_la_muestra == ship_id:
            nave[tramo].append(valor)
    return replace(
        POR_DEFECTO,
        **{
            tramo: calibrar(nave[tramo], comandante[tramo], getattr(POR_DEFECTO, tramo))
            for tramo in tramos.TRAMOS
        },
    )
