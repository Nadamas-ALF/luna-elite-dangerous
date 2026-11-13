"""Importación del volcado de Spansh a la base de datos (secciones 4.3 y 10.4).

Dos fases, para que un fallo a medias no deje la base a medio llenar:

1. **Leer** (hilo propio): recorre el gzip entero, valida cada línea y copia a un
   archivo temporal solo los sistemas dentro de la esfera. Al llegar al final se
   comprueba la integridad del gzip y que el arreglo JSON cierre. Si algo falla,
   la base no se ha tocado.
2. **Guardar**: un solo trabajo del hilo escritor vuelca ese archivo temporal en
   una transacción. Si falla o se cancela, se deshace entera. El escritor solo
   está ocupado el tiempo del volcado, no el de leer 4 GiB.

El archivo descargado se borra únicamente cuando todo salió bien.
"""

from __future__ import annotations

import gzip
import logging
import sqlite3
import threading
import time
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.db import mercado
from core.db.escritor import Escritor, TrabajoCancelado
from core.esfera import Esfera
from core.spansh import volcado
from core.validacion import Descartado

registro = logging.getLogger("luna.spansh")

LEYENDO = "leyendo"
GUARDANDO = "guardando"

MOTIVO_ARCHIVO = "archivo"
MOTIVO_FORMATO = "formato"
MOTIVO_BASE = "base"
MOTIVO_DESTINO = "destino"

# Las líneas de las zonas pobladas pesan cientos de KB: se mira el reloj, no el número de líneas.
SEGUNDOS_ENTRE_AVISOS = 0.5
CADA_CUANTAS_LINEAS_COMPROBAR = 20
CADA_CUANTOS_SISTEMAS_COMPROBAR = 200
# Un volcado sano casi no tiene líneas rotas; más de esto es que cambió el formato.
CANDIDATOS_MINIMOS = 200
DESCARTES_MAXIMOS = 0.05


class ErrorDeImportacion(Exception):
    def __init__(self, motivo: str, detalle: str = "") -> None:
        super().__init__(f"{motivo}: {detalle}" if detalle else motivo)
        self.motivo = motivo


class _Cancelada(TrabajoCancelado):
    pass


@dataclass(frozen=True)
class Progreso:
    fase: str
    leidas: int
    encontrados: int
    guardados: int
    # Bytes leídos del gzip y su tamaño: el avance real mientras se lee.
    posicion: int = 0
    total: int = 0


@dataclass(frozen=True)
class Resumen:
    leidas: int
    sistemas: int
    estaciones: int
    mercados: int
    precios: int
    descartados: int
    # Mercados que Spansh trae pero más viejos que la antigüedad máxima: no se guardan.
    mercados_viejos: int = 0


@dataclass
class _Lectura:
    leidas: int = 0
    encontrados: int = 0
    descartados: int = 0
    mercados_viejos: int = 0


def importar(
    archivo: Path,
    esfera: Esfera,
    escritor: Escritor,
    parar: threading.Event,
    avisar: Callable[[Progreso], None],
    ahora: datetime | None = None,
    dias_maximos: float | None = None,
) -> Resumen | None:
    """Bloquea hasta terminar. None si se canceló: la base queda como estaba.

    `dias_maximos`: un mercado más viejo no se guarda; la retención lo borraría
    enseguida y Spansh trae mercados de hace años.
    """
    ahora = ahora or datetime.now(UTC)
    corte = _marca(ahora - timedelta(days=dias_maximos)) if dias_maximos is not None else None
    intermedio = archivo.with_name(f"{archivo.name}.esfera")
    try:
        lectura = _leer(archivo, intermedio, esfera, ahora, corte, parar, avisar)
        if lectura is None:
            return None
        resumen = _guardar(intermedio, lectura, escritor, parar, avisar)
    finally:
        intermedio.unlink(missing_ok=True)
    if resumen is not None:
        archivo.unlink(missing_ok=True)
    return resumen


