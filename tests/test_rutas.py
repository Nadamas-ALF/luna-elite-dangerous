import sys
from pathlib import Path

import pytest

from core.config import rutas


@pytest.fixture(autouse=True)
def sin_variables_del_entorno(monkeypatch):
    """Que el resultado no dependa de la maquina donde corren las pruebas."""
    monkeypatch.delenv(rutas.VARIABLE_DE_DESARROLLO, raising=False)
    for nombre in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        monkeypatch.delenv(nombre, raising=False)
    monkeypatch.setattr(rutas, "es_unidad_extraible", lambda carpeta: False)
    monkeypatch.setattr(rutas, "es_unidad_de_red", lambda carpeta: False)


def test_carpeta_del_programa_contiene_el_proyecto():
    raiz = rutas.carpeta_del_programa()
    assert (raiz / "main.py").is_file()
    assert (raiz / "ui" / "index.html").is_file()


def test_portable_cuando_se_puede_escribir(tmp_path):
    ubicacion = rutas.resolver(programa=tmp_path, respaldo=tmp_path / "respaldo")
    assert ubicacion.portable
    assert ubicacion.carpeta == tmp_path
    assert ubicacion.motivo is None
    assert ubicacion.avisos == ()


def test_la_variable_de_desarrollo_manda(tmp_path, monkeypatch):
    """Para que al desarrollar la base de datos no caiga dentro del repositorio."""
    elegida = tmp_path / "datos"
    monkeypatch.setenv(rutas.VARIABLE_DE_DESARROLLO, str(elegida))

    ubicacion = rutas.resolver(programa=tmp_path, respaldo=tmp_path / "respaldo")

    assert ubicacion.carpeta == elegida
    assert not ubicacion.portable


def test_respaldo_cuando_no_se_puede_escribir(tmp_path, monkeypatch):
    monkeypatch.setattr(rutas, "se_puede_escribir", lambda carpeta: carpeta != tmp_path)
    respaldo = tmp_path / "respaldo"

    ubicacion = rutas.resolver(programa=tmp_path, respaldo=respaldo)

    assert not ubicacion.portable
    assert ubicacion.carpeta == respaldo
    assert ubicacion.motivo == rutas.MOTIVO_SIN_ESCRITURA
    assert ubicacion.avisos == ()


def test_respaldo_en_unidad_de_red(tmp_path, monkeypatch):
    monkeypatch.setattr(rutas, "es_unidad_de_red", lambda carpeta: carpeta == tmp_path)
    respaldo = tmp_path / "respaldo"

    ubicacion = rutas.resolver(programa=tmp_path, respaldo=respaldo)

    assert ubicacion.motivo == rutas.MOTIVO_UNIDAD_DE_RED
    assert ubicacion.carpeta == respaldo


def test_respaldo_dentro_de_onedrive(tmp_path, monkeypatch):
    monkeypatch.setenv("OneDrive", str(tmp_path))
    carpeta = tmp_path / "LUNA"
    carpeta.mkdir()

    ubicacion = rutas.resolver(programa=carpeta, respaldo=tmp_path / "respaldo")

    assert ubicacion.motivo == rutas.MOTIVO_CARPETA_SINCRONIZADA


def test_avisa_si_el_respaldo_tampoco_sirve(tmp_path, monkeypatch):
    """%LOCALAPPDATA% redirigido a red deja a SQLite sin memoria compartida."""
    monkeypatch.setattr(rutas, "es_unidad_de_red", lambda carpeta: True)

    ubicacion = rutas.resolver(programa=tmp_path, respaldo=tmp_path / "respaldo")

    assert ubicacion.motivo == rutas.MOTIVO_UNIDAD_DE_RED
    assert ubicacion.avisos == (rutas.AVISO_RESPALDO_TAMBIEN_FALLA,)


def test_ruta_unc_es_unidad_de_red(monkeypatch):
    monkeypatch.undo()
    assert rutas.es_unidad_de_red(Path(r"\\servidor\compartido\LUNA"))


def test_aviso_en_unidad_extraible(tmp_path, monkeypatch):
    monkeypatch.setattr(rutas, "es_unidad_extraible", lambda carpeta: True)

    ubicacion = rutas.resolver(programa=tmp_path, respaldo=tmp_path / "respaldo")

    assert ubicacion.portable
    assert ubicacion.avisos == (rutas.AVISO_UNIDAD_EXTRAIBLE,)


def test_no_se_puede_escribir_donde_el_padre_es_un_archivo(tmp_path):
    archivo = tmp_path / "archivo"
    archivo.write_text("x", encoding="utf-8")
    assert not rutas.se_puede_escribir(archivo / "subcarpeta")


def test_se_puede_escribir_no_deja_restos(tmp_path):
    assert rutas.se_puede_escribir(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_los_datos_del_usuario_y_los_recursos_no_comparten_raiz(tmp_path, monkeypatch):
    """La invariante que protege el empaquetado de la fase 8.

    Sin congelar, las dos carpetas coinciden y confundirlas es invisible. Con
    PyInstaller, los datos del usuario van junto al .exe y los recursos dentro
    del bundle; usar el modulo equivocado se veria como "la ventana no carga"
    o "la base de datos se borra al cerrar".
    """
    from core import recursos

    exe = tmp_path / "instalado" / "LUNA.exe"
    exe.parent.mkdir()
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)

    assert rutas.carpeta_del_programa() == exe.parent
    assert recursos.carpeta_de_recursos() == bundle
