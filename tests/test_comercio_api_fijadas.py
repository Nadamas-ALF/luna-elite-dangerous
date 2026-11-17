"""Las rutas fijadas y la ruta en curso por la API de Comercio (prefase 8, bloque 5)."""

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from core.db import esquema
from core.db.escritor import Escritor
from modules.comercio import api as modulo
from modules.comercio import fijadas
from tests.bucle_de_prueba import guardar_el_bucle
from tests.mercado_de_prueba import AHORA, compra, estacion, sistema, vende
from tests.test_comercio_api import AQUI, sesion

ANTONELLI, BEREGOVOI = 4299403779, 3228387328
FIN_DEL_BUCLE = datetime(2026, 11, 10, 8, 30, 0, tzinfo=UTC)
COMANDANTE = "F0000001"


def con_nave():
    """El estado de la sesión real (nave de 1 120 t) puesto en las estaciones de la base."""
    return replace(sesion(), fid=COMANDANTE, sistema="S1", posicion=(0.0, 0.0, 0.0))


@pytest.fixture
def base(tmp_path):
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
    conexion.execute("INSERT INTO commodities (simbolo, nombre_en) VALUES ('silver', 'Silver')")
    conexion.close()
    return archivo


@pytest.fixture
def escritor(base):
    hilo = Escritor(base)
    hilo.iniciar()
    yield hilo
    hilo.detener()


def api(base, tmp_path, estado=None, escritor=None, reloj=lambda: AHORA) -> modulo.Comercio:
    return modulo.Comercio(
        lambda: estado or con_nave(), tmp_path / "config.json", base, escritor, reloj=reloj
    )


def pedida(*ids, cerrada=False) -> dict:
    return {"cerrada": cerrada, "paradas": [{"market_id": i, "mercancia": None} for i in ids]}


def test_fijar_guarda_la_ruta_y_la_lista_enseña_cifras_de_hoy(base, tmp_path, escritor):
    comercio = api(base, tmp_path, escritor=escritor)

    respuesta = comercio.fijar_ruta(pedida(101, 202, cerrada=True))
    lista = comercio.rutas_fijadas()

    assert respuesta == {"pendiente": False, "ok": True, "id": 1}
    [fijada] = lista["fijadas"]
    assert (fijada["id"], fijada["cerrada"], fijada["estado"]) == (1, True, "ok")
    assert fijada["resumen"]["ganancia_viaje"] == 1120 * 1_000 + 1120 * 500
    assert [p["estacion"] for p in fijada["paradas"]] == ["E101", "E202"]
    assert lista["en_curso"] is None
    json.dumps(lista)


def test_fijar_otra_vez_la_misma_ruta_no_la_duplica(base, tmp_path, escritor):
    comercio = api(base, tmp_path, escritor=escritor)
    comercio.fijar_ruta(pedida(101, 202, cerrada=True))

    repetida = comercio.fijar_ruta(pedida(202, 101, cerrada=True))

    assert repetida == {"pendiente": False, "ya_fijada": True, "id": 1}
    assert len(comercio.rutas_fijadas()["fijadas"]) == 1


def test_con_el_limite_alcanzado_no_se_fija_otra(base, tmp_path, escritor, monkeypatch):
    monkeypatch.setattr(fijadas, "MAXIMO_DE_RUTAS", 1)
    comercio = api(base, tmp_path, escritor=escritor)
    comercio.fijar_ruta(pedida(101, 202))

    assert comercio.fijar_ruta(pedida(202, 101)) == {"pendiente": False, "error": "limite"}


def test_una_estacion_que_la_base_no_conoce_no_se_fija(base, tmp_path, escritor):
    respuesta = api(base, tmp_path, escritor=escritor).fijar_ruta(pedida(101, 999))

    assert respuesta == {"error": "estacion_desconocida", "campo": "paradas.1"}


