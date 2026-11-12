"""Lectura incremental del journal, siempre en solo lectura.

El juego escribe una línea JSON por evento y deja el archivo abierto, así que
una lectura puede toparse con una línea a medias: solo se consume hasta el
último salto de línea y el resto se vuelve a leer en la siguiente pasada.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

registro = logging.getLogger("luna.journal")

PATRON = "Journal.*.log"
SEGUNDOS_POR_DIA = 86_400


def listar(carpeta: Path) -> list[Path]:
    """Journals por orden de nombre, que es el cronológico."""
    return sorted(carpeta.glob(PATRON))


def _eventos_de(contenido: bytes, archivo: str) -> Iterator[dict]:
    ilegibles = 0
    for linea in contenido.decode("utf-8", errors="replace").splitlines():
        if not linea.strip():
            continue
        try:
            evento = json.loads(linea)
        except json.JSONDecodeError:
            ilegibles += 1
            continue
        if isinstance(evento, dict) and isinstance(evento.get("event"), str):
            yield evento
    if ilegibles:
        # Solo el recuento: el contenido del journal no va al registro (10.3).
        registro.warning("%s: %d lineas ilegibles", archivo, ilegibles)


def _leer_desde(archivo: Path, posicion: int) -> tuple[list[dict], int]:
    """Eventos completos desde `posicion` y la posición siguiente a ellos."""
    with archivo.open("rb") as f:
        f.seek(posicion)
        crudo = f.read()
    fin = crudo.rfind(b"\n") + 1
    return list(_eventos_de(crudo[:fin], archivo.name)), posicion + fin


def leer_archivo(archivo: Path) -> list[dict]:
    """Todos los eventos de un journal, para quien lo recorre entero (tools/)."""
    return _leer_desde(archivo, 0)[0]


@dataclass
class Lectura:
    eventos: list[dict]
    archivo: str | None


class Seguidor:
    """Recorre los journals y luego solo lo que se añade al más reciente."""

    def __init__(self, carpeta: Path) -> None:
        self._carpeta = carpeta
        self._actual: Path | None = None
        self._posicion = 0

    def iniciar(self, dias: int, ahora: float | None = None) -> Lectura:
        """Reconstruye desde los journals de los últimos `dias` días.

        El más reciente se lee siempre: si el usuario lleva tiempo sin jugar,
        sin él no habría comandante ni nave que mostrar.
        """
        journals = listar(self._carpeta)
        if not journals:
            return Lectura([], None)

        limite = (ahora if ahora is not None else time.time()) - dias * SEGUNDOS_POR_DIA
        elegidos = [j for j in journals[:-1] if self._modificado(j) >= limite]
        elegidos.append(journals[-1])

        eventos: list[dict] = []
        for archivo in elegidos:
            nuevos, posicion = _leer_desde(archivo, 0)
            eventos.extend(nuevos)
        self._actual, self._posicion = elegidos[-1], posicion
        return Lectura(eventos, self._actual.name)

    def nuevos(self) -> Lectura:
        """Eventos añadidos desde la última llamada, incluido un journal nuevo."""
        journals = listar(self._carpeta)
        if not journals:
            return Lectura([], self._actual.name if self._actual else None)

        eventos: list[dict] = []
        if self._actual is None:
            self._actual = journals[0]
            self._posicion = 0
        eventos.extend(self._leer_actual())

        # El juego abre un journal nuevo al arrancar o cada cierto tamaño;
        # lo que quedara sin leer en el anterior ya se ha consumido arriba.
        for siguiente in (j for j in journals if j.name > self._actual.name):
            self._actual, self._posicion = siguiente, 0
            eventos.extend(self._leer_actual())
        return Lectura(eventos, self._actual.name)

    def _leer_actual(self) -> list[dict]:
        try:
            eventos, self._posicion = _leer_desde(self._actual, self._posicion)
        except OSError:
            registro.warning("no se pudo leer %s", self._actual.name)
            return []
        return eventos

    @staticmethod
    def _modificado(archivo: Path) -> float:
        try:
            return archivo.stat().st_mtime
        except OSError:
            return 0.0
