import json

import pytest

from core.config import archivo


def test_leer_un_archivo_que_no_existe_da_vacio(tmp_path):
    assert archivo.leer(tmp_path / "config.json") == {}


def test_leer_un_archivo_ilegible_avisa(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{ falta una llave", encoding="utf-8")
    with pytest.raises(archivo.ConfigCorrupta):
        archivo.leer(config)


def test_leer_rechaza_un_json_que_no_es_objeto(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(archivo.ConfigCorrupta):
        archivo.leer(config)


def test_leer_rechaza_otra_codificacion(tmp_path):
    """Un es.json o config.json guardado con el Bloc de notas de siempre."""
    config = tmp_path / "config.json"
    config.write_bytes('{"nave": "Pantera Clíper"}'.encode("cp1252"))
    with pytest.raises(archivo.ConfigCorrupta):
        archivo.leer(config)


def test_fusionar_aparta_el_archivo_danado_en_vez_de_borrarlo(tmp_path):
    """El fallo que importa: perder radio de la esfera y umbrales en silencio."""
    config = tmp_path / "config.json"
    config.write_text('{"radio_esfera": 150, "umbral": 2000,', encoding="utf-8")

    archivo.fusionar(config, "ventana", {"ancho": 1280})

    apartados = list(tmp_path.glob("config.json.roto*"))
    assert len(apartados) == 1, "el archivo danado debe conservarse para recuperarlo"
    assert "radio_esfera" in apartados[0].read_text(encoding="utf-8")
    assert archivo.leer(config) == {"ventana": {"ancho": 1280}}


def test_apartar_dos_veces_no_pisa_la_primera_copia(tmp_path):
    config = tmp_path / "config.json"

    config.write_text('{"primero": 1,', encoding="utf-8")
    primero = archivo.apartar_roto(config)
    config.write_text('{"segundo": 2,', encoding="utf-8")
    segundo = archivo.apartar_roto(config)

    assert primero != segundo
    assert "primero" in primero.read_text(encoding="utf-8")
    assert "segundo" in segundo.read_text(encoding="utf-8")


def test_fusionar_no_escribe_si_no_se_puede_leer(tmp_path, monkeypatch):
    """El antivirus o una copia de seguridad pueden tener el archivo abierto.

    Antes, un PermissionError de un instante se trataba como corrupcion y
    dejaba un config.json con una sola clave.
    """
    config = tmp_path / "config.json"
    archivo.escribir(config, {"radio_esfera": 150, "umbral": 2000})

    def no_se_puede_leer(self, *args, **kwargs):
        raise PermissionError(str(self))

    monkeypatch.setattr("pathlib.Path.read_text", no_se_puede_leer)
    archivo.fusionar(config, "ventana", {"ancho": 1280})
    monkeypatch.undo()

    assert archivo.leer(config) == {"radio_esfera": 150, "umbral": 2000}
    assert list(tmp_path.glob("*.tmp")) == []


def test_fusionar_conserva_el_resto_de_claves(tmp_path):
    config = tmp_path / "config.json"
    archivo.escribir(config, {"radio_esfera": 150})

    archivo.fusionar(config, "ventana", {"ancho": 1280})

    assert archivo.leer(config) == {"radio_esfera": 150, "ventana": {"ancho": 1280}}


def test_el_temporal_lleva_un_nombre_unico(tmp_path, monkeypatch):
    """Dos LUNA abiertos compartirian el temporal e intercalarian sus escrituras."""
    nombres = []
    original = archivo.Path.open

    def espiar(self, *args, **kwargs):
        if self.suffix == ".tmp":
            nombres.append(self.name)
        return original(self, *args, **kwargs)

    monkeypatch.setattr("pathlib.Path.open", espiar)
    archivo.escribir(tmp_path / "config.json", {"a": 1})
    archivo.escribir(tmp_path / "config.json", {"a": 2})
    monkeypatch.undo()

    assert len(nombres) == 2
    assert nombres[0] != nombres[1]


def test_escribir_no_deja_temporales(tmp_path):
    archivo.escribir(tmp_path / "config.json", {"a": 1})
    assert list(tmp_path.glob("*.tmp")) == []


def test_escribir_crea_la_carpeta(tmp_path):
    config = tmp_path / "nueva" / "config.json"
    archivo.escribir(config, {"a": 1})
    assert json.loads(config.read_text(encoding="utf-8")) == {"a": 1}


def test_config_json_se_puede_editar_a_mano(tmp_path):
    """Los acentos se guardan sin escapar para que el archivo sea legible."""
    config = tmp_path / "config.json"
    archivo.escribir(config, {"nave": "Pantera Clíper"})
    assert "Clíper" in config.read_text(encoding="utf-8")
    assert archivo.leer(config)["nave"] == "Pantera Clíper"


def test_leer_o_vacio_tolera_cualquier_problema(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{ roto", encoding="utf-8")
    assert archivo.leer_o_vacio(config) == {}
    assert archivo.leer_o_vacio(tmp_path / "no-existe.json") == {}


def test_fusionar_dice_si_escribio(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    assert archivo.fusionar(config, "ventana", {"ancho": 1}) is True

    def ocupado(self, *args, **kwargs):
        raise PermissionError("abierto por otro programa")

    monkeypatch.setattr(type(config), "read_text", ocupado)
    assert archivo.fusionar(config, "ventana", {"ancho": 2}) is False


def test_fusionar_campos_escribe_todos_a_la_vez_y_conserva_los_demas(tmp_path):
    ruta = tmp_path / "config.json"
    archivo.fusionar(ruta, "seccion", {"a": 1, "otro": 9})

    assert archivo.fusionar_campos(ruta, "seccion", {"a": 2, "b": 3})

    assert archivo.leer(ruta)["seccion"] == {"a": 2, "otro": 9, "b": 3}


def test_guardar_mientras_otro_hilo_lee_espera_y_guarda(tmp_path):
    """En Windows, reemplazar un archivo abierto por otro falla con acceso denegado (E-42)."""
    import threading

    config = tmp_path / "config.json"
    archivo.escribir(config, {"a": 1})
    abierto = config.open(encoding="utf-8")
    threading.Timer(0.2, abierto.close).start()

    assert archivo.fusionar(config, "b", 2)
    assert archivo.leer(config) == {"a": 1, "b": 2}
    assert list(tmp_path.glob("*.tmp")) == []


def test_si_sigue_bloqueado_se_rinde_sin_dejar_temporales(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    archivo.escribir(config, {"a": 1})
    monkeypatch.setattr(archivo, "ESPERA_ENTRE_REINTENTOS", 0)
    with config.open(encoding="utf-8"), pytest.raises(PermissionError):
        archivo.escribir(config, {"a": 2})

    assert archivo.leer(config) == {"a": 1}
    assert list(tmp_path.glob("*.tmp")) == []


def test_un_config_guardado_con_bom_se_lee_y_no_se_aparta(tmp_path):
    """PowerShell 5.1 (`Set-Content -Encoding UTF8`) y algunos editores añaden el BOM."""
    config = tmp_path / "config.json"
    config.write_bytes(b"\xef\xbb\xbf" + b'{"esfera": {"radio": 250}}')

    assert archivo.leer(config) == {"esfera": {"radio": 250}}
    assert archivo.fusionar(config, "otra", 1)
    assert archivo.leer(config) == {"esfera": {"radio": 250}, "otra": 1}
    assert list(tmp_path.glob("config.json.roto*")) == []