@pytest.mark.parametrize("datos", [None, "ruta", {"cerrada": True}, pedida(101), pedida(101, 101)])
def test_una_ruta_mal_formada_se_rechaza_antes_de_tocar_la_base(base, tmp_path, escritor, datos):
    comercio = api(base, tmp_path, escritor=escritor)

    for metodo in (comercio.fijar_ruta, comercio.estimar_ruta):
        assert metodo(datos)["error"] == "parametro"


def test_estimar_una_ruta_no_la_guarda(base, tmp_path, escritor):
    comercio = api(base, tmp_path, escritor=escritor)

    estimada = comercio.estimar_ruta(pedida(101, 202))

    assert estimada["estado"] == "ok"
    assert estimada["cerrada"] is False
    assert estimada["detalle"]["paradas"][0]["estacion"]["market_id"] == 101
    assert comercio.rutas_fijadas()["fijadas"] == []


def test_estimar_una_estacion_desconocida_dice_cual(base, tmp_path):
    respuesta = api(base, tmp_path).estimar_ruta(pedida(999, 101))

    assert respuesta == {"error": "estacion_desconocida", "campo": "paradas.0"}


def test_sin_nave_detectada_no_se_estima(base, tmp_path):
    assert api(base, tmp_path, AQUI).estimar_ruta(pedida(101, 202)) == {"error": "sin_nave"}
    assert api(base, tmp_path, AQUI).rutas_fijadas() == {"error": "sin_nave"}


def test_con_un_journal_de_legacy_no_se_estima(base, tmp_path):
    legacy = replace(AQUI, legacy=True)

    assert api(base, tmp_path, legacy).rutas_fijadas() == {"error": "legacy"}


def test_desfijar_quita_la_elegida(base, tmp_path, escritor):
    comercio = api(base, tmp_path, escritor=escritor)
    comercio.fijar_ruta(pedida(101, 202))

    assert comercio.desfijar_ruta(1)["ok"] is True
    assert comercio.rutas_fijadas()["fijadas"] == []


@pytest.mark.parametrize("id_", [0, -1, True, "1", None, 1.5])
def test_desfijar_rechaza_un_id_que_no_es_un_entero_positivo(base, tmp_path, escritor, id_):
    assert api(base, tmp_path, escritor=escritor).desfijar_ruta(id_) == {
        "error": "parametro",
        "campo": "id",
    }


def test_tras_borrar_los_mercados_la_ruta_sigue_con_sus_nombres_y_sin_precios(
    base, tmp_path, escritor
):
    comercio = api(base, tmp_path, escritor=escritor)
    comercio.fijar_ruta(pedida(101, 202, cerrada=True))
    conexion = sqlite3.connect(base, isolation_level=None)
    for tabla in ("market_prices", "stations", "systems"):
        conexion.execute(f"DELETE FROM {tabla}")  # noqa: S608 - nombres fijos de la prueba
    conexion.close()

    [fijada] = comercio.rutas_fijadas()["fijadas"]

    assert fijada["estado"] == "incompleta"
    assert {t["estado"] for t in fijada["tramos"]} == {"sin_precios"}
    assert [p["estacion"] for p in fijada["paradas"]] == ["E101", "E202"]
    assert fijada["resumen"] is None


@pytest.fixture
def base_del_bucle(tmp_path):
    archivo = tmp_path / "bucle.db"
    conexion = sqlite3.connect(archivo, isolation_level=None)
    esquema.migrar(conexion)
    guardar_el_bucle(conexion)
    sistema(conexion, 1, 0.0, nombre="HIP 45301")
    sistema(conexion, 2, 10.0, nombre="Orishpucho")
    estacion(conexion, ANTONELLI, 1)
    estacion(conexion, BEREGOVOI, 2)
    conexion.execute(
        "UPDATE stations SET nombre = 'Antonelli Arsenal' WHERE market_id = ?", (ANTONELLI,)
    )
    conexion.execute(
        "UPDATE stations SET nombre = 'Beregovoi Colony' WHERE market_id = ?", (BEREGOVOI,)
    )
    vende(conexion, ANTONELLI, "bauxite", 400)
    compra(conexion, BEREGOVOI, "bauxite", 2_000)
    vende(conexion, BEREGOVOI, "titanium", 800)
    compra(conexion, ANTONELLI, "titanium", 1_500)
    conexion.close()
    return archivo


