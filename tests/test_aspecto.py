import json
import re
import threading

import pytest

from core import events, recursos
from core.api import Api
from core.config import ajustes, aspecto
from core.config.rutas import Ubicacion
from core.nucleo import Nucleo

RAIZ = recursos.carpeta_de_recursos()
RUTAS_JS = RAIZ / "ui" / "js" / "rutas.js"
ES_JSON = RAIZ / "ui" / "i18n" / "es.json"


def interfaz(tmp_path):
    config = tmp_path / "config.json"
    api = Api(
        Nucleo(config, events.Bus(), None),
        Ubicacion(tmp_path, portable=True),
        config,
        base_disponible=True,
        elegir_carpeta=lambda: None,
    )
    return api, config


def test_sin_config_todo_es_de_fabrica(tmp_path):
    actual = aspecto.leer(tmp_path / "config.json")

    assert actual.tamano_letra == "normal"
    assert actual.densidad == "comoda"
    assert actual.filas_por_pagina == 10
    assert actual.columnas == aspecto.COLUMNAS_POR_DEFECTO


def test_las_columnas_de_un_salto_de_fabrica_son_las_que_pidio_el_usuario(tmp_path):
    por_defecto = aspecto.leer(tmp_path / "config.json").columnas["un_salto"]

    assert por_defecto == (
        "mercancia", "comprar", "vender", "ganancia_hora", "antiguedad", "toneladas",
        "ganancia_viaje", "tiempo",
    )  # fmt: skip


def test_lo_guardado_se_lee_de_vuelta_y_sobrevive_a_otra_lectura(tmp_path):
    api, config = interfaz(tmp_path)

    assert api.guardar_tamano_de_letra("muy_grande") == {"tamano_letra": "muy_grande"}
    assert api.guardar_densidad("compacta") == {"densidad": "compacta"}
    assert api.guardar_filas_por_pagina(25) == {"filas_por_pagina": 25}
    assert api.guardar_columnas("un_salto", ["tiempo", "mercancia"]) == {
        "modo": "un_salto",
        "elegidas": ["mercancia", "tiempo"],
    }

    leido = aspecto.leer(config)
    assert (leido.tamano_letra, leido.densidad) == ("muy_grande", "compacta")
    assert leido.filas_por_pagina == 25
    assert leido.columnas["un_salto"] == ("mercancia", "tiempo")
    assert leido.columnas["bucle"] == aspecto.COLUMNAS_POR_DEFECTO["bucle"]


def test_guardar_el_aspecto_conserva_los_ajustes_de_ventana(tmp_path):
    api, config = interfaz(tmp_path)
    ajustes.guardar_siempre_encima(config, True)
    ajustes.guardar_lateral_plegado(config, True)

    api.guardar_densidad("compacta")

    assert ajustes.interfaz(config) == (True, True)


def test_la_api_devuelve_lo_elegido_y_lo_que_se_puede_elegir(tmp_path):
    api, _ = interfaz(tmp_path)
    api.guardar_columnas("bucle", ["ida", "vuelta"])

    datos = api.ajustes_de_aspecto()

    assert datos["opciones"] == {
        "tamanos": ["pequeno", "normal", "grande", "muy_grande"],
        "densidades": ["comoda", "compacta"],
        "filas": [5, 10, 25],
    }
    assert datos["columnas"]["bucle"]["elegidas"] == ["ida", "vuelta"]
    assert datos["columnas"]["bucle"]["disponibles"] == list(aspecto.COLUMNAS_DISPONIBLES["bucle"])
    de_fabrica = list(aspecto.COLUMNAS_POR_DEFECTO["un_salto"])
    assert datos["columnas"]["un_salto"]["elegidas"] == de_fabrica


@pytest.mark.parametrize("valor", ["enorme", "", None, 3, ["normal"], True])
def test_un_tamano_de_letra_desconocido_se_rechaza_sin_escribir(tmp_path, valor):
    api, config = interfaz(tmp_path)

    assert api.guardar_tamano_de_letra(valor) == {"error": "parametro"}
    assert not config.exists()


@pytest.mark.parametrize("valor", ["apretada", None, 1, True])
def test_una_densidad_desconocida_se_rechaza_sin_escribir(tmp_path, valor):
    api, config = interfaz(tmp_path)

    assert api.guardar_densidad(valor) == {"error": "parametro"}
    assert not config.exists()


@pytest.mark.parametrize("valor", [7, 0, -10, 10.0, "10", None, True, 10**9])
def test_solo_se_admiten_las_filas_por_pagina_del_selector(tmp_path, valor):
    api, config = interfaz(tmp_path)

    assert api.guardar_filas_por_pagina(valor) == {"error": "parametro"}
    assert not config.exists()


