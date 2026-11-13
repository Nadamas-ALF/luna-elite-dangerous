import json
import re
from html.parser import HTMLParser

import pytest
import webview.util

from core import datos, recursos, textos
from core.db import espacio
from core.eddn import suscriptor
from core.spansh import cambio, descarga, gestor, importacion
from core.state import vista

RAIZ = recursos.carpeta_de_recursos()
INDEX = RAIZ / "ui" / "index.html"
ES_JSON = RAIZ / "ui" / "i18n" / "es.json"
JS = sorted((RAIZ / "ui" / "js").glob("*.js"))
ESTADOS_EDDN = (
    suscriptor.DESACTIVADO,
    suscriptor.CONECTANDO,
    suscriptor.CONECTADO,
    suscriptor.SIN_DATOS,
    suscriptor.REINTENTANDO,
)
FASES_DEL_GESTOR = (
    gestor.INACTIVA,
    gestor.DESCARGANDO,
    gestor.PAUSADA,
    gestor.IMPORTANDO,
    gestor.ERROR,
)
ESTADOS_DE_SPANSH = (
    vista.SPANSH_SIN_DESCARGA,
    vista.SPANSH_COMPLETA,
    gestor.DESCARGANDO,
    gestor.PAUSADA,
    "importando_leyendo",
    "importando_guardando",
    gestor.ERROR,
)
# El gestor compone el código con el prefijo de la etapa y el motivo del error.
ERRORES_DEL_GESTOR = (
    *(
        f"descarga_{motivo}"
        for motivo in (
            descarga.MOTIVO_URL,
            descarga.MOTIVO_RED,
            descarga.MOTIVO_HTTP,
            descarga.MOTIVO_CORTADA,
            descarga.MOTIVO_ESPACIO,
            descarga.MOTIVO_FORMATO,
            descarga.MOTIVO_DESTINO,
        )
    ),
    *(
        f"importacion_{motivo}"
        for motivo in (
            importacion.MOTIVO_ARCHIVO,
            importacion.MOTIVO_FORMATO,
            importacion.MOTIVO_BASE,
            importacion.MOTIVO_DESTINO,
        )
    ),
    "interno",
)
ERRORES_DE_DATOS = (
    cambio.MOTIVO_DESCONOCIDO,
    cambio.MOTIVO_AMBIGUO,
    cambio.MOTIVO_NOMBRE,
    cambio.MOTIVO_RADIO,
    datos.ERROR_OCUPADO,
    datos.ERROR_SIN_BASE,
    datos.ERROR_NO_GUARDADO,
    datos.ERROR_DIAS,
    datos.ERROR_PARAMETRO,
    "no_disponible",
)

# Formas de meter HTML ajeno en la página. Con
# --allow-file-access-from-files activo, una de estas con texto de EDDN o del
# journal daría lectura de archivos locales, no solo un destrozo visual.
INYECCION = re.compile(
    r"\b(innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval|new Function|srcdoc)\b"
)

ETIQUETAS_SIN_TEXTO_PROPIO = {"script", "style", "title"}
ETIQUETAS_VACIAS = {"meta", "link", "br", "hr", "img", "input", "source", "path", "circle"}
ATRIBUTOS_DE_TEXTO = ("placeholder", "aria-label", "alt", "title")
# Los que el HTML puede traducir con data-i18n-<nombre> (ui/js/i18n.js).
ATRIBUTOS_TRADUCIBLES = {"placeholder", "aria-label", "title"}


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
                self.hallazgos.append(f'<{tag} {nombre}="{atributos[nombre]}">')
        if tag not in ETIQUETAS_VACIAS:
            self.pila.append((tag, atributos))

    def handle_endtag(self, tag):
        if self.pila and tag not in ETIQUETAS_VACIAS:
            self.pila.pop()

    def handle_data(self, data):
        if not data.strip() or not self.pila:
            return
        etiqueta, atributos = self.pila[-1]
        if etiqueta in ETIQUETAS_SIN_TEXTO_PROPIO:
            return
        if "data-i18n" not in atributos:
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
    html = INDEX.read_text(encoding="utf-8")
    claves = set(re.findall(r'data-i18n(?:-[a-z-]+)?="([^"]+)"', html))
    assert claves, "el HTML deberia marcar sus textos con data-i18n"
    faltantes = [clave for clave in claves if not isinstance(buscar(clave), str)]
    assert faltantes == []


def test_el_html_solo_traduce_atributos_de_la_lista_permitida():
    html = INDEX.read_text(encoding="utf-8")
    usados = set(re.findall(r"data-i18n-([a-z-]+)=", html))
    assert usados <= ATRIBUTOS_TRADUCIBLES
    lista_del_js = re.search(r"new Set\(\[(.*?)\]\)", (RAIZ / "ui/js/i18n.js").read_text("utf-8"))
    assert set(re.findall(r"'([^']+)'", lista_del_js.group(1))) == ATRIBUTOS_TRADUCIBLES


