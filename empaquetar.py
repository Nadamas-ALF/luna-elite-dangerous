r"""Construye el .zip de LUNA para publicar (docs/empaquetado.md).

Uso: .venv\Scripts\python.exe empaquetar.py

Comprueba que pytest y ruff están en verde, construye con PyInstaller y `luna.spec`,
añade LEEME.txt, LICENSE y las licencias de terceros, y deja en dist/ el
`LUNA-<versión>-win64.zip` con su SHA-256 al lado.

Está en la raíz y se publica junto con `luna.spec`: la GPL pide que el código publicado
incluya lo necesario para construir el programa (decisión del usuario, 2026-11-18).
"""

from __future__ import annotations

import hashlib
import html.parser
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from core.version import VERSION

RAIZ = Path(__file__).resolve().parent
VENV = RAIZ / ".venv" / "Scripts"
DIST = RAIZ / "dist"
CARPETA = DIST / "LUNA"
# Las licencias salen del mismo .venv con que PyInstaller construye, no del Python que ejecute
# este archivo.
PAQUETES = RAIZ / ".venv" / "Lib" / "site-packages"
# Lo que PyInstaller deja en el ejecutable: la lista de módulos que mete en el PYZ.
INDICE_PYZ = RAIZ / "build" / "luna" / "PYZ-00.toc"
PROPIOS = frozenset({"core", "modules", "main"})

# Cada módulo de terceros que va dentro del ejecutable, con la distribución de pip de la que
# sale su licencia. Si entra uno que no está aquí, no se empaqueta (`modulos_sin_licencia`).
MODULOS = {
    "bottle": "bottle",
    "cffi": "cffi",
    "clr": "pythonnet",
    "clr_loader": "clr_loader",
    "proxy_tools": "proxy_tools",
    "pycparser": "pycparser",
    "pythonnet": "pythonnet",
    "typing_extensions": "typing_extensions",
    "webview": "pywebview",
    "zmq": "pyzmq",
}
DISTRIBUIDOS = tuple(sorted(set(MODULOS.values())))
# Textos que el paquete instalado no trae; se guardan a mano en el repositorio.
EXTERNAS = RAIZ / "licencias-externas"
# Nada de esto puede acabar en la carpeta: son datos del desarrollador o herramientas.
PROHIBIDOS = ("config.json", "luna.db", "luna.log", "tests", "tools", "docs", "SPEC.md")


class FalloAlEmpaquetar(Exception):
    pass


def ejecutar(*orden: str) -> None:
    print("$", " ".join(orden))
    if subprocess.run(orden, cwd=RAIZ).returncode != 0:  # noqa: S603 - rutas de .venv, sin datos de fuera
        raise FalloAlEmpaquetar(f"falló: {' '.join(orden)}")


def comprobar_calidad() -> None:
    ejecutar(str(VENV / "python.exe"), "-m", "pytest", "-q")
    ejecutar(str(VENV / "ruff.exe"), "check", ".")


def construir() -> None:
    shutil.rmtree(RAIZ / "build", ignore_errors=True)
    shutil.rmtree(DIST, ignore_errors=True)
    ejecutar(str(VENV / "pyinstaller.exe"), "--noconfirm", "luna.spec")


def modulos_de_terceros(indice: str) -> set[str]:
    """Los paquetes de primer nivel del PYZ que no son de la biblioteca estándar ni de LUNA."""
    modulos = re.findall(r"\('([A-Za-z0-9_.]+)',\s*'[^']*',\s*'PYMODULE'\)", indice)
    primeros = {modulo.split(".")[0] for modulo in modulos}
    return primeros - set(sys.stdlib_module_names) - PROPIOS


def modulos_sin_licencia(indice: str) -> list[str]:
    return sorted(modulos_de_terceros(indice) - set(MODULOS))


def licencias_de(distribucion: str) -> list[Path]:
    """Los textos de licencia que trae instalados la distribución de pip."""
    info = next(PAQUETES.glob(f"{distribucion}-*.dist-info"), None)
    if info is None:
        raise FalloAlEmpaquetar(f"{distribucion} no está instalado en .venv")
    carpeta = info / "licenses"
    if carpeta.is_dir():
        return [f for f in carpeta.rglob("*") if f.is_file()]
    return [f for f in info.iterdir() if f.name.upper().startswith(("LICENSE", "COPYING"))]


