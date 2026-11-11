r"""Decide dónde escribe LUNA sus datos.

LUNA es portable: config.json, la base de datos y los registros viven en la
carpeta del programa. Si esa carpeta no sirve, se usa %LOCALAPPDATA%\LUNA y se
informa del motivo en la pantalla Estado, nunca en silencio.

Los motivos y avisos son códigos, no frases: los textos están en
`ui/i18n/es.json`.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

NOMBRE_APP = "LUNA"
VARIABLE_DE_DESARROLLO = "LUNA_DATOS"

MOTIVO_SIN_ESCRITURA = "sin_permiso_de_escritura"
MOTIVO_UNIDAD_DE_RED = "unidad_de_red"
MOTIVO_CARPETA_SINCRONIZADA = "carpeta_sincronizada"
AVISO_UNIDAD_EXTRAIBLE = "unidad_extraible"
AVISO_RESPALDO_TAMBIEN_FALLA = "respaldo_tambien_falla"

_DRIVE_REMOVABLE = 2
_DRIVE_REMOTE = 4


@dataclass(frozen=True)
class Ubicacion:
    carpeta: Path
    portable: bool
    motivo: str | None = None
    avisos: tuple[str, ...] = ()


def carpeta_del_programa() -> Path:
    """Carpeta del .exe, o la raíz del repositorio cuando se ejecuta el código.

    Con PyInstaller, `sys.executable` es el .exe del usuario; `sys._MEIPASS`
    sería la carpeta temporal de extracción, que se borra al cerrar.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def carpeta_de_respaldo() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / NOMBRE_APP


def se_puede_escribir(carpeta: Path) -> bool:
    prueba = carpeta / f".escritura-{uuid.uuid4().hex}.tmp"
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        prueba.write_bytes(b"")
    except OSError:
        return False
    finally:
        with contextlib.suppress(OSError):
            prueba.unlink(missing_ok=True)
    return True


def tipo_de_unidad(carpeta: Path) -> int | None:
    """Valor de GetDriveTypeW, o None si no se puede determinar."""
    unidad = os.path.splitdrive(str(carpeta))[0]
    if not unidad:
        return None
    try:
        return int(ctypes.windll.kernel32.GetDriveTypeW(f"{unidad}\\"))
    except (AttributeError, OSError):
        return None


def es_unidad_de_red(carpeta: Path) -> bool:
    """SQLite en modo WAL necesita memoria compartida, que una unidad de red no da."""
    if str(carpeta).startswith("\\\\"):
        return True
    return tipo_de_unidad(carpeta) == _DRIVE_REMOTE


def es_unidad_extraible(carpeta: Path) -> bool:
    """En un USB la app funciona, pero la importación de Spansh es muy lenta."""
    return tipo_de_unidad(carpeta) == _DRIVE_REMOVABLE


def esta_sincronizada(carpeta: Path) -> bool:
    """OneDrive subiría la base de datos entera cada vez que cambia un precio."""
    variables = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")
    for nombre in variables:
        raiz = os.environ.get(nombre)
        if not raiz:
            continue
        try:
            carpeta.relative_to(Path(raiz))
        except ValueError:
            continue
        return True
    return False


def motivo_para_descartar(carpeta: Path) -> str | None:
    if es_unidad_de_red(carpeta):
        return MOTIVO_UNIDAD_DE_RED
    if esta_sincronizada(carpeta):
        return MOTIVO_CARPETA_SINCRONIZADA
    if not se_puede_escribir(carpeta):
        return MOTIVO_SIN_ESCRITURA
    return None


def resolver(programa: Path | None = None, respaldo: Path | None = None) -> Ubicacion:
    """Carpeta de datos: la del programa, o la de respaldo con el motivo.

    La variable LUNA_DATOS la impone, para que al desarrollar no caigan
    config.json ni la base de datos dentro del repositorio.
    """
    elegida = os.environ.get(VARIABLE_DE_DESARROLLO)
    if elegida:
        return Ubicacion(Path(elegida), portable=False)

    programa = programa or carpeta_del_programa()
    respaldo = respaldo or carpeta_de_respaldo()

    motivo = motivo_para_descartar(programa)
    if motivo is None:
        avisos = (AVISO_UNIDAD_EXTRAIBLE,) if es_unidad_extraible(programa) else ()
        return Ubicacion(programa, portable=True, avisos=avisos)

    # El respaldo puede ser igual de malo: %LOCALAPPDATA% redirigido a un
    # recurso de red deja a SQLite en WAL sin memoria compartida.
    avisos = () if motivo_para_descartar(respaldo) is None else (AVISO_RESPALDO_TAMBIEN_FALLA,)
    return Ubicacion(respaldo, portable=False, motivo=motivo, avisos=avisos)


def archivo_de_config(ubicacion: Ubicacion) -> Path:
    return ubicacion.carpeta / "config.json"