@pytest.mark.parametrize(
    ("modo", "columnas"),
    [
        ("otro", ["mercancia"]),
        (None, ["mercancia"]),
        ("un_salto", []),
        ("un_salto", "mercancia"),
        ("un_salto", None),
        ("un_salto", ["no_existe"]),
        ("un_salto", ["mercancia", 3]),
        ("un_salto", [["mercancia"]]),
        ("un_salto", ["ida"]),
        ("bucle", ["mercancia"]),
    ],
)
def test_columnas_que_no_son_de_ese_modo_se_rechazan_sin_escribir(tmp_path, modo, columnas):
    api, config = interfaz(tmp_path)

    assert api.guardar_columnas(modo, columnas) == {"error": "parametro"}
    assert not config.exists()


def test_las_columnas_repetidas_se_guardan_una_vez_y_en_el_orden_de_la_tabla(tmp_path):
    api, config = interfaz(tmp_path)

    api.guardar_columnas("un_salto", ["tiempo", "mercancia", "tiempo"])

    assert aspecto.leer(config).columnas["un_salto"] == ("mercancia", "tiempo")


def test_un_config_con_valores_raros_vuelve_a_los_de_fabrica(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        '{"interfaz": {"tamano_letra": "gigante", "densidad": 3, "filas_por_pagina": 7,'
        ' "columnas_un_salto": ["nada"], "columnas_bucle": "ida"}}'
    )

    actual = aspecto.leer(config)

    assert (actual.tamano_letra, actual.densidad) == ("normal", "comoda")
    assert actual.filas_por_pagina == 10
    assert actual.columnas == aspecto.COLUMNAS_POR_DEFECTO


def test_si_no_se_puede_escribir_la_api_lo_dice(tmp_path, monkeypatch):
    api, _ = interfaz(tmp_path)
    monkeypatch.setattr(aspecto, "_guardar", lambda *_: False)

    assert api.guardar_densidad("compacta") == {"error": "no_guardado"}
    assert api.guardar_columnas("bucle", ["ida"]) == {"error": "no_guardado"}


def test_dos_hilos_que_guardan_campos_distintos_no_se_pisan(tmp_path):
    config = tmp_path / "config.json"
    salida = threading.Barrier(2)

    def guardar(funcion, valor):
        salida.wait()
        for _ in range(20):
            funcion(config, valor)

    hilos = [
        threading.Thread(target=guardar, args=(aspecto.guardar_densidad, "compacta")),
        threading.Thread(target=guardar, args=(aspecto.guardar_filas_por_pagina, 25)),
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    leido = aspecto.leer(config)
    assert (leido.densidad, leido.filas_por_pagina) == ("compacta", 25)


def nombres_de_columnas(modo):
    """Los nombres que `ui/js/rutas.js` define para un modo, en su orden."""
    codigo = RUTAS_JS.read_text(encoding="utf-8")
    cuerpo = re.search(rf"\b{modo}: \[(.*?)\n  \],", codigo, re.DOTALL)
    assert cuerpo, f"no se encontró el modo {modo} en rutas.js"
    return tuple(re.findall(r"^    \['(\w+)',", cuerpo.group(1), re.MULTILINE))


@pytest.mark.parametrize("modo", list(aspecto.COLUMNAS_DISPONIBLES))
def test_las_columnas_de_python_son_las_de_la_interfaz(modo):
    assert nombres_de_columnas(modo) == aspecto.COLUMNAS_DISPONIBLES[modo]


@pytest.mark.parametrize("modo", list(aspecto.COLUMNAS_DISPONIBLES))
def test_las_de_fabrica_son_columnas_disponibles(modo):
    assert set(aspecto.COLUMNAS_POR_DEFECTO[modo]) <= set(aspecto.COLUMNAS_DISPONIBLES[modo])


def _texto(clave):
    nodo = json.loads(ES_JSON.read_text(encoding="utf-8"))
    for parte in clave.split("."):
        nodo = nodo.get(parte) if isinstance(nodo, dict) else None
    return nodo


def test_hay_texto_para_cada_opcion_y_columna_de_lectura():
    """El panel y las tablas piden estas claves con una plantilla, que la otra prueba no ve."""
    columnas = {nombre for lista in aspecto.COLUMNAS_DISPONIBLES.values() for nombre in lista}
    claves = [f"configuracion.lectura.tamano_letra.{tamano}" for tamano in aspecto.TAMANOS_DE_LETRA]
    claves += [f"configuracion.lectura.densidad.{densidad}" for densidad in aspecto.DENSIDADES]
    claves += [f"comercio.rutas.columnas.{nombre}" for nombre in columnas]
    claves += [f"comercio.columnas_ayuda.{nombre}" for nombre in columnas]
    claves += [f"comercio.paginacion.{nombre}" for nombre in ("filas", "anterior", "siguiente")]

    assert [clave for clave in claves if not isinstance(_texto(clave), str)] == []


def test_el_resumen_de_la_paginacion_acepta_sus_valores():
    marcadores = set(re.findall(r"\{(\w+)\}", _texto("comercio.paginacion.resumen")))

    assert marcadores == {"desde", "hasta", "total"}
