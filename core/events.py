"""Bus de eventos interno: la frontera entre el núcleo y los módulos.

Los módulos se suscriben aquí y nunca leen el journal ni EDDN (sección 3). Los
manejadores se ejecutan en el hilo que publica, así que tienen que ser cortos.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable

registro = logging.getLogger("luna.eventos")

ESTADO_ACTUALIZADO = "estado_actualizado"
NAVE_CAMBIADA = "nave_cambiada"
ATRACADO = "atracado"
DESATRACADO = "desatracado"  # con la estación que se deja
CARGA_CAMBIADA = "carga_cambiada"
MERCADO_ACTUALIZADO = "mercado_actualizado"

Manejador = Callable[[object], None]


class Bus:
    def __init__(self) -> None:
        self._manejadores: dict[str, list[Manejador]] = defaultdict(list)
        self._candado = threading.Lock()

    def suscribir(self, tipo: str, manejador: Manejador) -> None:
        with self._candado:
            self._manejadores[tipo].append(manejador)

    def publicar(self, tipo: str, datos: object = None) -> None:
        with self._candado:
            manejadores = list(self._manejadores[tipo])
        for manejador in manejadores:
            try:
                manejador(datos)
            except Exception:  # noqa: BLE001 - un módulo roto no debe parar al núcleo
                registro.exception("fallo un manejador de %s", tipo)
