import json
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from core.config import ajustes
from core.db import esquema
from core.db.escritor import Escritor
from core.state.estado import Compra, Estacion, Estado, Mercancia, aplicar
from modules.comercio import api as modulo
from modules.comercio.engine import candidatos
from modules.comercio.engine.perfil import desde_dict
from tests.bucle_de_prueba import guardar_el_bucle
from tests.mercado_de_prueba import AHORA, compra, estacion, perfil, sistema, vende

FIXTURES = Path(__file__).parent / "fixtures" / "journal"
ESPERA = 5.0

AQUI = Estado(legacy=False, sistema="S1", posicion=(0.0, 0.0, 0.0))


@pytest.fixture
def ruta(tmp_path):
    """Dos estaciones a 10 ly: oro barato en la 1 y caro en la 2, plata al revés."""
    archivo = tmp_path / "luna.db"
    conexion = sqlite3.connect(archivo, isolation_level=None)
    esquema.migrar(conexion)
    sistema(conexion, 1, 0.0)
    sistema(conexion, 2, 10.0)
    estacion(conexion, 101, 1)
    estacion(conexion, 202, 2)
    vende(conexion, 101, "gold", 9_000)
    compra(conexion, 202, "gold", 10_000)
    vende(conexion, 202, "silver", 4_000)
    compra(conexion, 101, "silver", 4_500)
    conexion.execute(
        "INSERT INTO commodities (simbolo, nombre_en, nombre_es) VALUES ('gold', 'Gold', 'Oro')"
    )
    conexion.close()
    return archivo


def comercio(ruta, tmp_path, estado=AQUI, escritor=None) -> modulo.Comercio:
    return modulo.Comercio(
        lambda: estado, tmp_path / "config.json", ruta, escritor, reloj=lambda: AHORA
    )


def datos(**cambios) -> dict:
    return perfil(**cambios).a_dict()


def test_un_salto_devuelve_las_columnas_de_la_7_2_con_el_nombre_en_espanol(ruta, tmp_path):
    respuesta = comercio(ruta, tmp_path).buscar_rutas("un_salto", datos())

    primero = respuesta["resultados"][0]
    assert respuesta["modo"] == "un_salto"
    assert primero["mercancia"] == {"simbolo": "gold", "nombre": "Oro"}
    assert (primero["compra"]["market_id"], primero["venta"]["market_id"]) == (101, 202)
    assert primero["ganancia_tonelada"] == 1_000
    assert primero["toneladas"] == 100
    assert primero["ganancia_sesion"] == pytest.approx(primero["ganancia_hora"])
    assert sum(p["segundos"] for p in primero["tiempo"]) == pytest.approx(primero["segundos"])
    assert [p["parte"] for p in primero["tiempo"]] == [
        "salida",
        "saltos",
        "supercrucero",
        "atraque",
        "comercio",
    ]
    assert {p["fuente"] for p in primero["tiempo"]} == {"por_defecto"}
    # Sin nombre en la tabla, se enseña el símbolo.
    plata = next(r for r in respuesta["resultados"] if r["mercancia"]["simbolo"] == "silver")
    assert plata["mercancia"]["nombre"] == "silver"
    json.dumps(respuesta)


def test_el_bucle_lleva_ida_y_vuelta(ruta, tmp_path):
    [bucle] = comercio(ruta, tmp_path).buscar_rutas("bucle", datos())["resultados"]

    simbolos = {bucle["ida"]["mercancia"]["simbolo"], bucle["vuelta"]["mercancia"]["simbolo"]}
    assert simbolos == {"gold", "silver"}
    assert bucle["ganancia_viaje"] == 100 * 1_000 + 100 * 500


@pytest.mark.parametrize("modo", ["otro", None, ["un_salto"], 3])
def test_un_modo_desconocido_se_rechaza(ruta, tmp_path, modo):
    assert comercio(ruta, tmp_path).buscar_rutas(modo, datos()) == {
        "error": "parametro",
        "campo": "modo",
    }


def test_un_perfil_invalido_dice_que_campo_falla(ruta, tmp_path):
    malo = {**datos(), "capacidad": -1}
    assert comercio(ruta, tmp_path).buscar_rutas("un_salto", malo) == {
        "error": "perfil",
        "campo": "capacidad",
    }


