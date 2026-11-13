"""El hilo que escucha el relay de EDDN (sección 4.2).

Solo hace conexiones salientes. ZeroMQ reconecta solo cuando se corta la red,
pero no avisa: una conexión muerta es indistinguible de un relay en silencio.
Por eso, si no llega nada en `SILENCIO_MAXIMO`, se descarta el socket y se abre
otro. El servicio Live se reinicia cada semana y esto lo cubre.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import zmq

from core.eddn.ingesta import Ingesta

registro = logging.getLogger("luna.eddn")

RELAY = "tcp://eddn.edcd.io:9500"

DESACTIVADO = "desactivado"
CONECTANDO = "conectando"
CONECTADO = "conectado"
SIN_DATOS = "sin_datos"
REINTENTANDO = "reintentando"

ESPERA_DE_LECTURA_MS = 1000
# El relay lleva varios mensajes por segundo; medio minuto sin ninguno es raro.
SIN_DATOS_TRAS = 30.0
SILENCIO_MAXIMO = 120.0
ESPERA_BASE = 5.0
ESPERA_MAXIMA = 300.0
# Un mercado grande ocupa unos 60 KB comprimido; el tope corta lo anómalo.
TAMANO_MAXIMO_COMPRIMIDO = 524_288
RESUMEN_CADA = 600.0


class Suscriptor:
    def __init__(
        self,
        ingesta: Ingesta,
        direccion: str = RELAY,
        contexto: zmq.Context | None = None,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ingesta = ingesta
        self._direccion = direccion
        self._contexto_ajeno = contexto
        self._reloj = reloj
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._bucle, name="eddn", daemon=True)
        self._estado = CONECTANDO
        self._fallos = 0

    def iniciar(self) -> None:
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
        if self._hilo.is_alive():
            self._hilo.join(5)

    def estado(self) -> str:
        return self._estado

    def _bucle(self) -> None:
        contexto = self._contexto_ajeno or zmq.Context()
        try:
            while not self._parar.is_set():
                self._una_conexion(contexto)
        finally:
            self._ingesta.cerrar()
            if self._contexto_ajeno is None:
                contexto.term()

    def _una_conexion(self, contexto: zmq.Context) -> None:
        """Escucha hasta que la conexión se da por muerta o llega la orden de parar."""
        self._estado = CONECTANDO
        try:
            socket = self._abrir(contexto)
        except zmq.ZMQError:
            registro.exception("no se pudo abrir el socket de EDDN")
        else:
            try:
                self._escuchar(socket)
            except zmq.ZMQError:
                registro.exception("fallo el socket de EDDN")
            finally:
                socket.close(linger=0)
        if not self._parar.is_set():
            self._esperar_para_reintentar()

    def _abrir(self, contexto: zmq.Context) -> zmq.Socket:
        socket = contexto.socket(zmq.SUB)
        try:
            socket.setsockopt(zmq.SUBSCRIBE, b"")
            socket.setsockopt(zmq.RCVTIMEO, ESPERA_DE_LECTURA_MS)
            socket.setsockopt(zmq.MAXMSGSIZE, TAMANO_MAXIMO_COMPRIMIDO)
            # Si la red cae, ZeroMQ reconecta él solo; que no lo haga cada 100 ms.
            socket.setsockopt(zmq.RECONNECT_IVL, 2000)
            socket.setsockopt(zmq.RECONNECT_IVL_MAX, 30000)
            socket.connect(self._direccion)
        except zmq.ZMQError:
            socket.close(linger=0)
            raise
        return socket

    def _escuchar(self, socket: zmq.Socket) -> None:
        ultimo = self._reloj()
        proximo_resumen = ultimo + RESUMEN_CADA
        while not self._parar.is_set():
            try:
                crudo = socket.recv()
            except zmq.Again:
                silencio = self._reloj() - ultimo
                if silencio > SILENCIO_MAXIMO:
                    registro.warning("EDDN sin mensajes desde hace %.0f s: se reconecta", silencio)
                    return
                if silencio > SIN_DATOS_TRAS:
                    self._estado = SIN_DATOS
                continue
            ultimo = self._reloj()
            self._estado = CONECTADO
            self._fallos = 0
            self._atender(crudo)
            if ultimo >= proximo_resumen:
                proximo_resumen = ultimo + RESUMEN_CADA
                self._resumir()

    def _resumir(self) -> None:
        registro.info("EDDN: %s, en espera %d", self._ingesta.resumen(), self._ingesta.pendientes())

    def _atender(self, crudo: bytes) -> None:
        try:
            self._ingesta.procesar(crudo)
        except Exception:  # noqa: BLE001 - un mensaje raro no debe tumbar el hilo
            registro.exception("fallo al procesar un mensaje de EDDN")

    def _esperar_para_reintentar(self) -> None:
        """Espera progresiva, para no martillear al relay mientras está de mantenimiento."""
        self._estado = REINTENTANDO
        espera = min(ESPERA_BASE * 2**self._fallos, ESPERA_MAXIMA)
        self._fallos += 1
        self._parar.wait(espera)
