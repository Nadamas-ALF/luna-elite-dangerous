"""Activar y desactivar la escucha de EDDN sin reiniciar LUNA.

Un `Suscriptor` no se puede reiniciar una vez parado, así que cada activación
construye uno nuevo con la fábrica. La fábrica decide si hay algo que escuchar
(ajuste activado y base de datos disponible) y devuelve `None` si no.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from core.eddn.suscriptor import DESACTIVADO, Suscriptor


class Servicio:
    def __init__(self, fabrica: Callable[[], Suscriptor | None]) -> None:
        self._fabrica = fabrica
        self._candado = threading.Lock()
        self._suscriptor: Suscriptor | None = None

    def iniciar(self) -> None:
        with self._candado:
            if self._suscriptor is not None:
                return
            suscriptor = self._fabrica()
            if suscriptor is not None:
                suscriptor.iniciar()
            self._suscriptor = suscriptor

    def detener(self) -> None:
        with self._candado:
            suscriptor, self._suscriptor = self._suscriptor, None
        if suscriptor is not None:
            suscriptor.detener()

    def estado(self) -> str:
        suscriptor = self._suscriptor
        return suscriptor.estado() if suscriptor is not None else DESACTIVADO
