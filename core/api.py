"""La única clase que la interfaz puede llamar (sección 10.2).

pywebview expone todos los métodos públicos y también recorre los atributos
públicos que sean objetos: por eso todo lo interno lleva guion bajo. Ningún
método recibe rutas ni datos de la interfaz; la carpeta del journal se elige
con el diálogo nativo de Windows.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from core.config import ajustes
from core.config.rutas import Ubicacion
from core.journal import carpeta
from core.nucleo import Nucleo
from core.state import vista

registro = logging.getLogger("luna.api")

Selector = Callable[[], str | None]


class Api:
    def __init__(
        self,
        nucleo: Nucleo,
        ubicacion: Ubicacion,
        config: Path,
        base_disponible: bool,
        elegir_carpeta: Selector,
        estado_eddn: Callable[[], str] = lambda: "desactivado",
    ) -> None:
        self._nucleo = nucleo
        self._ubicacion = ubicacion
        self._config = config
        self._base_disponible = base_disponible
        self._elegir_carpeta = elegir_carpeta
        self._estado_eddn = estado_eddn

    def estado(self) -> dict:
        contexto = vista.Contexto(
            journal=self._nucleo.estado_del_journal(),
            motivo_datos=self._ubicacion.motivo,
            avisos_datos=self._ubicacion.avisos,
            base_disponible=self._base_disponible,
            eddn=self._estado_eddn(),
        )
        return vista.a_diccionario(self._nucleo.estado(), contexto)

    def configuracion(self) -> dict:
        elegida = ajustes.carpeta_journal(self._config)
        usada = carpeta.resolver(elegida)
        return {
            "journal": {
                "carpeta": str(usada) if usada else None,
                "automatica": elegida is None,
                "elegida_no_existe": elegida is not None and not Path(elegida).is_dir(),
            },
            "datos": {"carpeta": str(self._ubicacion.carpeta)},
        }

    def elegir_carpeta_journal(self) -> dict:
        """Abre el diálogo nativo; si el usuario cancela, no cambia nada."""
        try:
            seleccion = self._elegir_carpeta()
        except Exception:  # noqa: BLE001 - un diálogo roto no debe tumbar la interfaz
            registro.exception("no se pudo abrir el dialogo de carpeta")
            seleccion = None
        if not seleccion:
            return self.configuracion()
        return self._con_resultado(self._guardar_carpeta(seleccion))

    def usar_carpeta_automatica(self) -> dict:
        return self._con_resultado(self._guardar_carpeta(None))

    def _con_resultado(self, guardado: bool) -> dict:
        return {**self.configuracion(), "no_guardado": not guardado}

    def _guardar_carpeta(self, elegida: str | None) -> bool:
        """Solo reconstruye el núcleo si el cambio quedó escrito."""
        guardado = ajustes.guardar_carpeta_journal(self._config, elegida)
        if guardado:
            self._nucleo.reiniciar_journal()
        return guardado