def _lineas(origen: gzip.GzipFile) -> Iterator[bytes | None]:
    """Líneas del volcado; None por cada una que excede el tope (se salta entera)."""
    tope = volcado.TAMANO_MAXIMO_DE_LINEA
    while linea := origen.readline(tope + 1):
        if len(linea) <= tope or linea.endswith(b"\n"):
            yield linea
            continue
        while resto := origen.readline(tope):
            if resto.endswith(b"\n"):
                break
        yield None


def _marca(fecha: datetime) -> str:
    return fecha.strftime("%Y-%m-%dT%H:%M:%SZ")


def _leer(
    archivo: Path,
    intermedio: Path,
    esfera: Esfera,
    ahora: datetime,
    corte: str | None,
    parar: threading.Event,
    avisar: Callable[[Progreso], None],
) -> _Lectura | None:
    lectura = _Lectura()
    abierto = cerrado = False
    total = archivo.stat().st_size
    proximo_aviso = 0.0
    try:
        with (
            archivo.open("rb") as bruto,
            gzip.GzipFile(fileobj=bruto) as origen,
            intermedio.open("wb") as salida,
        ):
            for linea in _lineas(origen):
                lectura.leidas += 1
                if lectura.leidas % CADA_CUANTAS_LINEAS_COMPROBAR == 0 and parar.is_set():
                    return None
                contenido = (linea or b"").strip()
                if cerrado and contenido:
                    raise ErrorDeImportacion(MOTIVO_FORMATO, "hay datos después de «]»")
                if not abierto:
                    if contenido != b"[":
                        raise ErrorDeImportacion(MOTIVO_FORMATO, "no empieza con «[»")
                    abierto = True
                    continue
                cerrado = contenido == b"]"
                _filtrar(linea, esfera, ahora, corte, salida, lectura)
                if (reloj := time.monotonic()) >= proximo_aviso:
                    proximo_aviso = reloj + SEGUNDOS_ENTRE_AVISOS
                    avisar(_progreso_de_lectura(lectura, bruto.tell(), total))
    except (EOFError, zlib.error) as error:
        raise ErrorDeImportacion(MOTIVO_ARCHIVO, "gzip incompleto o dañado") from error
    except gzip.BadGzipFile as error:
        raise ErrorDeImportacion(MOTIVO_ARCHIVO, "gzip dañado") from error
    except OSError as error:
        raise ErrorDeImportacion(MOTIVO_DESTINO, type(error).__name__) from error
    if not cerrado:
        raise ErrorDeImportacion(MOTIVO_FORMATO, "el arreglo no se cierra con «]»")
    _comprobar_descartes(lectura)
    avisar(_progreso_de_lectura(lectura, total, total))
    return lectura


def _progreso_de_lectura(lectura: _Lectura, posicion: int, total: int) -> Progreso:
    return Progreso(LEYENDO, lectura.leidas, lectura.encontrados, 0, posicion, total)


def _filtrar(  # noqa: PLR0913
    linea: bytes | None,
    esfera: Esfera,
    ahora: datetime,
    corte: str | None,
    salida,  # noqa: ANN001
    lectura: _Lectura,
) -> None:
    try:
        if linea is None:
            raise Descartado("demasiado_larga")
        sistema = volcado.interpretar(linea, esfera, ahora)
    except Descartado:
        lectura.descartados += 1
        return
    if sistema is None:
        return
    lectura.encontrados += 1
    lectura.descartados += sistema.estaciones_descartadas
    if corte is not None:
        sistema = _sin_mercados_viejos(sistema, corte, lectura)
    salida.write(volcado.serializar(sistema) + b"\n")
    if lectura.encontrados % CADA_CUANTOS_SISTEMAS_COMPROBAR == 0:
        _comprobar_descartes(lectura)


def _sin_mercados_viejos(
    sistema: volcado.SistemaDeVolcado, corte: str, lectura: _Lectura
) -> volcado.SistemaDeVolcado:
    """La estación se guarda; solo sus precios caducados se dejan fuera."""
    estaciones = []
    for estacion in sistema.estaciones:
        if estacion.observado is not None and estacion.observado < corte:
            lectura.mercados_viejos += 1
            estacion = replace(estacion, observado=None, articulos=None)
        estaciones.append(estacion)
    return replace(sistema, estaciones=tuple(estaciones))