def test_las_claves_literales_del_js_estan_en_es_json():
    literales = set()
    for ruta in JS:
        literales |= set(re.findall(r"texto\(\s*'([^'$]+)'", ruta.read_text(encoding="utf-8")))
    assert literales, "el JS deberia pedir sus textos con texto('clave')"
    assert [clave for clave in literales if not isinstance(buscar(clave), str)] == []


def test_hay_texto_para_cada_codigo_que_el_nucleo_puede_enviar():
    """El JS compone estas claves (`motivos.${codigo}`), así que no se ven arriba."""
    from core.config import rutas
    from core.state import estado, vista

    motivos = [
        vista.MOTIVO_SIN_JOURNAL,
        vista.MOTIVO_SIN_COMANDANTE,
        vista.MOTIVO_SIN_SALDO,
        vista.MOTIVO_SIN_LOADOUT,
        vista.MOTIVO_SIN_UBICACION,
        vista.MOTIVO_SIN_COMBUSTIBLE,
        vista.MOTIVO_SIN_LECTURA,
        vista.MOTIVO_NAVE_NO_CONOCIDA,
        estado.ERROR_LOADOUT,
        estado.ERROR_PROPULSOR,
        "sin_coordenadas",
    ]
    claves = [f"motivos.{codigo}" for codigo in motivos]
    claves += [f"datos.{codigo}" for codigo in (vista.AVISO_SIN_BASE, rutas.MOTIVO_SIN_ESCRITURA)]
    claves += [
        f"datos.{codigo}"
        for codigo in (
            espacio.AVISO_COMPACTANDO,
            espacio.AVISO_SIN_ESPACIO,
            espacio.AVISO_SIN_COMPACTAR,
        )
    ]
    claves += [
        f"estado.fuentes.journal_estado.{e}"
        for e in (vista.JOURNAL_LEYENDO, vista.JOURNAL_SIN_CARPETA, vista.JOURNAL_SIN_ARCHIVOS)
    ]
    claves += [f"estado.fuentes.eddn_estado.{e}" for e in ESTADOS_EDDN]
    claves += [f"estado.fuentes.spansh_estado.{e}" for e in ESTADOS_DE_SPANSH]
    claves += [f"configuracion.spansh.fase.{f}" for f in FASES_DEL_GESTOR]
    claves += [f"configuracion.spansh.errores.{e}" for e in ERRORES_DEL_GESTOR]
    claves += [f"configuracion.errores.{e}" for e in ERRORES_DE_DATOS]
    claves += [f"estado.nave.plataformas.{p}" for p in ("S", "M", "L")]
    assert [clave for clave in claves if not isinstance(buscar(clave), str)] == []


def test_los_textos_con_marcadores_aceptan_sus_valores():
    ejemplos = {
        "estado.legacy": {"version": "3.8"},
        "estado.ubicacion.al_centro_valor": {"distancia": "1", "centro": "Sol"},
        "estado.nave.modelo_con_nombre": {"modelo": "Python", "nombre": "x"},
        "estado.carga.resumen": {"total": 1, "capacidad": 2},
        "estado.fuentes.journal_ultimo": {"estado": "a", "hace": "b"},
        "estado.fuentes.spansh_estado.completa": {"hace": "a", "centro": "b", "radio": "c"},
        "estado.fuentes.spansh_estado.descargando": {"porcentaje": "a"},
        "estado.fuentes.spansh_estado.pausada": {"porcentaje": "a"},
        "estado.fuentes.spansh_estado.importando_leyendo": {"porcentaje": "a"},
        "estado.fuentes.spansh_estado.error": {"motivo": "a"},
        "configuracion.esfera.actual_valor": {"centro": "a", "radio": "b"},
        "configuracion.esfera.propuesta.resumen": {"centro": "a", "radio": "b"},
        "configuracion.esfera.propuesta.descarga_si": {"tamano": "a", "libre": "b"},
        "configuracion.esfera.propuesta.descarga_si_sin_tamano": {"libre": "a"},
        "configuracion.esfera.propuesta.descarga_no_repetir": {"tamano": "a"},
        "configuracion.spansh.progreso_descarga": {"descargado": 1, "total": 2, "porcentaje": 3},
        "configuracion.spansh.progreso_lectura": {"porcentaje": "a", "encontrados": 2},
        "configuracion.spansh.progreso_guardado": {"guardados": 1, "encontrados": 2},
        "configuracion.spansh.ultima": {"hace": "a", "centro": "b", "radio": "c"},
        "formato.gib": {"valor": 1},
        "formato.mib": {"valor": 1},
        "formato.kib": {"valor": 1},
        "formato.porcentaje": {"valor": 1},
    }
    for clave, valores in ejemplos.items():
        marcadores = set(re.findall(r"\{(\w+)\}", buscar(clave)))
        assert marcadores == set(valores), clave


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
    css = "".join(
        ruta.read_text(encoding="utf-8") for ruta in sorted((RAIZ / "ui" / "css").glob("*.css"))
    )
    propiedades = re.findall(
        r"^\s*(width|min-width|max-width|flex-basis|grid-template-columns)\s*:\s*([^;]+);",
        css,
        re.M,
    )
    en_pixeles = [f"{nombre}: {valor}" for nombre, valor in propiedades if "px" in valor]
    assert en_pixeles == []
