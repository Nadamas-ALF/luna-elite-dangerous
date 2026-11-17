"""Importar el historial completo del journal, una sola vez y a petición (7.5).

Lee todos los journals de la carpeta de más antiguo a más reciente, con su propio
`Plegador` y sin tocar el estado del seguimiento en vivo, y guarda por la cola del
escritor lo mismo que el seguimiento: compras, ventas, tramos, bloques de actividad y
muestras de tiempo. Repetirlo no duplica nada: esas tablas ignoran lo ya guardado.

Un journal de Legacy se salta (sus datos no valen para Live) y uno ilegible se cuenta
y no detiene el resto. El journal sigue siendo de solo lectura.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from core.db.escritor import Escritor
from core.journal import lector, plegado
from core.state.estado import Estado

registro = logging.getLogger("luna.historial")

INACTIVA = "inactiva"
IMPORTANDO = "importando"
TERMINADA = "terminada"
CANCELADA = "cancelada"
ERROR = "error"

ESPERA_DE_CIERRE = 10.0


class Importador:
    def __init__(self, escritor: Escritor | None) -> None:
        self._escritor = escritor
        self._candado = threading.Lock()
        self._hilo: threading.Thread | None = None
        self._parar = threading.Event()
        self._fase = INACTIVA
        self._total = self._leidos = self._saltados = self._ilegibles = 0
        self._operaciones = self._tramos = self._fallos = 0
        # Cada ejecución se numera para que una cancelada no cierre a la siguiente.
        self._numero = 0

    def estado(self) -> dict:
        with self._candado:
            return {
                "fase": self._fase,
                "total": self._total,
                "leidos": self._leidos,
                "saltados": self._saltados,
                "ilegibles": self._ilegibles,
                "operaciones": self._operaciones,
                "tramos": self._tramos,
            }

    def iniciar(self, carpeta: Path) -> bool:
        """False si no hay base donde guardar o ya hay una importación en marcha."""
        if self._escritor is None:
            return False
        with self._candado:
            if self._fase == IMPORTANDO:
                return False
            journals = lector.listar(carpeta)
            self._numero += 1
            self._fase = IMPORTANDO
            self._total = len(journals)
            self._leidos = self._saltados = self._ilegibles = 0
            self._operaciones = self._tramos = self._fallos = 0
            self._parar.clear()
            self._hilo = threading.Thread(
                target=self._correr, args=(journals, self._numero), name="historial", daemon=True
            )
        self._hilo.start()
        return True

    def cancelar(self) -> None:
        self._parar.set()

    def detener(self) -> None:
        self._parar.set()
        if self._hilo is not None and self._hilo.is_alive():
            self._hilo.join(ESPERA_DE_CIERRE)

    def _correr(self, journals: list[Path], numero: int) -> None:
        try:
            completa = self._recorrer(journals, numero)
            self._cerrar(numero, completa)
        except Exception:  # noqa: BLE001 - un fallo aquí no debe dejar la pantalla esperando
            registro.exception("fallo la importacion del historial")
            self._poner(numero, ERROR)

    def _recorrer(self, journals: list[Path], numero: int) -> bool:
        """False si se canceló antes de leerlos todos."""
        plegador = plegado.Plegador()
        estado = Estado()
        for archivo in journals:
            if self._parar.is_set():
                return False
            try:
                eventos = lector.leer_archivo(archivo)
            except OSError:
                registro.warning("no se pudo leer %s", archivo.name)
                with self._candado:
                    self._ilegibles += 1
                continue
            estado, lote = plegador.plegar(estado, eventos)
            plegado.guardar(
                self._escritor, lote, lambda _error, numero=numero: self._anotar_fallo(numero)
            )
            with self._candado:
                self._leidos += 1
                self._saltados += bool(estado.legacy)
                self._operaciones += len(lote.operaciones)
                self._tramos += len(lote.tramos)
        return True

    def _cerrar(self, numero: int, completa: bool) -> None:
        """Terminada o cancelada de verdad cuando el escritor ya guardó lo leído.

        Si no, la pantalla recargaría antes de tiempo y otra importación podría
        empezar con trabajos de esta todavía en la cola.
        """
        self._escritor.encolar(
            lambda _conexion: None,
            despues=lambda _resultado: self._poner(numero, self._fase_final(completa)),
            # Si ni este trabajo vacío se puede guardar, la fase no se quedaría en «importando».
            fallo=lambda _error: self._poner(numero, ERROR),
        )

    def _fase_final(self, completa: bool) -> str:
        with self._candado:
            if self._fallos:
                return ERROR
            return TERMINADA if completa else CANCELADA

    def _anotar_fallo(self, numero: int) -> None:
        with self._candado:
            if numero == self._numero:
                self._fallos += 1

    def _poner(self, numero: int, fase: str) -> None:
        with self._candado:
            if numero == self._numero:
                self._fase = fase