def test_la_antiguedad_no_puede_pasar_del_tope_de_la_configuracion(ruta, tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({"comercio": {"tope_antiguedad_dias": 2}}), encoding="utf-8"
    )
    respuesta = comercio(ruta, tmp_path).buscar_rutas("un_salto", datos(antiguedad_max_h=49.0))
    assert respuesta == {"error": "perfil", "campo": "antiguedad_max_h"}


def test_con_un_journal_de_legacy_no_hay_rutas(ruta, tmp_path):
    legacy = Estado(legacy=True)
    assert comercio(ruta, tmp_path, legacy).buscar_rutas("un_salto", datos()) == {"error": "legacy"}
    assert comercio(ruta, tmp_path, legacy).ahora(datos()) == {"error": "legacy"}


def test_un_origen_que_no_esta_en_la_base_se_rechaza(ruta, tmp_path):
    respuesta = comercio(ruta, tmp_path).buscar_rutas("un_salto", datos(origen="Nadie"))
    assert respuesta == {"error": "origen_desconocido"}


def test_el_origen_no_distingue_mayusculas(ruta, tmp_path):
    lejos = Estado(legacy=False, sistema="Recien llegado", posicion=(5.0, 0.0, 0.0))
    api = comercio(ruta, tmp_path, lejos)

    en_la_base = api.buscar_rutas("un_salto", datos(origen="s2"))
    assert en_la_base["resultados"][0]["compra"]["distancia_origen"] == pytest.approx(10.0)
    el_actual = api.buscar_rutas("un_salto", datos(origen="RECIEN LLEGADO"))
    assert el_actual["resultados"][0]["compra"]["distancia_origen"] == pytest.approx(5.0)


def test_el_sistema_actual_vale_como_origen_aunque_no_este_en_la_base(ruta, tmp_path):
    lejos = Estado(legacy=False, sistema="Recien llegado", posicion=(5.0, 0.0, 0.0))
    respuesta = comercio(ruta, tmp_path, lejos).buscar_rutas(
        "un_salto", datos(origen="Recien llegado")
    )
    assert respuesta["resultados"][0]["compra"]["distancia_origen"] == pytest.approx(5.0)


def test_sin_base_no_hay_busqueda(tmp_path):
    sin_base = modulo.Comercio(lambda: AQUI, tmp_path / "config.json", None, None)
    assert sin_base.buscar_rutas("un_salto", datos()) == {"error": "sin_base"}
    assert sin_base.perfiles_guardados() == {"error": "sin_base"}
    assert sin_base.guardar_perfil("x", datos()) == {"error": "sin_base"}


def test_una_base_ilegible_responde_con_error_y_no_con_una_excepcion(tmp_path):
    rota = tmp_path / "rota.db"
    rota.write_bytes(b"esto no es sqlite" * 100)
    assert comercio(rota, tmp_path).buscar_rutas("un_salto", datos()) == {"error": "base"}


class Bloqueo:
    """Sustituye la lectura de candidatos: la primera llamada espera a que la cancelen."""

    def __init__(self, monkeypatch) -> None:
        self.dentro = threading.Event()
        self._real = candidatos.cargar
        self._primera = True
        monkeypatch.setattr(modulo.candidatos, "cargar", self)

    def __call__(self, *argumentos, parar=None, **opciones):
        if self._primera:
            self._primera = False
            self.dentro.set()
            assert parar.wait(ESPERA)
            # Devuelve la lectura completa: aun así la API no debe enseñarla.
        return self._real(*argumentos, parar=None, **opciones)


def en_hilo(funcion, *argumentos) -> tuple[threading.Thread, dict]:
    salida: dict = {}
    hilo = threading.Thread(target=lambda: salida.update(r=funcion(*argumentos)))
    hilo.start()
    return hilo, salida


def test_una_busqueda_nueva_cancela_la_anterior_y_esta_no_devuelve_nada(
    ruta, tmp_path, monkeypatch
):
    bloqueo = Bloqueo(monkeypatch)
    api = comercio(ruta, tmp_path)
    hilo, primera = en_hilo(api.buscar_rutas, "un_salto", datos())
    assert bloqueo.dentro.wait(ESPERA)

    segunda = api.buscar_rutas("un_salto", datos())
    hilo.join(ESPERA)

    assert primera["r"] == {"cancelada": True}
    assert segunda["resultados"]


