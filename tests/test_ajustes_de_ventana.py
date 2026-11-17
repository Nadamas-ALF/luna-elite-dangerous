import re
from pathlib import Path

import pytest

from core import events, plataforma, recursos
from core.api import Api
from core.config import ajustes
from core.config.rutas import Ubicacion
from core.nucleo import Nucleo


def interfaz(tmp_path, aplicar=None):
    config = tmp_path / "config.json"
    api = Api(
        Nucleo(config, events.Bus(), None),
        Ubicacion(tmp_path, portable=True),
        config,
        base_disponible=True,
        elegir_carpeta=lambda: None,
        aplicar_siempre_encima=aplicar,
    )
    return api, config


def test_por_defecto_la_ventana_no_va_encima_y_la_barra_esta_desplegada(tmp_path):
    assert ajustes.interfaz(tmp_path / "config.json") == (False, False)


def test_los_dos_ajustes_se_guardan_sin_pisarse(tmp_path):
    api, config = interfaz(tmp_path, aplicar=lambda _: None)

    api.guardar_siempre_encima(True)
    api.guardar_lateral_plegado(True)

    assert ajustes.interfaz(config) == (True, True)
    assert api.ajustes_de_ventana() == {
        "siempre_encima": True,
        "lateral_plegado": True,
        "secciones_abiertas": ["esfera", "spansh"],
    }


def test_siempre_encima_se_aplica_en_vivo(tmp_path):
    pedidos = []
    api, _ = interfaz(tmp_path, aplicar=pedidos.append)

    assert api.guardar_siempre_encima(True) == {"siempre_encima": True, "aplicado": True}
    assert pedidos == [True]


def test_si_la_ventana_no_lo_admite_se_guarda_y_se_dice_que_hace_falta_reiniciar(tmp_path):
    def roto(_):
        raise RuntimeError("sin ventana")

    api, config = interfaz(tmp_path, aplicar=roto)

    assert api.guardar_siempre_encima(True) == {"siempre_encima": True, "aplicado": False}
    assert ajustes.interfaz(config)[0] is True


@pytest.mark.parametrize("valor", ["si", 1, None, [True]])
def test_la_api_rechaza_lo_que_no_es_un_booleano(tmp_path, valor):
    api, config = interfaz(tmp_path, aplicar=lambda _: None)

    assert api.guardar_siempre_encima(valor) == {"error": "parametro"}
    assert api.guardar_lateral_plegado(valor) == {"error": "parametro"}
    assert not config.exists()


def test_un_config_con_valores_raros_vuelve_a_los_de_fabrica(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"interfaz": {"siempre_encima": "si", "lateral_plegado": 3}}')

    assert ajustes.interfaz(config) == (False, False)


class Forma:
    class Handle:
        @staticmethod
        def ToInt64():  # noqa: N802 - nombre de .NET
            return 1234


def test_la_barra_se_tine_con_modo_oscuro_y_los_tres_colores_en_windows_11(monkeypatch):
    llamadas = []
    monkeypatch.setattr(plataforma, "_atributo", lambda h, a, v: llamadas.append((h, a, v)) or True)

    assert plataforma.tenir_barra_de_titulo(Forma, compilacion=26100)

    assert [a for _, a, _ in llamadas] == [20, 35, 36, 34]
    assert llamadas[1][2] == 0x20120A  # COLORREF es 0x00BBGGRR
    assert all(h == 1234 for h, _, _ in llamadas)


def test_en_windows_10_solo_se_pide_el_modo_oscuro(monkeypatch):
    llamadas = []
    monkeypatch.setattr(plataforma, "_atributo", lambda h, a, v: llamadas.append(a) or True)

    assert plataforma.tenir_barra_de_titulo(Forma, compilacion=19045)

    assert llamadas == [20]


def test_si_windows_rechaza_la_barra_se_queda_como_estaba(monkeypatch):
    monkeypatch.setattr(plataforma, "_atributo", lambda *_: False)

    assert plataforma.tenir_barra_de_titulo(Forma, compilacion=26100) is False


def test_una_excepcion_al_tenir_no_se_propaga(monkeypatch):
    def falla(*_):
        raise OSError("dwmapi")

    monkeypatch.setattr(plataforma, "_atributo", falla)

    assert plataforma.tenir_barra_de_titulo(Forma, compilacion=26100) is False


