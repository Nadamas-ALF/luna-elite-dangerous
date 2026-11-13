"""Qué se hace con cada mensaje de EDDN (sección 4.2 y reglas de la 5.4).

Un mensaje entra, se interpreta y, si cae dentro de la esfera, se encola como
trabajo para el hilo escritor. Este hilo no escribe nunca en la base. Se usa
desde el hilo del suscriptor; el candado cubre lo que toca también el hilo escritor.
"""

from __future__ import annotations

import threading
from collections import Counter, OrderedDict
from collections.abc import Callable
from datetime import timedelta

from core import events
from core.db import mercado
from core.db.escritor import Escritor
from core.db.mercado import Sistema
from core.eddn import mensaje
from core.eddn.espera import Espera
from core.eddn.mensaje import MercadoDeRed, Visita
from core.eddn.sistemas import Conocidos
from core.esfera import Esfera, EsferaViva

# Mismo tope que la caché de sistemas: recordar qué se envió ya al escritor.
RECORDADOS = 20_000

RECIBIDO = "recibido"
GUARDADO = "guardado"
REPETIDO = "repetido"
FUERA_DE_LA_ESFERA = "fuera_de_la_esfera"
EN_ESPERA = "en_espera"
IGNORADO = "ignorado"
CONFLICTO = "conflicto"


class Ingesta:
    def __init__(
        self,
        escritor: Escritor,
        bus: events.Bus,
        esfera: Esfera | EsferaViva,
        conocidos: Conocidos,
        espera: Espera | None = None,
        antiguedad: Callable[[], timedelta] = lambda: mensaje.ANTIGUEDAD_MAXIMA,
    ) -> None:
        self._escritor = escritor
        self._bus = bus
        self._esfera = esfera
        self._conocidos = conocidos
        self._espera = Espera() if espera is None else espera
        self._antiguedad = antiguedad
        self._mercados_enviados: OrderedDict[int, str] = OrderedDict()
        self._estaciones_enviadas: OrderedDict[int, mercado.Estacion] = OrderedDict()
        self._contadores: Counter[str] = Counter()
        # El aviso de «guardado» llega desde el hilo escritor.
        self._candado = threading.Lock()

    def resumen(self) -> dict[str, int]:
        with self._candado:
            return dict(self._contadores)

    def procesar(self, crudo: bytes) -> None:
        self._contar(RECIBIDO)
        try:
            resultado = mensaje.interpretar(crudo, antiguedad=self._antiguedad())
        except mensaje.Descartado as descarte:
            self._contar(descarte.motivo)
            return
        if isinstance(resultado, Visita):
            self._visita(resultado)
        elif isinstance(resultado, MercadoDeRed):
            self._mercado(resultado)
        else:
            self._contar(IGNORADO)

    def _contar(self, clave: str) -> None:
        with self._candado:
            self._contadores[clave] += 1

    def pendientes(self) -> int:
        return len(self._espera)

    def cerrar(self) -> None:
        self._conocidos.cerrar()

    def _visita(self, visita: Visita) -> None:
        if self._conocidos.contradice(visita):
            self._contar(CONFLICTO)
            return
        nuevo = self._conocidos.aprender(visita)
        if nuevo is not None and self._esfera.contiene(nuevo.posicion):
            self._enviar_visita(nuevo, visita)
        elif visita.estacion is not None and self._esfera.contiene(visita.posicion):
            self._enviar_estacion(visita)
        if nuevo is not None:
            for esperaba in self._espera.liberar(visita.nombre):
                self._mercado(esperaba)

    def _enviar_visita(self, sistema: Sistema, visita: Visita) -> None:
        self._recordar_estacion(visita)
        self._escritor.encolar(
            lambda c: mercado.guardar_visita(c, sistema, visita.estacion, visita.observado)
        )

    def _enviar_estacion(self, visita: Visita) -> None:
        """El sistema ya estaba guardado; solo cambia si la estación es nueva o distinta."""
        sistema = self._conocidos.buscar(visita.nombre)
        if sistema is None or not self._recordar_estacion(visita):
            return
        self._escritor.encolar(
            lambda c: mercado.guardar_visita(c, sistema, visita.estacion, visita.observado)
        )

    def _recordar_estacion(self, visita: Visita) -> bool:
        """True si la estación es nueva o distinta de la última que se envió."""
        estacion = visita.estacion
        if estacion is None:
            return False
        if self._estaciones_enviadas.get(estacion.market_id) == estacion:
            return False
        _acotar(self._estaciones_enviadas, estacion.market_id, estacion)
        return True

    def _mercado(self, recibido: MercadoDeRed) -> None:
        sistema = self._conocidos.buscar(recibido.sistema)
        if sistema is None:
            self._espera.guardar(recibido)
            self._contar(EN_ESPERA)
            return
        if not self._esfera.contiene(sistema.posicion):
            self._contar(FUERA_DE_LA_ESFERA)
            return
        market_id = recibido.estacion.market_id
        with self._candado:
            visto = self._mercados_enviados.get(market_id, "")
        if visto >= recibido.observado:
            self._contar(REPETIDO)
            return
        self._enviar_mercado(sistema, recibido)

    def _enviar_mercado(self, sistema: Sistema, recibido: MercadoDeRed) -> None:
        market_id = recibido.estacion.market_id

        def guardar(conexion) -> bool:
            return mercado.guardar_de_red(
                conexion,
                sistema,
                recibido.estacion,
                recibido.articulos,
                mercado.ORIGEN_EDDN,
                recibido.observado,
            )

        def avisar(guardado: object) -> None:
            # Solo se recuerda lo que el escritor procesó: si el trabajo falla, se reintenta.
            with self._candado:
                _acotar(self._mercados_enviados, market_id, recibido.observado)
            if guardado:
                self._contar(GUARDADO)
                self._bus.publicar(events.MERCADO_ACTUALIZADO, market_id)

        self._escritor.encolar(guardar, avisar)


def _acotar(recuerdo: OrderedDict, clave: int, valor: object) -> None:
    recuerdo[clave] = valor
    recuerdo.move_to_end(clave)
    while len(recuerdo) > RECORDADOS:
        recuerdo.popitem(last=False)