def test_ahora_no_cancela_una_busqueda_de_rutas(ruta, tmp_path, monkeypatch):
    bloqueo = Bloqueo(monkeypatch)
    api = comercio(ruta, tmp_path)
    hilo, rutas = en_hilo(api.buscar_rutas, "un_salto", datos())
    assert bloqueo.dentro.wait(ESPERA)

    api.ahora(datos())
    hilo.join(0.5)

    assert hilo.is_alive()
    api.buscar_rutas("un_salto", datos())  # la de Rutas sí la cancela
    hilo.join(ESPERA)
    assert rutas["r"] == {"cancelada": True}


def test_la_cancelacion_real_de_la_lectura_llega_como_cancelada(ruta, tmp_path, monkeypatch):
    def cancelada(*_, **__):
        raise candidatos.BusquedaCancelada

    monkeypatch.setattr(modulo.candidatos, "cargar", cancelada)
    assert comercio(ruta, tmp_path).buscar_rutas("un_salto", datos()) == {"cancelada": True}


def atracado_en(market_id: int, carga=(), compras=()) -> Estado:
    return replace(
        AQUI,
        estacion=Estacion("E", market_id, "Coriolis", "L", 100.0),
        carga=tuple(carga),
        compras=tuple(compras),
    )


def test_ahora_vende_la_carga_con_su_ganancia_y_compra_desde_aqui(ruta, tmp_path):
    estado = atracado_en(
        101, carga=[Mercancia("Oro", 50, "gold")], compras=[Compra("gold", 50, 50 * 8_000)]
    )
    respuesta = comercio(ruta, tmp_path, estado).ahora(datos())

    [oro] = respuesta["vender"]
    assert oro["mercancia"] == {"simbolo": "gold", "nombre": "Oro"}
    assert (oro["cantidad"], oro["precio_compra"]) == (50, 8_000)
    assert oro["destinos"][0]["venta"]["market_id"] == 202
    assert oro["destinos"][0]["ganancia"] == 50 * 2_000
    assert [t["mercancia"]["simbolo"] for t in respuesta["desde_aqui"]] == ["gold"]
    json.dumps(respuesta)


def test_ahora_sin_atracar_no_compra_desde_aqui_y_sin_compra_no_hay_ganancia(ruta, tmp_path):
    estado = replace(AQUI, carga=(Mercancia("Oro", 5, "gold"),))
    respuesta = comercio(ruta, tmp_path, estado).ahora(datos())

    assert respuesta["desde_aqui"] is None
    assert respuesta["vender"][0]["precio_compra"] is None
    assert respuesta["vender"][0]["destinos"][0]["ganancia"] is None


def test_ahora_solo_vende_lo_vendible_y_una_vez_por_mercancia(ruta, tmp_path):
    carga = [
        Mercancia("Oro", 30, "gold"),
        Mercancia("Oro", 20, "gold", de_mision=True),
        Mercancia("Oro", 10, "gold", robadas=4),
        Mercancia("Plata", 5, "silver", robadas=5),
    ]
    respuesta = comercio(ruta, tmp_path, atracado_en(101, carga=carga)).ahora(datos())

    [oro] = respuesta["vender"]
    assert (oro["mercancia"]["simbolo"], oro["cantidad"]) == ("gold", 36)
    assert oro["destinos"][0]["toneladas"] == 36


def test_ahora_no_depende_del_origen_de_rutas(ruta, tmp_path):
    respuesta = comercio(ruta, tmp_path).ahora(datos(origen="Nadie"))
    assert "error" not in respuesta
    vacio = {**datos(), "origen": ""}
    assert "error" not in comercio(ruta, tmp_path).ahora(vacio)


def test_ahora_sin_posicion_conocida_no_busca(ruta, tmp_path):
    respuesta = comercio(ruta, tmp_path, Estado(legacy=False)).ahora(datos())
    assert respuesta == {"error": "sin_posicion"}


def sesion() -> Estado:
    estado = Estado()
    texto = (FIXTURES / "sesion_comercio.log").read_text(encoding="utf-8")
    for linea in texto.splitlines():
        estado = aplicar(estado, json.loads(linea))
    return estado


