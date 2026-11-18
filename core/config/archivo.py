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
import time
import uuid
from datetime import datetime
from pathlib import Path

SUFIJO_ROTO = ".roto"
# Una lectura de config.json dura microsegundos: medio segundo en total sobra.
REINTENTOS_DE_REEMPLAZO = 10
ESPERA_ENTRE_REINTENTOS = 0.05

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
        # Con BOM o sin él: PowerShell 5.1 y algunos editores lo añaden al guardar.
        texto = archivo.read_text(encoding="utf-8-sig")
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
        _reemplazar(temporal, archivo)
    except OSError:
        temporal.unlink(missing_ok=True)
        raise


def _reemplazar(temporal: Path, archivo: Path) -> None:
    """En Windows, reemplazar falla mientras otro hilo o programa lee el archivo (E-42)."""
    for _ in range(REINTENTOS_DE_REEMPLAZO - 1):
        try:
            temporal.replace(archivo)
            return
        except PermissionError:
            time.sleep(ESPERA_ENTRE_REINTENTOS)
    temporal.replace(archivo)


def fusionar(archivo: Path, clave: str, valor: object) -> bool:
    """Cambia una clave sin perder el resto de la configuración del usuario.

    Devuelve False cuando no escribió nada, para que quien lo pidió pueda avisar.
    """
    return _cambiar(archivo, lambda datos: datos.__setitem__(clave, valor))


def quitar(archivo: Path, clave: str) -> bool:
    """Borra una clave y deja el resto. True también si ya no estaba."""
    return _cambiar(archivo, lambda datos: datos.pop(clave, None))


def fusionar_campo(archivo: Path, seccion: str, campo: str, valor: object) -> bool:
    """Cambia un campo de una sección conservando los demás campos de esa sección.

    Leer la sección fuera del candado y escribirla entera perdería el cambio de otro hilo
    que guarde a la vez otro campo de la misma sección.
    """
    return fusionar_campos(archivo, seccion, {campo: valor})


def fusionar_campos(archivo: Path, seccion: str, campos: dict) -> bool:
    """Como `fusionar_campo` para varios campos, en una sola escritura: o todos o ninguno."""

    def cambio(datos: dict) -> None:
        actual = datos.get(seccion)
        datos[seccion] = {**(actual if isinstance(actual, dict) else {}), **campos}

    return _cambiar(archivo, cambio)


def _cambiar(archivo: Path, cambio) -> bool:
    with _candado:
        try:
            datos = leer(archivo)
        except ConfigCorrupta:
            if apartar_roto(archivo) is None:
                registro.error("no se pudo apartar %s; no se escribe nada", archivo)
                return False
            datos = {}
        except OSError:
            registro.exception("%s no se pudo leer; no se escribe nada", archivo)
            return False

        cambio(datos)
        _escribir_sin_candado(archivo, datos)
        return True


def apartar_roto(archivo: Path) -> Path | None:
    """Aparta el archivo ilegible con marca de tiempo.

    Con un nombre fijo, el segundo incidente borraría la copia del primero,
    que es justo lo que se intenta no perder.
    """
    # El reloj de Windows avanza a saltos de milisegundos: dos incidentes seguidos
    # pueden recibir la misma marca, y el segundo pisaría la copia del primero.
    marca = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destino = archivo.with_name(f"{archivo.name}{SUFIJO_ROTO}.{marca}")
    repetido = 0
    while destino.exists():
        repetido += 1
        destino = archivo.with_name(f"{archivo.name}{SUFIJO_ROTO}.{marca}-{repetido}")
    try:
        archivo.replace(destino)
    except OSError:
        return None
    registro.warning("%s era ilegible; apartado como %s", archivo, destino.name)
    return destino