class _Texto(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.partes: list[str] = []

    def handle_data(self, data: str) -> None:
        self.partes.append(data)


def texto_de_html(origen: Path) -> str:
    lector = _Texto()
    lector.feed(origen.read_text(encoding="utf-8"))
    return "".join(lector.partes)


def copiar_licencias_de_python(destino: Path) -> None:
    """La de Python cubre el runtime de Microsoft, bzip2 y libffi; la documentación, OpenSSL,
    expat, zlib y libmpdec. SQLite y xz son de dominio público."""
    base = Path(sys.base_prefix)
    shutil.copy2(base / "LICENSE.txt", destino / "Python.txt")
    incluido = texto_de_html(base / "Doc" / "html" / "license.html")
    (destino / "Python-software-incluido.txt").write_text(incluido, encoding="utf-8")


def copiar_licencias(destino: Path) -> None:
    destino.mkdir(parents=True)
    copiar_licencias_de_python(destino)
    for distribucion in DISTRIBUIDOS:
        archivos = licencias_de(distribucion) + sorted(EXTERNAS.glob(f"{distribucion}*"))
        if not archivos:
            raise FalloAlEmpaquetar(f"falta el texto de la licencia de {distribucion}")
        carpeta = destino / distribucion
        carpeta.mkdir()
        for archivo in archivos:
            shutil.copy2(archivo, carpeta / archivo.name)
    for archivo in sorted((RAIZ / "ui" / "fonts").glob("OFL-*.txt")):
        shutil.copy2(archivo, destino / archivo.name)
    # Las DLL de WebView2 que trae pywebview son de Microsoft y no vienen con su texto.
    webview2 = sorted(EXTERNAS.glob("WebView2*"))
    if not webview2:
        raise FalloAlEmpaquetar("falta el texto de la licencia del SDK de WebView2")
    for archivo in webview2:
        shutil.copy2(archivo, destino / archivo.name)


def completar_carpeta() -> None:
    shutil.copy2(RAIZ / "LEEME.txt", CARPETA / "LEEME.txt")
    shutil.copy2(RAIZ / "LICENSE", CARPETA / "LICENSE")
    copiar_licencias(CARPETA / "licencias")


def prohibidos_en(carpeta: Path) -> list[str]:
    return sorted(
        str(ruta.relative_to(carpeta)) for ruta in carpeta.rglob("*") if ruta.name in PROHIBIDOS
    )


def comprimir(carpeta: Path, destino: Path) -> None:
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as archivo:
        for ruta in sorted(carpeta.rglob("*")):
            if ruta.is_file():
                archivo.write(ruta, Path(carpeta.name) / ruta.relative_to(carpeta))


def escribir_sha256(archivo: Path) -> str:
    resumen = hashlib.sha256(archivo.read_bytes()).hexdigest()
    archivo.with_name(f"{archivo.name}.sha256").write_text(
        f"{resumen}  {archivo.name}\n", encoding="utf-8"
    )
    return resumen


def main() -> int:
    try:
        comprobar_calidad()
        construir()
        sin_licencia = modulos_sin_licencia(INDICE_PYZ.read_text(encoding="utf-8"))
        if sin_licencia:
            raise FalloAlEmpaquetar(f"van en el ejecutable sin licencia asignada: {sin_licencia}")
        completar_carpeta()
        sobran = prohibidos_en(CARPETA)
        if sobran:
            raise FalloAlEmpaquetar(f"la carpeta lleva cosas que no debe: {sobran}")
        zip_ = DIST / f"LUNA-{VERSION}-win64.zip"
        comprimir(CARPETA, zip_)
        resumen = escribir_sha256(zip_)
    except FalloAlEmpaquetar as error:
        print(f"\nNO EMPAQUETADO: {error}")
        return 1
    print(f"\n{zip_.name}: {zip_.stat().st_size / 2**20:.1f} MiB\nSHA-256 {resumen}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