def test_el_perfil_inicial_sale_de_la_nave_y_es_un_perfil_valido(ruta, tmp_path):
    inicial = comercio(ruta, tmp_path, sesion()).perfil_inicial()

    p = inicial["perfil"]
    automaticos = {"capacidad", "rango", "plataforma", "stock_minimo", "origen"}
    assert set(inicial["automaticos"]) == automaticos
    assert (p["capacidad"], p["plataforma"]) == (1120, "L")
    assert (p["stock_minimo"], p["limitar_saldo"], p["ganancia_min"]) == (1120, True, 0)
    assert "creditos" not in p
    assert inicial["saldo"] == sesion().creditos
    assert p["origen"] == "Col 285 Sector HB-C b14-2"
    assert 0 < p["rango"] < 49.3
    assert p["rango"] == round(p["rango"], 2)
    assert p["distancia_max_ly"] == 50.0
    assert inicial["limites"] == {"antiguedad_max_h": 7 * 24.0}
    desde_dict(p, 7)


def test_sin_nave_el_perfil_inicial_deja_vacio_lo_que_no_se_sabe(ruta, tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({"comercio": {"tipos_estacion": ["orbital"]}}), encoding="utf-8"
    )
    inicial = comercio(ruta, tmp_path, Estado()).perfil_inicial()

    assert inicial["automaticos"] == []
    assert inicial["perfil"]["capacidad"] is None
    assert inicial["perfil"]["tipos"] == ["orbital"]
    json.dumps(inicial)


@pytest.fixture
def escritor(ruta):
    hilo = Escritor(ruta)
    hilo.iniciar()
    yield hilo
    hilo.detener()


def test_un_perfil_se_guarda_se_lista_y_se_borra(ruta, tmp_path, escritor):
    api = comercio(ruta, tmp_path, escritor=escritor)

    assert api.guardar_perfil("  Panther  ", datos(capacidad=720)) == {
        "pendiente": False,
        "ok": True,
    }
    [guardado] = api.perfiles_guardados()["perfiles"]
    assert (guardado["nombre"], guardado["perfil"]["capacidad"]) == ("Panther", 720)

    assert api.borrar_perfil("panther")["ok"]
    assert api.perfiles_guardados() == {"perfiles": []}


@pytest.mark.parametrize("nombre", ["", "   ", None, 3, "x" * 101, "a\nb"])
def test_un_nombre_de_perfil_invalido_se_rechaza(ruta, tmp_path, escritor, nombre):
    api = comercio(ruta, tmp_path, escritor=escritor)
    assert api.guardar_perfil(nombre, datos()) == {"error": "perfil", "campo": "nombre"}
    assert api.borrar_perfil(nombre) == {"error": "perfil", "campo": "nombre"}


def test_con_el_escritor_ocupado_se_responde_pendiente_y_se_guarda_despues(
    ruta, tmp_path, escritor, monkeypatch
):
    monkeypatch.setattr(modulo, "ESPERA_DE_ESCRITURA", 0.05)
    soltar = threading.Event()
    escritor.encolar(lambda _: soltar.wait(ESPERA))
    api = comercio(ruta, tmp_path, escritor=escritor)

    assert api.guardar_perfil("Lento", datos()) == {"pendiente": True}

    soltar.set()
    hecho = threading.Event()
    escritor.encolar(lambda _: None, lambda _: hecho.set())
    assert hecho.wait(ESPERA)
    assert [g["nombre"] for g in api.perfiles_guardados()["perfiles"]] == ["Lento"]


def test_si_la_escritura_falla_se_avisa(ruta, tmp_path, escritor, monkeypatch):
    def falla(*_):
        raise sqlite3.OperationalError("disco lleno")

    monkeypatch.setattr(modulo.perfiles, "guardar", falla)
    api = comercio(ruta, tmp_path, escritor=escritor)
    assert api.guardar_perfil("X", datos()) == {"pendiente": False, "error": "no_guardado"}


