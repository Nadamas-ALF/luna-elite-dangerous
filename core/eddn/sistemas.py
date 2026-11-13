"""Caché de coordenadas de sistemas (sección 4.2).

Los mercados de EDDN solo traen el nombre del sistema; para saber si cae dentro
de la esfera hay que conocer sus coordenadas. Se aprenden de los `journal/1` que
pasan por el relay y de lo que ya hay en la base (visitas propias, Spansh).

Se usa solo desde el hilo del suscriptor: la conexión de lectura es suya.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from core.db import escritor, mercado
from core.db.mercado import Sistema
from core.eddn.mensaje import Visita
from core.esfera import Esfera, EsferaViva

registro = logging.getLogger("luna.eddn")

# Sin tope, el relay (miles de sistemas distintos al día) llenaría la memoria.
CAPACIDAD = 20_000


class Conocidos:
    def __init__(self, esfera: Esfera | EsferaViva, base: Path, capacidad: int = CAPACIDAD) -> None:
        self._esfera = esfera
        self._version_de_la_esfera = getattr(esfera, "version", 0)
        self._base = base
        self._capacidad = capacidad
        self._cache: OrderedDict[str, Sistema] = OrderedDict()
        self._lectura: sqlite3.Connection | None = None

    def _sincronizar(self) -> None:
        """Las distancias recordadas son al centro anterior: si la esfera cambió, se olvidan.

        Lo hace el hilo que usa el caché, no quien cambia la esfera: así no hay carreras.
        """
        version = getattr(self._esfera, "version", 0)
        if version != self._version_de_la_esfera:
            self._version_de_la_esfera = version
            self._cache.clear()

    def buscar(self, nombre: str) -> Sistema | None:
        """Con la distancia ya medida desde el centro actual; None si no se conoce."""
        self._sincronizar()
        if (conocido := self._cache.get(nombre)) is not None:
            self._cache.move_to_end(nombre)
            return conocido
        guardado = self._leer_de_la_base(nombre)
        if guardado is None:
            return None
        return self._recordar(guardado.system_address, nombre, guardado.posicion)

    def contradice(self, visita: Visita) -> bool:
        """True si ese nombre ya lo tiene otro sistema: el mensaje no cuadra y se descarta.

        Los nombres son únicos en el juego. Quien llegó antes (o es de fuente fiable)
        conserva el nombre; un duplicado por EDDN no puede desviar los mercados.
        """
        self._sincronizar()
        conocido = self._cache.get(visita.nombre)
        if conocido is not None:
            return conocido.system_address != visita.system_address
        return self._leer_bool(
            lambda c: mercado.nombre_en_uso_por_otro(c, visita.nombre, visita.system_address)
        )

    def aprender(self, visita: Visita) -> Sistema | None:
        """El sistema si es nuevo para la caché; None si ya se conocía con esa dirección.

        Lo que ya está en la base manda sobre el mensaje: las coordenadas no cambian.
        """
        self._sincronizar()
        conocido = self._cache.get(visita.nombre)
        if conocido is not None and conocido.system_address == visita.system_address:
            self._cache.move_to_end(visita.nombre)
            return None
        guardado = self._leer(lambda c: mercado.sistema_por_direccion(c, visita.system_address))
        if guardado is not None:
            return self._recordar(guardado.system_address, guardado.nombre, guardado.posicion)
        return self._recordar(visita.system_address, visita.nombre, visita.posicion)

    def cerrar(self) -> None:
        if self._lectura is not None:
            self._lectura.close()
            self._lectura = None

    def _recordar(self, direccion: int, nombre: str, posicion: tuple) -> Sistema:
        sistema = Sistema(direccion, nombre, posicion, self._esfera.distancia(posicion))
        self._cache[nombre] = sistema
        self._cache.move_to_end(nombre)
        while len(self._cache) > self._capacidad:
            self._cache.popitem(last=False)
        return sistema

    def _leer_de_la_base(self, nombre: str) -> Sistema | None:
        return self._leer(lambda c: mercado.sistema_por_nombre(c, nombre))

    def _leer_bool(self, consulta: Callable[[sqlite3.Connection], bool]) -> bool:
        resultado = self._leer(consulta)
        return bool(resultado)

    def _leer(self, consulta: Callable[[sqlite3.Connection], Sistema | None]) -> Sistema | None:
        try:
            if self._lectura is None:
                self._lectura = escritor.abrir_lectura(self._base)
            return consulta(self._lectura)
        except sqlite3.Error:
            registro.exception("no se pudo consultar el sistema en la base")
            self.cerrar()
            return None
