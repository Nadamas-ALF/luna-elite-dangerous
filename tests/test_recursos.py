import sys

import pytest

from core import recursos


def test_la_carpeta_de_recursos_contiene_ui_y_data():
    raiz = recursos.carpeta_de_recursos()
    assert (raiz / "ui" / "index.html").is_file()
    assert (raiz / "data" / "fsd.json").is_file()


def test_con_pyinstaller_los_recursos_salen_del_bundle(tmp_path, monkeypatch):
    """PyInstaller extrae ui/ y data/ en sys._MEIPASS, no junto al .exe.

    Es el fallo que dejaria la ventana sin cargar al empaquetar en la fase 8.
    """
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert recursos.carpeta_de_recursos() == tmp_path


def test_ruta_avisa_de_lo_que_falta(tmp_path, monkeypatch):
    monkeypatch.setattr(recursos, "carpeta_de_recursos", lambda: tmp_path)
    with pytest.raises(FileNotFoundError):
        recursos.ruta("ui", "index.html")