def test_los_ajustes_de_busqueda_salen_de_la_configuracion(ruta, tmp_path):
    assert comercio(ruta, tmp_path).ajustes_de_busqueda() == {
        "tope_antiguedad_dias": 7,
        "tope_maximo_dias": 30,
        "tipos": list(ajustes.TIPOS_DE_ESTACION),
        "limite_busqueda_s": 8,
        "limite_minimo_s": 3,
        "limite_maximo_s": 30,
    }


def test_guardar_los_ajustes_de_busqueda_cambia_el_perfil_inicial(ruta, tmp_path):
    api = comercio(ruta, tmp_path)
    respuesta = api.guardar_ajustes_de_busqueda(2, ["asentamiento", "orbital"], 8)

    assert respuesta["ok"] is True
    assert respuesta["tipos"] == ["orbital", "asentamiento"]
    inicial = api.perfil_inicial()
    assert inicial["perfil"]["tipos"] == ["orbital", "asentamiento"]
    assert inicial["limites"] == {"antiguedad_max_h": 48.0}
    assert inicial["perfil"]["antiguedad_max_h"] == 24.0


@pytest.mark.parametrize("tope", [0, 31, 7.0, "7", True, None, -1])
def test_un_tope_fuera_de_rango_no_se_guarda(ruta, tmp_path, tope):
    api = comercio(ruta, tmp_path)
    respuesta = api.guardar_ajustes_de_busqueda(tope, ["orbital"], 8)
    assert respuesta == {"error": "parametro", "campo": "tope_antiguedad_dias"}
    assert api.ajustes_de_busqueda()["tope_antiguedad_dias"] == 7


@pytest.mark.parametrize(
    "tipos",
    [[], ["fleet_carrier"], ["orbital", "orbital"], "orbital", None, [3], ("orbital",)],
)
def test_unos_tipos_invalidos_no_se_guardan(ruta, tmp_path, tipos):
    api = comercio(ruta, tmp_path)
    respuesta = api.guardar_ajustes_de_busqueda(7, tipos, 8)
    assert respuesta == {"error": "parametro", "campo": "tipos"}
    assert not (tmp_path / "config.json").exists()


def test_si_la_configuracion_no_se_puede_escribir_se_avisa(ruta, tmp_path, monkeypatch):
    monkeypatch.setattr(ajustes, "guardar_busqueda", lambda *_: False)
    respuesta = comercio(ruta, tmp_path).guardar_ajustes_de_busqueda(7, ["orbital"], 8)
    assert respuesta == {"error": "no_guardado"}


def test_la_busqueda_usa_los_tiempos_de_la_nave_en_la_que_vas(ruta, tmp_path):
    from core.state.estado import NaveActual

    conexion = sqlite3.connect(ruta, isolation_level=None)
    conexion.execute("INSERT INTO commanders VALUES ('F1', 'CMDR Prueba', '2026-11-14')")
    for i in range(12):
        conexion.execute(
            "INSERT INTO timing_samples VALUES ('F1', 14, 'comercio', ?, 300.0, NULL)",
            (f"2026-11-14T10:00:{i:02d}Z",),
        )
    conexion.close()
    nave = NaveActual(14, "panthermkii", "", "", 1120, 64.0, None)
    estado = replace(AQUI, fid="F1", nave=nave)

    respuesta = comercio(ruta, tmp_path, estado).buscar_rutas("un_salto", datos())

    primero = respuesta["resultados"][0]
    partes = {p["parte"]: p for p in primero["tiempo"]}
    assert partes["comercio"] == {
        "parte": "comercio",
        "segundos": 300.0,
        "fuente": "nave",
        "muestras": 12,
    }
    assert partes["saltos"]["fuente"] == "por_defecto"
    assert primero["segundos"] == pytest.approx(sum(p["segundos"] for p in primero["tiempo"]))


def base_con_el_bucle(tmp_path: Path) -> Path:
    archivo = tmp_path / "rendimiento.db"
    conexion = sqlite3.connect(archivo, isolation_level=None)
    esquema.migrar(conexion)
    guardar_el_bucle(conexion)
    conexion.execute(
        "INSERT INTO sessions VALUES ('F0000001', '2026-11-10T03:41:24Z', "
        "'2026-11-10T08:22:30Z', '2026-11-10T03:41:24Z', NULL, 0, 312382560, 312382560, "
        "15680, 54, 1)"
    )
    conexion.close()
    return archivo


