import json
import re
from html.parser import HTMLParser

import pytest
import webview.util

from core import recursos, textos

RAIZ = recursos.carpeta_de_recursos()
INDEX = RAIZ / "ui" / "index.html"
ES_JSON = RAIZ / "ui" / "i18n" / "es.json"
JS = sorted((RAIZ / "ui" / "js").glob("*.js"))

# Formas de meter HTML ajeno en la página. Con
# --allow-file-access-from-files activo, una de estas con texto de EDDN o del
# journal daría lectura de archivos locales, no solo un destrozo visual.
INYECCION = re.compile(
    r"\b(innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval|new Function|srcdoc)\b"
)

ETIQUETAS_SIN_TEXTO_PROPIO = {"script", "style", "title"}
ETIQUETAS_VACIAS = {"meta", "link", "br", "hr", "img", "input", "source"}
ATRIBUTOS_DE_TEXTO = ("placeholder", "aria-label", "alt", "title")


class TextoSinMarcar(HTMLParser):
    """Busca texto visible que no venga de es.json."""

    def __init__(self) -> None:
        super().__init__()
        self.pila: list[tuple[str, dict]] = []
        self.hallazgos: list[str] = []

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        for nombre in ATRIBUTOS_DE_TEXTO:
            if atributos.get(nombre):
                self.hallazgos.append(f"<{tag} {nombre}=\"{atributos[nombre]}\">")
        if tag not in ETIQUETAS_VACIAS:
            self.pila.append((tag, atributos))

    def handle_endtag(self, tag):
        if self.pila:
            self.pila.pop()

    def handle_data(self, data):
        if not data.strip() or not self.pila:
            return
        etiqueta, atributos = self.pila[-1]
        if etiqueta in ETIQUETAS_SIN_TEXTO_PROPIO:
            return
        if "data-texto" not in atributos:
            self.hallazgos.append(f"<{etiqueta}>{data.strip()[:40]}")


def diccionario() -> dict:
    return json.loads(ES_JSON.read_text(encoding="utf-8"))


def buscar(clave: str):
    return textos.texto(tuple(clave.split(".")), diccionario())


def test_la_url_usa_el_esquema_file():
    url = recursos.url_de_la_interfaz()
    assert url.startswith("file:///")
    assert url.endswith("/ui/index.html")


def test_pywebview_no_considera_local_nuestra_url():
    """La invariante de la 10.1: ningún puerto de escucha.

    `webview.start` arranca su servidor si `is_local_url` dice que la URL es
    local. Si una versión de pywebview cambia ese predicado, esto se pone rojo
    en vez de abrir un puerto en silencio.
    """
    assert not webview.util.is_local_url(recursos.url_de_la_interfaz())


def test_la_url_falla_si_falta_index(tmp_path, monkeypatch):
    monkeypatch.setattr(recursos, "carpeta_de_recursos", lambda: tmp_path)
    with pytest.raises(FileNotFoundError):
        recursos.url_de_la_interfaz()


def test_todas_las_claves_del_html_estan_en_es_json():
    claves = set(re.findall(r'data-texto="([^"]+)"', INDEX.read_text(encoding="utf-8")))
    assert claves, "el HTML deberia marcar sus textos con data-texto"
    faltantes = [clave for clave in claves if not isinstance(buscar(clave), str)]
    assert faltantes == []


def test_el_html_no_lleva_texto_visible_sin_marcar():
    """Al revés que mirar una lista de etiquetas: cualquier texto cuenta."""
    buscador = TextoSinMarcar()
    buscador.feed(INDEX.read_text(encoding="utf-8"))
    assert buscador.hallazgos == []


def test_el_titulo_de_la_ventana_sale_de_es_json():
    assert textos.texto(textos.CLAVE_TITULO, diccionario()) == "LUNA"


def test_hay_mensaje_para_cada_motivo_de_la_carpeta_de_datos():
    from core.config import rutas

    codigos = [
        rutas.MOTIVO_SIN_ESCRITURA,
        rutas.MOTIVO_UNIDAD_DE_RED,
        rutas.MOTIVO_CARPETA_SINCRONIZADA,
        rutas.AVISO_UNIDAD_EXTRAIBLE,
        rutas.AVISO_RESPALDO_TAMBIEN_FALLA,
    ]
    sin_texto = [codigo for codigo in codigos if not isinstance(buscar(f"datos.{codigo}"), str)]
    assert sin_texto == []


def test_el_mensaje_de_error_de_arranque_acepta_el_detalle():
    plantilla = textos.texto(textos.CLAVE_ERROR_ARRANQUE, diccionario())
    assert "{error}" in plantilla
    assert plantilla.format(error="prueba").endswith("prueba")


def test_los_textos_no_usan_raya():
    """La raya (—) es un tic de la escritura automática."""
    assert "—" not in ES_JSON.read_text(encoding="utf-8")


def sin_comentarios(codigo: str) -> str:
    """Los comentarios hablan de innerHTML precisamente para prohibirlo."""
    sin_bloques = re.sub(r"/\*.*?\*/", "", codigo, flags=re.S)
    return re.sub(r"^\s*//.*$", "", sin_bloques, flags=re.M)


def test_el_js_no_inyecta_html():
    assert JS, "no se encontro ningun modulo de interfaz"
    culpables = [
        f"{ruta.name}: {coincidencia}"
        for ruta in JS
        for coincidencia in INYECCION.findall(sin_comentarios(ruta.read_text(encoding="utf-8")))
    ]
    assert culpables == []


def test_la_pagina_declara_una_csp():
    html = INDEX.read_text(encoding="utf-8")
    assert 'http-equiv="Content-Security-Policy"' in html
    assert "default-src 'none'" in html


def test_el_layout_no_fija_anchos_en_pixeles():
    """La sección 9.1 exige unidades relativas para que nada se corte."""
    css = (RAIZ / "ui" / "css" / "base.css").read_text(encoding="utf-8")
    propiedades = re.findall(
        r"^\s*(width|min-width|max-width|flex-basis|grid-template-columns)\s*:\s*([^;]+);",
        css,
        re.M,
    )
    en_pixeles = [f"{nombre}: {valor}" for nombre, valor in propiedades if "px" in valor]
    assert en_pixeles == []
