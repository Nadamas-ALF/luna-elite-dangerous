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
from typing import Any

from core.db import espacio, esquema

registro = logging.getLogger("luna.db")

Trabajo = Callable[[sqlite3.Connection], object]
Despues = Callable[[object], None]
Fallo = Callable[[Exception], None]

_FIN = None
ESPERA_DE_ARRANQUE = 10.0
ESPERA_DE_CIERRE = 10.0
# Tamaño al que se recorta el WAL tras un punto de control (la importación de Spansh lo infla).
LIMITE_DEL_WAL = 64 * 1024 * 1024


class TrabajoCancelado(Exception):  # noqa: N818 - no es un error: lo pidió el usuario
    """Un trabajo que se interrumpe a propósito: se deshace sin dejar un error en el registro."""


class NoSePudoAbrir(RuntimeError):
    """La base no se abrió o no se pudo migrar."""


def abrir(ruta: Path) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: las transacciones las gestiona el propio escritor.
    conexion = sqlite3.connect(ruta, isolation_level=None)
    espacio.preparar_base_nueva(conexion)
    conexion.execute("PRAGMA journal_mode = WAL")
    conexion.execute("PRAGMA synchronous = NORMAL")
    conexion.execute("PRAGMA foreign_keys = ON")
    conexion.execute("PRAGMA busy_timeout = 5000")
    # Sin esto, tras una transacción enorme el WAL conserva su tamaño hasta que se cierra la base.
    conexion.execute(f"PRAGMA journal_size_limit = {LIMITE_DEL_WAL}")
    return conexion


def abrir_lectura(ruta: Path) -> sqlite3.Connection:
    """Conexión propia de solo lectura, para quien consulta desde otro hilo."""
    conexion = sqlite3.connect(f"{ruta.resolve().as_uri()}?mode=ro", uri=True)
    conexion.execute("PRAGMA busy_timeout = 5000")
    return conexion


class Escritor:
    def __init__(self, ruta: Path) -> None:
        self._ruta = ruta
        self._cola: queue.Queue[tuple[Trabajo, Despues | None, Fallo | None] | None] = queue.Queue()
        self._hilo = threading.Thread(target=self._bucle, name="escritor-sqlite", daemon=True)
        self._listo = threading.Event()
        self._error: Exception | None = None
        self._avisos: tuple[str, ...] = ()

    def iniciar(self) -> None:
        self._hilo.start()
        if not self._listo.wait(ESPERA_DE_ARRANQUE):
            raise NoSePudoAbrir("la base de datos tarda demasiado en abrirse")
        if self._error is not None:
            raise NoSePudoAbrir(str(self._error)) from self._error

    @property
    def avisos(self) -> tuple[str, ...]:
        """Códigos de lo que Estado debe contar de la base (compactando, sin espacio…)."""
        return self._avisos

    def encolar(
        self, trabajo: Trabajo, despues: Despues | None = None, fallo: Fallo | None = None
    ) -> None:
        """`despues` recibe el resultado del trabajo cuando su transacción ya se confirmó.

        `fallo` recibe la excepción si el trabajo falla y se deshizo su transacción.
        """
        self._cola.put((trabajo, despues, fallo))

    def pendientes(self) -> int:
        """Trabajos esperando turno; aproximado, porque otros hilos encolan a la vez (E-05)."""
        return self._cola.qsize()

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
        # El arranque no espera a la conversión, que puede tardar un minuto.
        self._listo.set()
        try:
            self._cuidar_el_espacio_sin_caer(conexion)
            self._atender(conexion)
        finally:
            conexion.close()

    def _cuidar_el_espacio_sin_caer(self, conexion: sqlite3.Connection) -> None:
        """Compactar es opcional: si algo falla, el escritor sigue atendiendo trabajos."""
        try:
            self._cuidar_el_espacio(conexion)
        except Exception:  # noqa: BLE001 - un fallo aquí no debe matar al único hilo escritor
            registro.exception("fallo al cuidar el espacio de la base")
            self._publicar_aviso(espacio.AVISO_SIN_COMPACTAR)

    def _cuidar_el_espacio(self, conexion: sqlite3.Connection) -> None:
        """Convierte una base anterior a `auto_vacuum` incremental, antes de atender trabajos."""
        resultado = espacio.convertir(
            conexion, self._ruta, lambda: self._publicar_aviso(espacio.AVISO_COMPACTANDO)
        )
        self._publicar_aviso(
            {
                espacio.SIN_ESPACIO: espacio.AVISO_SIN_ESPACIO,
                espacio.ERROR: espacio.AVISO_SIN_COMPACTAR,
            }.get(resultado)
        )

    def _publicar_aviso(self, codigo: str | None) -> None:
        self._avisos = (codigo,) if codigo else ()

    def _atender(self, conexion: sqlite3.Connection) -> None:
        while (tarea := self._cola.get()) is not _FIN:
            self._ejecutar(conexion, *tarea)

    @staticmethod
    def _ejecutar(
        conexion: sqlite3.Connection,
        trabajo: Trabajo,
        despues: Despues | None,
        fallo: Fallo | None,
    ) -> None:
        try:
            conexion.execute("BEGIN IMMEDIATE")
            resultado = trabajo(conexion)
            conexion.execute("COMMIT")
        except Exception as error:  # noqa: BLE001 - un trabajo roto no debe parar al escritor
            if isinstance(error, TrabajoCancelado):
                registro.info("un trabajo de escritura se canceló")
            else:
                registro.exception("fallo un trabajo de escritura")
            if conexion.in_transaction:
                conexion.execute("ROLLBACK")
            Escritor._avisar(fallo, error)
            return
        Escritor._avisar(despues, resultado)

    @staticmethod
    def _avisar(aviso: Callable[[Any], None] | None, argumento: object) -> None:
        if aviso is None:
            return
        try:
            aviso(argumento)
        except Exception:  # noqa: BLE001 - un aviso roto no debe parar al escritor
            registro.exception("fallo el aviso de un trabajo de escritura")