def _comprobar_descartes(lectura: _Lectura) -> None:
    candidatos = lectura.encontrados + lectura.descartados
    if candidatos >= CANDIDATOS_MINIMOS and lectura.descartados / candidatos > DESCARTES_MAXIMOS:
        raise ErrorDeImportacion(
            MOTIVO_FORMATO, f"{lectura.descartados} de {candidatos} elementos inválidos"
        )


def _guardar(
    intermedio: Path,
    lectura: _Lectura,
    escritor: Escritor,
    parar: threading.Event,
    avisar: Callable[[Progreso], None],
) -> Resumen | None:
    terminado = threading.Event()
    desenlace: list[Resumen | Exception] = []

    def trabajo(conexion: sqlite3.Connection) -> Resumen:
        return _volcar(conexion, intermedio, lectura, parar, avisar)

    def bien(resumen: object) -> None:
        desenlace.append(resumen)  # type: ignore[arg-type]
        terminado.set()

    def mal(error: Exception) -> None:
        desenlace.append(error)
        terminado.set()

    escritor.encolar(trabajo, bien, mal)
    terminado.wait()
    resultado = desenlace[0]
    if isinstance(resultado, _Cancelada):
        return None
    if isinstance(resultado, Exception):
        raise ErrorDeImportacion(MOTIVO_BASE, type(resultado).__name__) from resultado
    return resultado


def _volcar(
    conexion: sqlite3.Connection,
    intermedio: Path,
    lectura: _Lectura,
    parar: threading.Event,
    avisar: Callable[[Progreso], None],
) -> Resumen:
    sistemas = estaciones = mercados = precios = 0
    proximo_aviso = 0.0
    total = intermedio.stat().st_size
    with intermedio.open("rb") as entrada:
        for linea in entrada:
            if sistemas % CADA_CUANTOS_SISTEMAS_COMPROBAR == 0 and parar.is_set():
                raise _Cancelada
            if (reloj := time.monotonic()) >= proximo_aviso:
                proximo_aviso = reloj + SEGUNDOS_ENTRE_AVISOS
                avisar(_progreso_de_guardado(lectura, sistemas, entrada.tell(), total))
            sistema = volcado.deserializar(linea)
            nuevos = _guardar_sistema(conexion, sistema)
            sistemas += 1
            estaciones += len(sistema.estaciones)
            mercados += nuevos[0]
            precios += nuevos[1]
    # Spansh manda sobre EDDN: los sistemas falsos que repetían un nombre real se van ahora.
    mercado.purgar_impostores(conexion)
    avisar(_progreso_de_guardado(lectura, sistemas, total, total))
    return Resumen(
        lectura.leidas,
        sistemas,
        estaciones,
        mercados,
        precios,
        lectura.descartados,
        lectura.mercados_viejos,
    )


def _progreso_de_guardado(lectura: _Lectura, guardados: int, posicion: int, total: int) -> Progreso:
    return Progreso(GUARDANDO, lectura.leidas, lectura.encontrados, guardados, posicion, total)


def _guardar_sistema(
    conexion: sqlite3.Connection, sistema: volcado.SistemaDeVolcado
) -> tuple[int, int]:
    """(mercados reemplazados, precios guardados)."""
    direccion = sistema.sistema.system_address
    mercado.guardar_sistema(conexion, sistema.sistema, sistema.observado)
    mercados = precios = 0
    for estacion in sistema.estaciones:
        mercado.completar_estacion(
            conexion, estacion.estacion, direccion, estacion.observado or sistema.observado
        )
        if estacion.articulos is None or estacion.observado is None:
            continue
        guardado = mercado.guardar_precios(
            conexion,
            estacion.estacion.market_id,
            estacion.articulos,
            mercado.ORIGEN_SPANSH,
            estacion.observado,
        )
        if guardado:
            mercados += 1
            precios += sum(1 for a in estacion.articulos if a.se_comercia)
    return mercados, precios
