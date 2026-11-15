"""Descarga reanudable del volcado de Spansh (secciones 4.3 y 10).

Solo HTTPS y solo al servidor de descargas de Spansh, también tras una
redirección. El archivo se baja a `<nombre>.part` junto a un `<nombre>.part.json`
con lo que se sabe del servidor; si la descarga se corta o se pausa, la siguiente
llamada continúa donde quedó. Si el archivo cambió en el servidor entre una
sesión y otra (otro `ETag`), se empieza de cero.

No escribe en la base de datos: solo entrega el archivo completo.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import logging
import os
import re
import shutil
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

registro = logging.getLogger("luna.spansh")

SERVIDOR = "downloads.spansh.co.uk"
URL = f"https://{SERVIDOR}/galaxy_stations.json.gz"
NOMBRE = "galaxy_stations.json.gz"

TROZO = 1024 * 1024
ESPERA_DE_RED = 30.0
# Margen sobre el tamaño del archivo para no dejar el disco justo.
MARGEN_DE_DISCO = 256 * 1024 * 1024
_MAGIA_GZIP = b"\x1f\x8b"
_RANGO_NO_SATISFACIBLE = 416
_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")

MOTIVO_URL = "url"
MOTIVO_RED = "red"
MOTIVO_HTTP = "http"
MOTIVO_CORTADA = "cortada"
MOTIVO_ESPACIO = "espacio"
MOTIVO_FORMATO = "formato"
MOTIVO_DESTINO = "destino"


class ErrorDeDescarga(Exception):
    """La descarga no terminó. Si quedó el `.part`, se puede reanudar."""

    def __init__(self, motivo: str, detalle: str = "") -> None:
        super().__init__(f"{motivo}: {detalle}" if detalle else motivo)
        self.motivo = motivo


@dataclass(frozen=True)
class Progreso:
    descargado: int
    total: int | None


Abrir = Callable[[str, Mapping[str, str]], "http.client.HTTPResponse"]


def validar_url(url: str) -> None:
    partes = urlsplit(url)
    if partes.scheme != "https" or partes.hostname != SERVIDOR or partes.username or partes.port:
        raise ErrorDeDescarga(MOTIVO_URL, "solo https al servidor de descargas de Spansh")


class _SoloSpansh(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        validar_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def abrir_https(url: str, cabeceras: Mapping[str, str]) -> http.client.HTTPResponse:
    validar_url(url)
    peticion = urllib.request.Request(url, headers={"User-Agent": "LUNA", **cabeceras})  # noqa: S310
    return urllib.request.build_opener(_SoloSpansh).open(peticion, timeout=ESPERA_DE_RED)


class Descarga:
    def __init__(
        self, carpeta: Path, url: str = URL, abrir: Abrir = abrir_https, trozo: int = TROZO
    ) -> None:
        validar_url(url)
        self._url = url
        self._abrir = abrir
        self._trozo = trozo
        self.final = carpeta / NOMBRE
        self._parcial = carpeta / f"{NOMBRE}.part"
        self._meta = carpeta / f"{NOMBRE}.part.json"

    def descartar(self) -> None:
        """Borra lo descargado a medias."""
        for archivo in (self._parcial, self._meta):
            archivo.unlink(missing_ok=True)

    def ejecutar(self, parar: threading.Event, progreso: Callable[[Progreso], None]) -> Path | None:
        """El archivo completo, o None si `parar` interrumpió la descarga (queda reanudable)."""
        self.final.parent.mkdir(parents=True, exist_ok=True)
        desplazamiento, etag, total = self._estado_guardado()
        if total is not None and desplazamiento == total:
            return self._terminar(total)
        respuesta = self._pedir(desplazamiento, etag)
        with respuesta:
            desplazamiento, total = self._aceptar(respuesta, desplazamiento, etag)
            self._comprobar_espacio(total, desplazamiento)
            self._guardar_meta(respuesta.headers.get("ETag"), total)
            try:
                terminada = self._copiar(respuesta, desplazamiento, total, parar, progreso)
            except ErrorDeDescarga as error:
                if error.motivo == MOTIVO_FORMATO:
                    self.descartar()
                raise
        if not terminada:
            return None
        return self._terminar(total)

    def _pedir(self, desplazamiento: int, etag: str | None):  # noqa: ANN202
        try:
            return self._abrir(self._url, self._cabeceras(desplazamiento, etag))
        except urllib.error.HTTPError as error:
            if error.code == _RANGO_NO_SATISFACIBLE:
                self.descartar()
            raise ErrorDeDescarga(MOTIVO_HTTP, str(error.code)) from error
        except (OSError, http.client.HTTPException) as error:
            raise ErrorDeDescarga(MOTIVO_RED, type(error).__name__) from error

    def pendiente(self) -> Progreso | None:
        """Lo que hay descargado a medias, sin tocar nada; None si no hay nada reanudable."""
        guardado = self._leer_estado()
        return Progreso(guardado[0], guardado[2]) if guardado else None

    def _leer_estado(self) -> tuple[int, str | None, int] | None:
        try:
            meta = json.loads(self._meta.read_text(encoding="utf-8"))
            etag, total = meta["etag"], meta["total"]
            tamano = self._parcial.stat().st_size
            valido = (
                meta["url"] == self._url
                and isinstance(total, int)
                and (etag is None or isinstance(etag, str))
                and tamano <= total
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return (tamano, etag, total) if valido else None

    def _estado_guardado(self) -> tuple[int, str | None, int | None]:
        guardado = self._leer_estado()
        if guardado is None:
            self.descartar()
            return 0, None, None
        return guardado

    @staticmethod
    def _cabeceras(desplazamiento: int, etag: str | None) -> dict[str, str]:
        if desplazamiento == 0:
            return {}
        # If-Range: si el archivo cambió, el servidor contesta 200 con el nuevo entero.
        return {"Range": f"bytes={desplazamiento}-", **({"If-Range": etag} if etag else {})}

    def _aceptar(self, respuesta, desplazamiento: int, etag: str | None) -> tuple[int, int]:  # noqa: ANN001
        """(desde dónde se escribe, tamaño total) según lo que contestó el servidor."""
        if respuesta.status == 206:
            # Un servidor que ignore If-Range mandaría el resto de otra versión del archivo.
            if etag is not None and respuesta.headers.get("ETag") != etag:
                self.descartar()
                raise ErrorDeDescarga(MOTIVO_HTTP, "ETag distinto al reanudar")
            coincidencia = _CONTENT_RANGE.fullmatch(respuesta.headers.get("Content-Range", ""))
            if coincidencia is None or int(coincidencia[1]) != desplazamiento:
                raise ErrorDeDescarga(MOTIVO_HTTP, "Content-Range inesperado")
            return desplazamiento, int(coincidencia[3])
        if respuesta.status == 200:
            if desplazamiento:
                registro.info("el volcado cambió en el servidor: se empieza de nuevo")
            longitud = respuesta.headers.get("Content-Length", "")
            if not longitud.isdigit():
                raise ErrorDeDescarga(MOTIVO_HTTP, "sin Content-Length")
            return 0, int(longitud)
        raise ErrorDeDescarga(MOTIVO_HTTP, str(respuesta.status))

    def _comprobar_espacio(self, total: int, desplazamiento: int) -> None:
        falta = total - desplazamiento + MARGEN_DE_DISCO
        try:
            libre = shutil.disk_usage(self.final.parent).free
        except OSError as error:
            raise ErrorDeDescarga(MOTIVO_DESTINO, type(error).__name__) from error
        if libre < falta:
            raise ErrorDeDescarga(MOTIVO_ESPACIO, f"faltan {falta - libre} bytes")

    def _guardar_meta(self, etag: str | None, total: int) -> None:
        datos = {"url": self._url, "etag": etag, "total": total}
        try:
            self._meta.write_text(json.dumps(datos), encoding="utf-8")
        except OSError as error:
            raise ErrorDeDescarga(MOTIVO_DESTINO, type(error).__name__) from error

    def _copiar(
        self,
        respuesta,  # noqa: ANN001
        desplazamiento: int,
        total: int,
        parar: threading.Event,
        progreso: Callable[[Progreso], None],
    ) -> bool:
        """False si se pidió parar. Lo ya escrito queda en el `.part`."""
        modo = "r+b" if desplazamiento else "wb"
        try:
            with self._parcial.open(modo) as salida:
                salida.seek(desplazamiento)
                salida.truncate()
                while desplazamiento < total:
                    if parar.is_set():
                        return False
                    trozo = self._leer(respuesta, min(self._trozo, total - desplazamiento))
                    if not trozo:
                        raise ErrorDeDescarga(MOTIVO_CORTADA, f"{desplazamiento} de {total}")
                    if desplazamiento == 0 and not trozo.startswith(_MAGIA_GZIP):
                        raise ErrorDeDescarga(MOTIVO_FORMATO, "no es un gzip")
                    salida.write(trozo)
                    desplazamiento += len(trozo)
                    progreso(Progreso(desplazamiento, total))
                salida.flush()
                os.fsync(salida.fileno())
        except OSError as error:
            raise ErrorDeDescarga(MOTIVO_DESTINO, type(error).__name__) from error
        return True

    @staticmethod
    def _leer(respuesta, cantidad: int) -> bytes:  # noqa: ANN001
        try:
            return respuesta.read(cantidad)
        except (OSError, http.client.HTTPException) as error:
            raise ErrorDeDescarga(MOTIVO_RED, type(error).__name__) from error

    def _terminar(self, total: int) -> Path:
        try:
            if self._parcial.stat().st_size != total:
                self.descartar()
                raise ErrorDeDescarga(MOTIVO_CORTADA, "el tamaño final no coincide")
            self._parcial.replace(self.final)
        except OSError as error:
            raise ErrorDeDescarga(MOTIVO_DESTINO, type(error).__name__) from error
        with contextlib.suppress(OSError):
            self._meta.unlink()
        return self.final