COMANDANTE = replace(AQUI, fid="F0000001")


def test_rendimiento_da_la_ultima_sesion_con_sus_rutas_y_mercancias(tmp_path):
    respuesta = comercio(base_con_el_bucle(tmp_path), tmp_path, COMANDANTE).rendimiento(None)

    assert respuesta["seleccion"] == "2026-11-10T03:41:24Z"
    assert [s["inicio"] for s in respuesta["sesiones"]] == ["2026-11-10T03:41:24Z"]
    assert respuesta["sesiones"][0]["en_curso"] is False
    resumen = respuesta["resumen"]
    assert (resumen["ganancia"], resumen["toneladas"], resumen["saltos"]) == (
        312_382_560,
        15680,
        54,
    )
    assert resumen["comparacion"]["tramos"] == 14
    assert [len(respuesta["rutas"]), len(respuesta["mercancias"])] == [2, 2]
    assert respuesta["rutas"][0]["origen"] == {
        "estacion": "Antonelli Arsenal",
        "sistema": "HIP 45301",
    }


def test_rendimiento_de_una_sesion_que_no_existe(tmp_path):
    api = comercio(base_con_el_bucle(tmp_path), tmp_path, COMANDANTE)

    assert api.rendimiento("2026-01-01T00:00:00Z") == {"error": "sesion_desconocida"}
    assert api.rendimiento("todo")["seleccion"] == "todo"


@pytest.mark.parametrize("sesion", [5, ["x"], "x" * 41])
def test_rendimiento_rechaza_una_sesion_mal_formada(tmp_path, sesion):
    api = comercio(base_con_el_bucle(tmp_path), tmp_path, COMANDANTE)

    assert api.rendimiento(sesion) == {"error": "parametro", "campo": "sesion"}


def test_rendimiento_sin_comandante_ni_sesiones(ruta, tmp_path):
    assert comercio(ruta, tmp_path).rendimiento(None) == {"error": "sin_comandante"}
    vacio = comercio(ruta, tmp_path, COMANDANTE).rendimiento(None)
    assert (vacio["sesiones"], vacio["seleccion"], vacio["resumen"]) == ([], None, None)


def test_guardar_el_ajuste_de_sesiones(ruta, tmp_path):
    api = comercio(ruta, tmp_path)

    respuesta = api.guardar_ajustes_de_sesiones(3, True)

    assert respuesta == {
        "ok": True,
        "pausa_horas": 3,
        "por_partida": True,
        "minimo": 1,
        "maximo": 12,
    }
    assert ajustes.sesiones(tmp_path / "config.json") == (3, True)


@pytest.mark.parametrize(
    ("horas", "por_partida", "campo"),
    [
        (0, False, "pausa_horas"),
        (13, False, "pausa_horas"),
        (True, False, "pausa_horas"),
        (2.5, False, "pausa_horas"),
        (2, "si", "por_partida"),
    ],
)
def test_un_ajuste_de_sesiones_invalido_no_se_guarda(ruta, tmp_path, horas, por_partida, campo):
    api = comercio(ruta, tmp_path)

    assert api.guardar_ajustes_de_sesiones(horas, por_partida) == {
        "error": "parametro",
        "campo": campo,
    }
    assert ajustes.sesiones(tmp_path / "config.json") == (1, False)


def test_omitir_sesiones_vacias_viene_activado_y_se_recuerda(ruta, tmp_path):
    api = comercio(base_con_el_bucle(tmp_path), tmp_path, COMANDANTE)
    assert api.rendimiento(None)["ajuste"]["omitir_vacias"] is True

    assert api.guardar_omitir_sesiones_vacias(False) == {"ok": True, "omitir_vacias": False}

    assert api.rendimiento(None)["ajuste"]["omitir_vacias"] is False


def test_guardar_el_umbral_de_sesiones_no_borra_omitir_vacias(ruta, tmp_path):
    api = comercio(ruta, tmp_path)
    api.guardar_omitir_sesiones_vacias(False)

    api.guardar_ajustes_de_sesiones(3, True)

    assert ajustes.omitir_sesiones_vacias(tmp_path / "config.json") is False


