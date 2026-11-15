"""La única clase que la interfaz puede llamar (sección 10.2).

pywebview expone todos los métodos públicos y también recorre los atributos
públicos que sean objetos: por eso todo lo interno lleva guion bajo. Ningún
método recibe rutas ni datos de la interfaz; la carpeta del journal se elige
con el diálogo nativo de Windows. Los datos de Spansh, la esfera y la retención
llegan como texto y números simples y `Datos` los valida antes de usarlos; los
perfiles de búsqueda los valida `Comercio`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from core.config import ajustes
from core.config.rutas import Ubicacion
from core.datos import Datos
from core.journal import carpeta
from core.nucleo import Nucleo
from core.state import vista

if TYPE_CHECKING:
    from modules.comercio.api import Comercio

registro = logging.getLogger("luna.api")

Selector = Callable[[], str | None]

_NO_DISPONIBLE = {"error": "no_disponible"}


class Api:
    def __init__(
        self,
        nucleo: Nucleo,
        ubicacion: Ubicacion,
        config: Path,
        base_disponible: bool,
        elegir_carpeta: Selector,
        estado_eddn: Callable[[], str] = lambda: "desactivado",
        datos: Datos | None = None,
        avisos_de_base: Callable[[], tuple[str, ...]] = tuple,
        comercio: Comercio | None = None,
    ) -> None:
        self._nucleo = nucleo
        self._ubicacion = ubicacion
        self._config = config
        self._base_disponible = base_disponible
        self._elegir_carpeta = elegir_carpeta
        self._estado_eddn = estado_eddn
        self._datos = datos
        self._avisos_de_base = avisos_de_base
        self._comercio = comercio

    def estado(self) -> dict:
        contexto = vista.Contexto(
            journal=self._nucleo.estado_del_journal(),
            motivo_datos=self._ubicacion.motivo,
            avisos_datos=(*self._ubicacion.avisos, *self._avisos_de_base()),
            base_disponible=self._base_disponible,
            eddn=self._estado_eddn(),
            **self._contexto_de_datos(),
        )
        return vista.a_diccionario(self._nucleo.estado(), contexto)

    def _contexto_de_datos(self) -> dict:
        if self._datos is None:
            return {}
        return {"esfera": self._datos.esfera_actual(), "spansh": self._datos.spansh()}

    def configuracion(self) -> dict:
        elegida = ajustes.carpeta_journal(self._config)
        usada = carpeta.resolver(elegida)
        return {
            **(self._datos.configuracion() if self._datos else {}),
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

    def spansh(self) -> dict:
        return self._datos.spansh() if self._datos else _NO_DISPONIBLE

    def proponer_esfera(self, nombre: str, radio: float) -> dict:
        """Lo que hay que enseñar antes de confirmar un cambio de centro o de radio."""
        return self._datos.proponer_esfera(nombre, radio) if self._datos else _NO_DISPONIBLE

    def aplicar_esfera(self, nombre: str, radio: float, descargar: bool) -> dict:
        if self._datos is None:
            return _NO_DISPONIBLE
        return self._datos.aplicar_esfera(nombre, radio, descargar)

    def guardar_retencion(self, visitados_dias: float, antiguedad_maxima_dias: float) -> dict:
        if self._datos is None:
            return _NO_DISPONIBLE
        return self._datos.guardar_retencion(visitados_dias, antiguedad_maxima_dias)

    def establecer_eddn(self, activado: bool) -> dict:
        return self._datos.establecer_eddn(activado) if self._datos else _NO_DISPONIBLE

    def reanudar_descarga(self) -> dict:
        return self._datos.reanudar() if self._datos else _NO_DISPONIBLE

    def pausar_descarga(self) -> dict:
        return self._datos.pausar() if self._datos else _NO_DISPONIBLE

    def cancelar_descarga(self) -> dict:
        return self._datos.cancelar() if self._datos else _NO_DISPONIBLE

    def perfil_inicial(self) -> dict:
        return self._comercio.perfil_inicial() if self._comercio else _NO_DISPONIBLE

    def buscar_rutas(self, modo: str, perfil: dict) -> dict:
        return self._comercio.buscar_rutas(modo, perfil) if self._comercio else _NO_DISPONIBLE

    def ahora(self, perfil: dict) -> dict:
        return self._comercio.ahora(perfil) if self._comercio else _NO_DISPONIBLE

    def perfiles_guardados(self) -> dict:
        return self._comercio.perfiles_guardados() if self._comercio else _NO_DISPONIBLE

    def guardar_perfil(self, nombre: str, perfil: dict) -> dict:
        return self._comercio.guardar_perfil(nombre, perfil) if self._comercio else _NO_DISPONIBLE

    def borrar_perfil(self, nombre: str) -> dict:
        return self._comercio.borrar_perfil(nombre) if self._comercio else _NO_DISPONIBLE

    def ajustes_de_busqueda(self) -> dict:
        return self._comercio.ajustes_de_busqueda() if self._comercio else _NO_DISPONIBLE

    def guardar_ajustes_de_busqueda(self, tope_dias: int, tipos: list) -> dict:
        if self._comercio is None:
            return _NO_DISPONIBLE
        return self._comercio.guardar_ajustes_de_busqueda(tope_dias, tipos)

    def _con_resultado(self, guardado: bool) -> dict:
        return {**self.configuracion(), "no_guardado": not guardado}

    def _guardar_carpeta(self, elegida: str | None) -> bool:
        """Solo reconstruye el núcleo si el cambio quedó escrito."""
        guardado = ajustes.guardar_carpeta_journal(self._config, elegida)
        if guardado:
            self._nucleo.reiniciar_journal()
        return guardado
