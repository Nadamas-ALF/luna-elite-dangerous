"""El sonido de las alertas, reproducido desde Python (sección 2: sin restricciones del navegador).

`winsound` no tiene volumen: las muestras del `.wav` se escalan en memoria y se
reproducen con `SND_MEMORY`, que no admite `SND_ASYNC`. Por eso suena en un hilo
propio, y pedir que suene nunca espera: si ya hay un sonido esperando, se descarta.
"""

from __future__ import annotations

import array
import contextlib
import io
import logging
import queue
import sys
import threading
import wave
from collections.abc import Callable
from pathlib import Path

from core import recursos
from core.config import ajustes

registro = logging.getLogger("luna.sonido")

Reproductor = Callable[[bytes], None]


def _winsound(datos: bytes) -> None:
    import winsound  # solo existe en Windows

    winsound.PlaySound(datos, winsound.SND_MEMORY | winsound.SND_NODEFAULT)


def con_volumen(wav: bytes, volumen: int) -> bytes:
    """El mismo `.wav` de 16 bits con las muestras escaladas a `volumen` (0 a 100)."""
    with wave.open(io.BytesIO(wav), "rb") as entrada:
        parametros = entrada.getparams()
        muestras = array.array("h", entrada.readframes(parametros.nframes))
    if sys.byteorder == "big":
        muestras.byteswap()
    factor = volumen / 100
    escaladas = array.array("h", (int(m * factor) for m in muestras))
    if sys.byteorder == "big":
        escaladas.byteswap()
    salida = io.BytesIO()
    with wave.open(salida, "wb") as destino:
        destino.setparams(parametros)
        destino.writeframes(escaladas.tobytes())
    return salida.getvalue()


class Sonido:
    def __init__(
        self,
        config: Path,
        archivo: Path | None = None,
        reproducir: Reproductor = _winsound,
    ) -> None:
        self._config = config
        self._archivo = archivo or recursos.ruta("data", "alerta.wav")
        self._reproducir = reproducir
        self._cola: queue.Queue[int | None] = queue.Queue(maxsize=1)
        self._hilo = threading.Thread(target=self._bucle, name="sonido", daemon=True)

    def iniciar(self) -> None:
        self._hilo.start()

    def detener(self) -> None:
        if not self._hilo.is_alive():
            return
        try:
            self._cola.put(None, timeout=1)
        except queue.Full:
            return
        self._hilo.join(2)

    def alerta(self) -> None:
        """Suena con el ajuste de Configuración, si está activado."""
        activado, volumen = ajustes.sonido(self._config)
        if activado:
            self.probar(volumen)

    def probar(self, volumen: int) -> None:
        # Si ya va a sonar uno, dos seguidos no avisan de nada más.
        with contextlib.suppress(queue.Full):
            self._cola.put_nowait(volumen)

    def _bucle(self) -> None:
        while (volumen := self._cola.get()) is not None:
            try:
                self._reproducir(con_volumen(self._archivo.read_bytes(), volumen))
            except Exception:  # noqa: BLE001 - sin sonido, la alerta sigue en pantalla
                registro.exception("no se pudo reproducir el sonido de la alerta")
