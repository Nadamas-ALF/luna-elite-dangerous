"""Limpieza periódica de los mercados (regla 8 de la sección 5.4).

Corre al arrancar y luego cada hora. El trabajo en sí lo hace el hilo escritor;
este hilo solo lo encola, así que nunca toca la base directamente.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from core.config import ajustes
from core.db import espacio, retencion
from core.db.escritor import Escritor
from core.esfera import Esfera, EsferaViva

registro = logging.getLogger("luna.mantenimiento")

INTERVALO = 3600.0


class Mantenimiento:
    def __init__(
        self,
        escritor: Escritor,
        esfera: EsferaViva,
        config: Path,
        intervalo: float = INTERVALO,
        reloj: Callable[[], datetime] = lambda: datetime.now(UTC),
        en_pausa: Callable[[], bool] = lambda: False,
    ) -> None:
        self._escritor = escritor
        self._esfera = esfera
        self._config = config
        self._intervalo = intervalo
        self._reloj = reloj
        # Durante una descarga de Spansh no se limpia: lo de fuera de la esfera nueva
        # se borra al terminar, no antes (regla 6 de la 5.4).
        self._en_pausa = en_pausa
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._bucle, name="mantenimiento", daemon=True)
        self._acumulado = retencion.Limpieza()

    def iniciar(self) -> None:
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
        if self._hilo.is_alive():
            self._hilo.join(5)

    def _reglas(self) -> retencion.Reglas:
        return retencion.Reglas(
            ajustes.dias_de_mercados_visitados(self._config),
            ajustes.antiguedad_maxima_de_precios(self._config),
        )

    def limpiar(self) -> None:
        self._lote(retencion.limpiar)

    def aplicar_esfera(self) -> None:
        """Tras cambiar el centro o el radio: recalcula distancias y limpia lo que sobra."""
        self._lote(retencion.aplicar_esfera)

    def _lote(self, operacion: Callable[..., retencion.Limpieza]) -> None:
        """Un lote por trabajo del escritor; si quedan más, se encola el siguiente.

        Entre lote y lote el escritor atiende lo demás (EDDN, tus mercados), y lo ya
        borrado queda confirmado aunque LUNA se cierre.
        """
        esfera = self._esfera_fiable()
        if esfera is None:
            registro.warning("config.json no se puede leer: no se limpia, para no borrar por error")
            self._acumulado = retencion.Limpieza()
            return
        reglas, ahora = self._reglas(), self._reloj()
        self._escritor.encolar(
            lambda conexion: operacion(conexion, esfera, reglas, ahora), self._tras_el_lote
        )

    def _esfera_fiable(self) -> Esfera | None:
        """La esfera con la que limpiar, o None si no hay que fiarse de ella.

        Con config.json ilegible, la esfera y los plazos son los de por defecto (100 ly y
        30 días): limpiar con ellos borraría, sin vuelta atrás, lo descargado fuera de 100 ly.
        """
        if not ajustes.configuracion_legible(self._config):
            return None
        if not self._esfera.fiable:
            # LUNA arrancó con el archivo ilegible y ahora se lee: se corrige la esfera viva.
            self._esfera.cambiar(ajustes.esfera(self._config))
        return self._esfera.actual

    def _tras_el_lote(self, resultado: object) -> None:
        if not isinstance(resultado, retencion.Limpieza):
            return
        self._acumulado = self._acumulado + resultado
        if resultado.incompleta and not self._parar.is_set():
            # Las distancias ya se recalcularon en el primer lote.
            self._lote(retencion.limpiar)
            return
        self._informar(self._acumulado)
        self._acumulado = retencion.Limpieza()
        self._devolver_espacio()

    def _devolver_espacio(self) -> None:
        """Tras limpiar, las páginas libres vuelven al disco, por tandas que no bloquean."""
        self._escritor.encolar(espacio.devolver, self._seguir_devolviendo)

    def _seguir_devolviendo(self, resultado: object) -> None:
        if not isinstance(resultado, tuple):
            return
        antes, despues = resultado
        # Solo si quedó mucho y la tanda sirvió: sin esto, un fallo a medias haría un bucle.
        if despues > espacio.UMBRAL_DE_PAGINAS and despues < antes and not self._parar.is_set():
            self._devolver_espacio()

    @staticmethod
    def _informar(resultado: retencion.Limpieza) -> None:
        if resultado.total:
            registro.info(
                "limpieza: %d precios viejos, %d de fuera de la esfera, %d estaciones, "
                "%d sistemas, %d falsos",
                resultado.precios_viejos,
                resultado.precios_fuera,
                resultado.estaciones,
                resultado.sistemas,
                resultado.impostores,
            )

    def _bucle(self) -> None:
        # Al arrancar también se recalculan las distancias: el centro pudo cambiar con LUNA cerrada.
        self.aplicar_esfera()
        while not self._parar.wait(self._intervalo):
            if not self._en_pausa():
                self.limpiar()
