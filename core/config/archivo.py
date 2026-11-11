"""Lectura y escritura de config.json.

Hay tres resultados distintos al leer, y confundirlos cuesta la configuración
del usuario: no existe (primer arranque), no se puede leer (el antivirus o una
copia de seguridad lo tienen abierto un instante) y es ilegible (JSON roto). En
el segundo caso no se escribe nada; en el tercero el archivo se aparta en lugar
de sobrescribirse.

El candado hace falta porque desde la fase 1 escriben los hilos de `js_api`
mientras la ventana guarda su geometría al cerrar. Entre procesos no protege,
así que el temporal lleva un nombre único.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

SUFIJO_ROTO = ".roto"

_candado = threading.Lock()
registro = logging.getLogger("luna.config")


class ConfigCorrupta(ValueError):
    """El archivo existe y se lee, pero su contenido no es un objeto JSON."""


def leer(archivo: Path) -> dict:
    """Contenido del archivo, o {} si no existe.

    Lanza `OSError` si no se puede leer y `ConfigCorrupta` si no se puede
    interpretar, para que quien escriba pueda distinguir los dos casos.
    """
    try:
        texto = archivo.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except UnicodeDecodeError as error:
        # Guardado con otra codificación: es contenido inservible, no un
        # problema de acceso al archivo.
        raise ConfigCorrupta(str(archivo)) from error

    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as error:
        raise ConfigCorrupta(str(archivo)) from error
    if not isinstance(datos, dict):
        raise ConfigCorrupta(f"{archivo}: la raiz no es un objeto")
    return datos


def leer_o_vacio(archivo: Path) -> dict:
    """Para quien solo lee: cualquier problema se trata como vacío."""
    try:
        return leer(archivo)
    except (OSError, ConfigCorrupta, UnicodeDecodeError):
        registro.warning("no se pudo leer %s; se usan los valores por defecto", archivo)
        return {}


def escribir(archivo: Path, datos: dict) -> None:
    with _candado:
        _escribir_sin_candado(archivo, datos)


def _escribir_sin_candado(archivo: Path, datos: dict) -> None:
    archivo.parent.mkdir(parents=True, exist_ok=True)
    # Nombre único: dos LUNA abiertos a la vez compartirían el temporal y se
    # intercalarían dentro del mismo archivo.
    temporal = archivo.with_name(f"{archivo.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    texto = json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True)
    try:
        with temporal.open("w", encoding="utf-8") as destino:
            destino.write(texto)
            destino.flush()
            # Sin fsync, un corte de luz puede dejar el archivo a cero bytes.
            os.fsync(destino.fileno())
        temporal.replace(archivo)
    except OSError:
        temporal.unlink(missing_ok=True)
        raise


def fusionar(archivo: Path, clave: str, valor: object) -> None:
    """Cambia una clave sin perder el resto de la configuración del usuario."""
    with _candado:
        try:
            datos = leer(archivo)
        except ConfigCorrupta:
            if apartar_roto(archivo) is None:
                registro.error("no se pudo apartar %s; no se escribe nada", archivo)
                return
            datos = {}
        except OSError:
            registro.exception("%s no se pudo leer; no se escribe nada", archivo)
            return

        datos[clave] = valor
        _escribir_sin_candado(archivo, datos)


def apartar_roto(archivo: Path) -> Path | None:
    """Aparta el archivo ilegible con marca de tiempo.

    Con un nombre fijo, el segundo incidente borraría la copia del primero,
    que es justo lo que se intenta no perder.
    """
    # Con microsegundos: dos incidentes en el mismo segundo no se pisan.
    marca = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destino = archivo.with_name(f"{archivo.name}{SUFIJO_ROTO}.{marca}")
    try:
        archivo.replace(destino)
    except OSError:
        return None
    registro.warning("%s era ilegible; apartado como %s", archivo, destino.name)
    return destino
