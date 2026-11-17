"""Lo que un script de la página alcanza por el puente de pywebview (E-01)."""

import webview
import webview.util

from core import events
from core.api import Api, metodos_expuestos
from core.config.rutas import Ubicacion
from core.nucleo import Nucleo


class HiloEnLinea:
    """Ejecuta el trabajo al arrancar, para mirar el resultado sin esperas."""

    def __init__(self, target):
        self._target = target

    def start(self):
        self._target()


def ventana_con_api(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    nucleo = Nucleo(config, events.Bus(), None)
    detenidos = []
    monkeypatch.setattr(nucleo, "detener", lambda *a: detenidos.append(a))
    api = Api(nucleo, Ubicacion(tmp_path, portable=True), config, True, lambda: None)
    win = webview.create_window("prueba", html="<p></p>")
    webview.windows.remove(win)
    win.expose(*metodos_expuestos(api))
    respuestas = []
    monkeypatch.setattr(win, "evaluate_js", respuestas.append)
    monkeypatch.setattr(webview.util, "Thread", HiloEnLinea)
    return win, detenidos, respuestas


def test_solo_se_exponen_los_metodos_publicos(tmp_path, monkeypatch):
    win, _, _ = ventana_con_api(tmp_path, monkeypatch)

    assert "estado" in win._functions
    assert "guardar_columnas" in win._functions
    assert not [nombre for nombre in win._functions if nombre.startswith("_")]


def test_un_metodo_publico_se_puede_llamar(tmp_path, monkeypatch):
    win, _, respuestas = ventana_con_api(tmp_path, monkeypatch)

    webview.util.js_bridge_call(win, "ajustes_de_ventana", [], "1")

    assert len(respuestas) == 1
    assert "siempre_encima" in respuestas[0]


def test_un_atributo_interno_no_se_alcanza_por_nombre(tmp_path, monkeypatch):
    win, detenidos, respuestas = ventana_con_api(tmp_path, monkeypatch)

    for nombre in ("_nucleo.detener", "estado.__self__._nucleo.detener"):
        webview.util.js_bridge_call(win, nombre, [], "1")

    assert detenidos == []
    assert respuestas == []
