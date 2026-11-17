"""`plataforma.copiar_al_portapapeles`: la única prueba que lee el portapapeles, y solo aquí."""

import ctypes
import sys

import pytest

from core import plataforma

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="el portapapeles es de Windows")


def _leer() -> str | None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    if not user32.OpenClipboard(None):
        return None
    try:
        memoria = user32.GetClipboardData(plataforma.CF_UNICODETEXT)
        if not memoria:
            return None
        puntero = kernel32.GlobalLock(memoria)
        try:
            return ctypes.wstring_at(puntero)
        finally:
            kernel32.GlobalUnlock(memoria)
    finally:
        user32.CloseClipboard()


@pytest.fixture
def conservar_el_portapapeles():
    """Lo que había se vuelve a poner al terminar: la prueba no deja huella en el del usuario."""
    antes = _leer()
    yield
    if antes is not None:
        plataforma.copiar_al_portapapeles(antes)


def test_lo_copiado_se_lee_igual_con_tildes_y_simbolos(conservar_el_portapapeles):
    assert plataforma.copiar_al_portapapeles("Col 285 Sector HB-C b14-2 · Orishpucho ñ")

    assert _leer() == "Col 285 Sector HB-C b14-2 · Orishpucho ñ"


def test_copiar_otra_vez_sustituye_lo_anterior(conservar_el_portapapeles):
    plataforma.copiar_al_portapapeles("primero")
    plataforma.copiar_al_portapapeles("segundo")

    assert _leer() == "segundo"


def test_con_el_portapapeles_ocupado_se_rinde_tras_tres_intentos(monkeypatch):
    intentos = []

    class Ocupado:
        @staticmethod
        def OpenClipboard(_):  # noqa: N802 - nombre de la API de Windows
            intentos.append(1)
            return 0

    monkeypatch.setattr(plataforma, "ESPERA_DE_PORTAPAPELES", 0.0)

    assert plataforma._abrir_portapapeles(Ocupado) is False
    assert len(intentos) == plataforma.INTENTOS_DE_PORTAPAPELES
