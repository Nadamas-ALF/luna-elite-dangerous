import hashlib
import zipfile
from pathlib import Path

import empaquetar


def test_detecta_datos_del_desarrollador_dentro_de_la_carpeta(tmp_path):
    (tmp_path / "_internal").mkdir()
    (tmp_path / "_internal" / "config.json").write_text("{}")
    (tmp_path / "LUNA.exe").write_bytes(b"")

    assert empaquetar.prohibidos_en(tmp_path) == [str(Path("_internal") / "config.json")]


def test_una_carpeta_limpia_no_tiene_prohibidos(tmp_path):
    (tmp_path / "LUNA.exe").write_bytes(b"")
    (tmp_path / "LEEME.txt").write_text("hola")

    assert empaquetar.prohibidos_en(tmp_path) == []


def test_el_zip_lleva_la_carpeta_luna_en_la_raiz(tmp_path):
    carpeta = tmp_path / "LUNA"
    (carpeta / "_internal").mkdir(parents=True)
    (carpeta / "LUNA.exe").write_bytes(b"exe")
    (carpeta / "_internal" / "a.dll").write_bytes(b"dll")
    destino = tmp_path / "LUNA.zip"

    empaquetar.comprimir(carpeta, destino)

    with zipfile.ZipFile(destino) as archivo:
        assert sorted(archivo.namelist()) == ["LUNA/LUNA.exe", "LUNA/_internal/a.dll"]


def test_el_sha256_se_escribe_al_lado_con_el_formato_de_sha256sum(tmp_path):
    archivo = tmp_path / "LUNA-1.0.0-win64.zip"
    archivo.write_bytes(b"contenido")

    resumen = empaquetar.escribir_sha256(archivo)

    assert resumen == hashlib.sha256(b"contenido").hexdigest()
    linea = (tmp_path / "LUNA-1.0.0-win64.zip.sha256").read_text(encoding="utf-8")
    assert linea == f"{resumen}  LUNA-1.0.0-win64.zip\n"


def test_cada_paquete_distribuido_esta_instalado():
    for distribucion in empaquetar.DISTRIBUIDOS:
        empaquetar.licencias_de(distribucion)


def test_los_que_traen_su_licencia_la_encuentran():
    assert empaquetar.licencias_de("pyzmq")
    assert empaquetar.licencias_de("pywebview")


INDICE_DE_PRUEBA = """('PYZ-00.pyz',
 [('json', 'C:\\\\x\\\\json\\\\__init__.py', 'PYMODULE'),
  ('core.version', 'D:\\\\Luna\\\\core\\\\version.py', 'PYMODULE'),
  ('webview.util', 'D:\\\\x\\\\util.py', 'PYMODULE'),
  ('setuptools._vendor.jaraco', 'D:\\\\x\\\\jaraco.py', 'PYMODULE')])"""


def test_un_modulo_de_terceros_sin_licencia_asignada_se_detecta():
    assert empaquetar.modulos_de_terceros(INDICE_DE_PRUEBA) == {"webview", "setuptools"}
    assert empaquetar.modulos_sin_licencia(INDICE_DE_PRUEBA) == ["setuptools"]


def test_las_licencias_salen_del_venv_del_proyecto():
    assert empaquetar.PAQUETES == empaquetar.RAIZ / ".venv" / "Lib" / "site-packages"