def token(css: str, nombre: str) -> tuple[int, int, int]:
    hexa = re.search(rf"--{nombre}:\s*#([0-9a-fA-F]{{6}})", css).group(1)
    return tuple(int(hexa[i : i + 2], 16) for i in (0, 2, 4))


def test_los_colores_de_la_barra_son_los_tokens_del_tema():
    css = (Path(recursos.carpeta_de_recursos()) / "ui" / "css" / "base.css").read_text("utf-8")

    assert token(css, "bg") == plataforma.COLOR_BARRA
    assert token(css, "text") == plataforma.COLOR_TEXTO_BARRA


def test_dos_hilos_que_guardan_campos_distintos_no_se_pisan(tmp_path):
    """Antes cada guardado leía la sección fuera del candado y la escribía entera."""
    import threading

    api, config = interfaz(tmp_path, aplicar=lambda _: None)
    salida = threading.Barrier(2)

    def encima():
        salida.wait()
        for _ in range(40):
            api.guardar_siempre_encima(True)

    def plegado():
        salida.wait()
        for _ in range(40):
            api.guardar_lateral_plegado(True)

    hilos = [threading.Thread(target=encima), threading.Thread(target=plegado)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert ajustes.interfaz(config) == (True, True)


def test_guardar_un_campo_conserva_el_resto_de_la_seccion(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"interfaz": {"lateral_plegado": true, "otro": 1}, "eddn": {}}')

    assert ajustes.guardar_siempre_encima(config, True)

    texto = config.read_text()
    assert ajustes.interfaz(config) == (True, True)
    assert '"otro": 1' in texto and '"eddn"' in texto


class FormaEnSuHilo:
    InvokeRequired = False


def test_desde_el_hilo_de_la_ventana_la_funcion_se_ejecuta_sin_invoke():
    llamadas = []

    plataforma.en_el_hilo_de_la_interfaz(FormaEnSuHilo, lambda: llamadas.append(1))

    assert llamadas == [1]


def test_desde_otro_hilo_la_funcion_pasa_por_invoke(monkeypatch):
    import sys
    import types

    class Forma:
        InvokeRequired = True
        recibido = None

        @classmethod
        def Invoke(cls, accion):  # noqa: N802 - nombre de .NET
            cls.recibido = accion
            accion()

    llamadas = []
    monkeypatch.setitem(sys.modules, "System", types.SimpleNamespace(Action=lambda f: f))

    plataforma.en_el_hilo_de_la_interfaz(Forma, lambda: llamadas.append(1))

    assert llamadas == [1]
    assert Forma.recibido is not None


def test_por_defecto_solo_estan_abiertas_la_esfera_y_spansh(tmp_path):
    assert ajustes.secciones_abiertas(tmp_path / "config.json") == ("esfera", "spansh")


def test_las_secciones_abiertas_se_guardan_y_sobreviven(tmp_path):
    api, config = interfaz(tmp_path)

    assert api.guardar_secciones_abiertas(["lectura", "journal"]) == {
        "secciones_abiertas": ["lectura", "journal"]
    }

    # Se devuelven en el orden de la pantalla y sin tocar los demás ajustes de la interfaz.
    assert api.ajustes_de_ventana()["secciones_abiertas"] == ["journal", "lectura"]
    assert api.guardar_lateral_plegado(True) == {"lateral_plegado": True}
    assert ajustes.secciones_abiertas(config) == ("journal", "lectura")


def test_todas_plegadas_es_una_eleccion_valida_y_no_vuelve_al_defecto(tmp_path):
    api, _ = interfaz(tmp_path)

    api.guardar_secciones_abiertas([])

    assert api.ajustes_de_ventana()["secciones_abiertas"] == []


@pytest.mark.parametrize(
    "valor",
    ["esfera", None, [1], ["nadie"], ["esfera", "esfera"], [["esfera"]], {"esfera": True}],
)
def test_la_api_rechaza_secciones_que_no_existen_o_con_otra_forma(tmp_path, valor):
    api, config = interfaz(tmp_path)

    assert api.guardar_secciones_abiertas(valor) == {"error": "parametro"}
    assert not config.exists()


def test_un_config_con_secciones_raras_vuelve_a_las_de_fabrica(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"interfaz": {"secciones_abiertas": "todas"}}')

    assert ajustes.secciones_abiertas(config) == ("esfera", "spansh")


def test_una_seccion_desconocida_guardada_a_mano_se_ignora(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"interfaz": {"secciones_abiertas": ["datos", "borrada", 3]}}')

    assert ajustes.secciones_abiertas(config) == ("datos",)