@pytest.mark.parametrize("valor", ["si", 1, None])
def test_omitir_sesiones_vacias_rechaza_lo_que_no_es_un_booleano(ruta, tmp_path, valor):
    api = comercio(ruta, tmp_path)

    assert api.guardar_omitir_sesiones_vacias(valor) == {
        "error": "parametro",
        "campo": "omitir_vacias",
    }


def test_rendimiento_lleva_el_saldo_actual_del_estado(tmp_path):
    estado = replace(COMANDANTE, creditos=1_234_567)

    respuesta = comercio(base_con_el_bucle(tmp_path), tmp_path, estado).rendimiento(None)

    assert respuesta["saldo_actual"] == 1_234_567


def test_reglas_de_alertas_por_defecto_y_guardadas(ruta, tmp_path):
    escritor = Escritor(ruta)
    escritor.iniciar()
    try:
        api = comercio(ruta, tmp_path, escritor=escritor)
        respuesta = api.reglas_de_alertas()
        assert respuesta["reglas"]["activadas"] is False
        reglas = {**respuesta["reglas"], "activadas": True, "distancia_max_ly": 12.5}

        guardado = api.guardar_reglas_de_alertas(reglas)

        assert guardado["ok"] is True
        assert api.reglas_de_alertas()["reglas"] == reglas
    finally:
        escritor.detener()


def test_una_regla_invalida_no_se_guarda(ruta, tmp_path):
    api = comercio(ruta, tmp_path)
    reglas = {**api.reglas_de_alertas()["reglas"], "repetir_min": 0}

    assert api.guardar_reglas_de_alertas(reglas) == {"error": "regla", "campo": "repetir_min"}


@pytest.mark.parametrize("desde", [-1, True, "3", 2.0])
def test_avisos_rechaza_un_desde_mal_formado(ruta, tmp_path, desde):
    assert comercio(ruta, tmp_path).avisos(desde) == {"error": "parametro", "campo": "desde_id"}


def test_avisos_sin_ninguno(ruta, tmp_path):
    assert comercio(ruta, tmp_path).avisos(None) == {"avisos": [], "ultimo": 0}


def test_ajustes_de_sonido(ruta, tmp_path):
    probados = []
    api = modulo.Comercio(
        lambda: AQUI, tmp_path / "config.json", ruta, None, probar_sonido=probados.append
    )

    assert api.ajustes_de_sonido() == {"activado": True, "volumen": 70}
    guardado = api.guardar_ajustes_de_sonido(False, 30)
    assert guardado == {"ok": True, "activado": False, "volumen": 30}
    assert api.guardar_ajustes_de_sonido(True, 101) == {"error": "parametro", "campo": "volumen"}
    assert api.guardar_ajustes_de_sonido("si", 30) == {"error": "parametro", "campo": "activado"}
    assert api.probar_sonido(40) == {"ok": True}
    assert api.probar_sonido(True) == {"error": "parametro", "campo": "volumen"}
    assert probados == [40]


def test_una_busqueda_corta_lo_dice_y_su_explicacion_se_pide_aparte(ruta, tmp_path):
    api = comercio(ruta, tmp_path)
    respuesta = api.buscar_rutas("un_salto", datos(ganancia_min=5_000))
    assert (respuesta["resultados"], respuesta["corta"]) == ([], True)
    assert "descartes" not in respuesta

    explicacion = api.explicar_busqueda(datos(ganancia_min=5_000))["descartes"]
    assert explicacion["estaciones_validas"] == 2
    assert explicacion["descartes"]["ganancia_min"] == 2


def test_una_busqueda_con_bastantes_resultados_no_es_corta(ruta, tmp_path, monkeypatch):
    monkeypatch.setattr(modulo.descartes, "RESULTADOS_CORTOS", 1)
    assert comercio(ruta, tmp_path).buscar_rutas("un_salto", datos())["corta"] is False


def test_la_explicacion_valida_el_perfil_como_la_busqueda(ruta, tmp_path):
    respuesta = comercio(ruta, tmp_path).explicar_busqueda(datos(capacidad=0))
    assert respuesta == {"error": "perfil", "campo": "capacidad"}