def test_la_ruta_en_curso_sale_del_bucle_del_journal_con_lo_real_y_lo_de_hoy(
    base_del_bucle, tmp_path
):
    comercio = api(base_del_bucle, tmp_path, reloj=lambda: FIN_DEL_BUCLE)

    en_curso = comercio.rutas_fijadas()["en_curso"]

    assert en_curso["cerrada"] is True
    assert en_curso["viajes"] == 14
    assert en_curso["por_hora_real"] > 0
    assert en_curso["estimacion"]["estado"] == "ok"
    assert en_curso["id"] is None
    assert {p["market_id"] for p in en_curso["paradas"]} == {ANTONELLI, BEREGOVOI}


def test_si_la_ruta_en_curso_ya_esta_fijada_lo_dice_con_su_id(base_del_bucle, tmp_path):
    escritor = Escritor(base_del_bucle)
    escritor.iniciar()
    try:
        comercio = api(base_del_bucle, tmp_path, escritor=escritor, reloj=lambda: FIN_DEL_BUCLE)
        fijada = comercio.fijar_ruta(pedida(BEREGOVOI, ANTONELLI, cerrada=True))

        assert comercio.rutas_fijadas()["en_curso"]["id"] == fijada["id"]
    finally:
        escritor.detener()


def test_pasada_la_pausa_de_la_sesion_ya_no_hay_ruta_en_curso(base_del_bucle, tmp_path):
    muy_tarde = datetime(2026, 11, 11, 8, 30, 0, tzinfo=UTC)

    assert (
        api(base_del_bucle, tmp_path, reloj=lambda: muy_tarde).rutas_fijadas()["en_curso"] is None
    )


def test_los_ajustes_de_ruta_en_curso_vienen_con_sus_valores_por_defecto(base, tmp_path):
    ajustes = api(base, tmp_path).ajustes_de_ruta_en_curso()

    assert (ajustes["aviso_mejor"], ajustes["margen_pct"], ajustes["portapapeles"]) == (
        True,
        20.0,
        False,
    )


def test_los_ajustes_de_ruta_en_curso_se_guardan_y_se_leen(base, tmp_path):
    comercio = api(base, tmp_path)

    respuesta = comercio.guardar_ajustes_de_ruta_en_curso(False, 35, True)

    assert respuesta["ok"] is True
    assert comercio.ajustes_de_ruta_en_curso()["margen_pct"] == 35.0
    guardado = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert guardado["comercio"]["ruta_en_curso"] == {
        "aviso_mejor": False,
        "margen_pct": 35.0,
        "portapapeles": True,
    }


def test_guardar_los_ajustes_de_busqueda_no_borra_los_de_ruta_en_curso(base, tmp_path):
    comercio = api(base, tmp_path)
    comercio.guardar_ajustes_de_ruta_en_curso(False, 35, True)

    comercio.guardar_ajustes_de_busqueda(5, ["orbital"])

    assert comercio.ajustes_de_ruta_en_curso()["aviso_mejor"] is False


@pytest.mark.parametrize(
    ("aviso", "margen", "portapapeles", "campo"),
    [
        (1, 20, False, "aviso_mejor"),
        (True, 0, False, "margen_pct"),
        (True, 1001, False, "margen_pct"),
        (True, True, False, "margen_pct"),
        (True, float("nan"), False, "margen_pct"),
        (True, "20", False, "margen_pct"),
        (True, 20, None, "portapapeles"),
    ],
)
def test_ajustes_de_ruta_en_curso_invalidos_dicen_que_campo_falla(
    base, tmp_path, aviso, margen, portapapeles, campo
):
    respuesta = api(base, tmp_path).guardar_ajustes_de_ruta_en_curso(aviso, margen, portapapeles)

    assert respuesta == {"error": "parametro", "campo": campo}
