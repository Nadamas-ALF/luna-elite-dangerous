# Receta de PyInstaller para LUNA (docs/empaquetado.md).
# Se construye con empaquetar.py, que además comprueba las pruebas y arma el .zip.
#
# Modo carpeta (no un solo .exe): un solo .exe se descomprime en cada arranque
# y es lo que más marcan los antivirus. Sin UPX por lo mismo.

import sys
from pathlib import Path

from PyInstaller.utils.win32 import versioninfo as vi

RAIZ = Path(SPECPATH)
sys.path.insert(0, str(RAIZ))
from core.version import VERSION  # noqa: E402

NUMEROS = (*(int(n) for n in VERSION.split(".")), 0)
DATOS_DE_VERSION = vi.VSVersionInfo(
    ffi=vi.FixedFileInfo(filevers=NUMEROS, prodvers=NUMEROS),
    kids=[
        vi.StringFileInfo([
            vi.StringTable("0C0A04B0", [
                vi.StringStruct("ProductName", "LUNA"),
                vi.StringStruct("FileDescription", "LUNA: rutas de comercio para Elite Dangerous"),
                vi.StringStruct("FileVersion", VERSION),
                vi.StringStruct("ProductVersion", VERSION),
                vi.StringStruct("OriginalFilename", "LUNA.exe"),
                vi.StringStruct("LegalCopyright", "GPLv3"),
            ])
        ]),
        vi.VarFileInfo([vi.VarStruct("Translation", [0x0C0A, 1200])]),
    ],
)

a = Analysis(
    ["main.py"],
    datas=[("ui", "ui"), ("data", "data")],
    # setuptools y packaging son de desarrollo (los trae PyInstaller) y solo los pide
    # cffi._shimmed_dist_utils, que es para compilar: en ejecución no se usan.
    excludes=[
        "pytest", "_pytest", "ruff", "PyInstaller",
        "setuptools", "_distutils_hack", "pkg_resources", "packaging",
    ],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LUNA",
    icon=str(RAIZ / "ui" / "assets" / "brandings" / "LUNA.ico"),
    version=DATOS_DE_VERSION,
    console=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="LUNA",
    upx=False,
)