def test_una_busqueda_nueva_cancela_la_explicacion_en_curso(ruta, tmp_path, monkeypatch):
    api = comercio(ruta, tmp_path)
    dentro = threading.Event()
    seguir = threading.Event()
    contar = modulo.descartes.contar

    def lento(*argumentos, **nombrados):
        dentro.set()
        seguir.wait(ESPERA)
        return contar(*argumentos, **nombrados)

    monkeypatch.setattr(modulo.descartes, "contar", lento)
    respuestas = []
    hilo = threading.Thread(target=lambda: respuestas.append(api.explicar_busqueda(datos())))
    hilo.start()
    assert dentro.wait(ESPERA)
    api.buscar_rutas("un_salto", datos())
    seguir.set()
    hilo.join(ESPERA)
    assert respuestas == [{"cancelada": True}]


def test_el_saldo_del_comandante_limita_las_toneladas_solo_con_la_casilla(ruta, tmp_path):
    pobre = Estado(legacy=False, sistema="S1", posicion=(0.0, 0.0, 0.0), creditos=18_000)
    limitada = comercio(ruta, tmp_path, pobre).buscar_rutas("un_salto", datos(limitar_saldo=True))
    libre = comercio(ruta, tmp_path, pobre).buscar_rutas("un_salto", datos(limitar_saldo=False))
    oro = next(r for r in limitada["resultados"] if r["mercancia"]["simbolo"] == "gold")
    oro_libre = next(r for r in libre["resultados"] if r["mercancia"]["simbolo"] == "gold")
    assert oro["toneladas"] == 2
    assert oro_libre["toneladas"] > 2


def test_el_buscador_de_estaciones_encuentra_por_parte_del_nombre_sin_mayusculas(ruta, tmp_path):
    api = comercio(ruta, tmp_path)
    [encontrada] = api.buscar_estaciones("e20")["estaciones"]
    assert (encontrada["market_id"], encontrada["sistema"]) == (202, "S2")
    assert encontrada["tipo"] == "orbital"
    assert encontrada["distancia_ly"] == pytest.approx(10.0)
    assert encontrada["horas"] == pytest.approx(0.5)
    assert [e["market_id"] for e in api.buscar_estaciones("S1")["estaciones"]] == [101]


def test_el_buscador_trata_los_comodines_como_letras_y_rechaza_textos_malos(ruta, tmp_path):
    api = comercio(ruta, tmp_path)
    assert api.buscar_estaciones("%%")["estaciones"] == []
    assert api.buscar_estaciones("E_0")["estaciones"] == []
    for malo in ("", " ", "a", "x" * 101, "E\x00", 5, None):
        assert api.buscar_estaciones(malo) == {"error": "parametro", "campo": "texto"}


def test_el_buscador_sin_base_responde_sin_base(tmp_path):
    sin_base = modulo.Comercio(lambda: AQUI, tmp_path / "config.json", None, None)
    assert sin_base.buscar_estaciones("Sol") == {"error": "sin_base"}


def test_cada_resultado_de_rutas_lleva_su_detalle_por_paradas(ruta, tmp_path):
    api = comercio(ruta, tmp_path)

    [salto, *_] = api.buscar_rutas("un_salto", datos())["resultados"]
    [bucle] = api.buscar_rutas("bucle", datos())["resultados"]

    assert [p["estacion"]["market_id"] for p in salto["detalle"]["paradas"]] == [101, 202]
    assert bucle["detalle"]["cerrada"] is True
    assert sorted(p["estacion"]["market_id"] for p in bucle["detalle"]["paradas"]) == [101, 202]


def test_ahora_lleva_el_detalle_de_vender_y_de_comprar_desde_aqui(ruta, tmp_path):
    estado = atracado_en(
        101, carga=[Mercancia("Oro", 50, "gold")], compras=[Compra("gold", 50, 50 * 8_000)]
    )
    respuesta = comercio(ruta, tmp_path, estado).ahora(datos())

    [destino, *_] = respuesta["vender"][0]["destinos"]
    [parada] = destino["detalle"]["paradas"]
    assert destino["detalle"]["desde_posicion"] is True
    assert parada["vender"][0]["mercancia"] == {"simbolo": "gold", "nombre": "Oro"}
    assert parada["vender"][0]["ganancia"] == 50 * 2_000
    assert respuesta["desde_aqui"][0]["detalle"]["cerrada"] is False
    json.dumps(respuesta)
