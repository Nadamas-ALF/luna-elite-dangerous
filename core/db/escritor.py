"""Hilo escritor único de SQLite (regla de concurrencia de la sección 3).

Las funciones de `js_api` corren en hilos propios y no son thread-safe, así que
ningún otro hilo toca la conexión de escritura: todos le mandan trabajos por la
cola. Cada trabajo se ejecuta en su propia transacción.
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

from core.db import esquema

registro = logging.getLogger("luna.db")

Trabajo = Callable[[sqlite3.Connection], object]
Despues = Callable[[object], None]

_FIN = None
ESPERA_DE_ARRANQUE = 10.0
ESPERA_DE_CIERRE = 10.0


class NoSePudoAbrir(RuntimeError):
    """La base no se abrió o no se pudo migrar."""


def abrir(ruta: Path) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: las transacciones las gestiona el propio escritor.
    conexion = sqlite3.connect(ruta, isolation_level=None)
    conexion.execute("PRAGMA journal_mode = WAL")
    conexion.execute("PRAGMA synchronous = NORMAL")
    conexion.execute("PRAGMA foreign_keys = ON")
    conexion.execute("PRAGMA busy_timeout = 5000")
    return conexion


def abrir_lectura(ruta: Path) -> sqlite3.Connection:
    """Conexión propia de solo lectura, para quien consulta desde otro hilo."""
    conexion = sqlite3.connect(f"{ruta.resolve().as_uri()}?mode=ro", uri=True)
    conexion.execute("PRAGMA busy_timeout = 5000")
    return conexion


class Escritor:
    def __init__(self, ruta: Path) -> None:
        self._ruta = ruta
        self._cola: queue.Queue[tuple[Trabajo, Despues | None] | None] = queue.Queue()
        self._hilo = threading.Thread(target=self._bucle, name="escritor-sqlite", daemon=True)
        self._listo = threading.Event()
        self._error: Exception | None = None

    def iniciar(self) -> None:
        self._hilo.start()
        if not self._listo.wait(ESPERA_DE_ARRANQUE):
            raise NoSePudoAbrir("la base de datos tarda demasiado en abrirse")
        if self._error is not None:
            raise NoSePudoAbrir(str(self._error)) from self._error

    def encolar(self, trabajo: Trabajo, despues: Despues | None = None) -> None:
        """`despues` recibe el resultado del trabajo cuando su transacción ya se confirmó."""
        self._cola.put((trabajo, despues))

    def detener(self) -> None:
        """Termina lo ya encolado y cierra la conexión."""
        self._cola.put(_FIN)
        self._hilo.join(ESPERA_DE_CIERRE)

    def _bucle(self) -> None:
        try:
            conexion = abrir(self._ruta)
            esquema.migrar(conexion)
        except (sqlite3.Error, OSError, esquema.BaseDeDatosPosterior) as error:
            self._error = error
            self._listo.set()
            return
        self._listo.set()
        try:
            self._atender(conexion)
        finally:
            conexion.close()

    def _atender(self, conexion: sqlite3.Connection) -> None:
        while (tarea := self._cola.get()) is not _FIN:
            self._ejecutar(conexion, *tarea)

    @staticmethod
    def _ejecutar(conexion: sqlite3.Connection, trabajo: Trabajo, despues: Despues | None) -> None:
        try:
            conexion.execute("BEGIN IMMEDIATE")
            resultado = trabajo(conexion)
            conexion.execute("COMMIT")
        except Exception:  # noqa: BLE001 - un trabajo roto no debe parar al escritor
            registro.exception("fallo un trabajo de escritura")
            if conexion.in_transaction:
                conexion.execute("ROLLBACK")
            return
        if despues is not None:
            try:
                despues(resultado)
            except Exception:  # noqa: BLE001 - un aviso roto no debe parar al escritor
                registro.exception("fallo el aviso posterior a un trabajo")
