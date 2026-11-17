import json
import sqlite3

import pytest

from core.db import esquema
from modules.comercio import fijadas
from modules.comercio.fijadas import RutaInvalida
from tests.mercado_de_prueba import base_vacia, estacion, sistema


def ruta(*ids, cerrada=False, mercancia=None) -> dict:
    return {
        "cerrada": cerrada,
        "paradas": [{"market_id": i, "mercancia": mercancia} for i in ids],
    }


def campo_rechazado(datos) -> str:
    with pytest.raises(RutaInvalida) as error:
        fijadas.validar(datos)
    return error.value.campo


@pytest.fixture
def base():
    conexion = base_vacia()
    for numero in range(1, 4):
        sistema(conexion, numero, float(numero))
        estacion(conexion, numero * 100, numero)
    conexion.execute("INSERT INTO commodities (simbolo, rara) VALUES ('gold', 0)")
    return conexion


def test_una_ruta_bien_formada_se_acepta():
    pedida = fijadas.validar(ruta(1, 2, 3, cerrada=True, mercancia="gold"))

    assert pedida.cerrada is True
    assert [p.market_id for p in pedida.paradas] == [1, 2, 3]
    assert pedida.paradas[0].mercancia == "gold"


@pytest.mark.parametrize(
    ("datos", "campo"),
    [
        ("texto", "ruta"),
        ({"cerrada": False}, "ruta"),
        ({**ruta(1, 2), "extra": 1}, "ruta"),
        ({**ruta(1, 2), "cerrada": 1}, "cerrada"),
        (ruta(1), "paradas"),
        (ruta(*range(1, 12)), "paradas"),
        ({"cerrada": False, "paradas": "no"}, "paradas"),
        ({"cerrada": False, "paradas": [1, 2]}, "paradas.0"),
        (
            {"cerrada": False, "paradas": [{"market_id": 1}, {"market_id": 2}]},
            "paradas.0",
        ),
        (
            {"cerrada": False, "paradas": [{"market_id": True, "mercancia": None}] * 2},
            "paradas.0.market_id",
        ),
        (ruta(1, 0), "paradas.1.market_id"),
        (ruta(1, -5), "paradas.1.market_id"),
        (ruta(1, 1.5), "paradas.1.market_id"),
        (ruta(1, 2**63), "paradas.1.market_id"),
        (ruta(1, 1), "paradas.1.market_id"),
        (ruta(1, 2, 2), "paradas.2.market_id"),
        (ruta(1, 2, 1, cerrada=True), "paradas.0.market_id"),
        (ruta(1, 2, mercancia=""), "paradas.0.mercancia"),
        (ruta(1, 2, mercancia="x" * 65), "paradas.0.mercancia"),
        (ruta(1, 2, mercancia=7), "paradas.0.mercancia"),
    ],
)
def test_cada_forma_mala_se_rechaza_con_su_campo(datos, campo):
    assert campo_rechazado(datos) == campo


def test_a_b_a_abierta_es_valida_pero_cerrada_no_repite_la_primera():
    assert fijadas.validar(ruta(1, 2, 1)).cerrada is False
    assert campo_rechazado(ruta(1, 2, 1, cerrada=True)) == "paradas.0.market_id"


def test_un_bucle_tiene_la_misma_clave_empiece_por_donde_empiece():
    assert fijadas.clave(True, [1, 2]) == fijadas.clave(True, [2, 1])
    assert fijadas.clave(True, [3, 1, 2]) == fijadas.clave(True, [1, 2, 3])
    assert fijadas.clave(True, [1, 2, 3]) != fijadas.clave(True, [1, 3, 2])


def test_una_ruta_abierta_se_distingue_de_la_cerrada_y_de_su_inversa():
    assert fijadas.clave(False, [1, 2]) != fijadas.clave(True, [1, 2])
    assert fijadas.clave(False, [1, 2]) != fijadas.clave(False, [2, 1])


def test_una_estacion_repetida_en_un_bucle_no_da_dos_claves_para_la_misma_ruta():
    assert fijadas.clave(True, [1, 2, 1, 3]) == fijadas.clave(True, [1, 3, 1, 2])


def test_completar_pone_estacion_y_sistema_de_la_base(base):
    completa = fijadas.completar(base, fijadas.validar(ruta(100, 200, mercancia="gold")))

    assert completa["paradas"][0] == {
        "market_id": 100,
        "estacion": "E100",
        "sistema": "S1",
        "mercancia": "gold",
    }


def test_una_mercancia_desconocida_se_guarda_como_ninguna(base):
    completa = fijadas.completar(base, fijadas.validar(ruta(100, 200, mercancia="inventada")))

    assert completa["paradas"][0]["mercancia"] is None


def test_una_estacion_que_la_base_no_conoce_dice_en_que_posicion_esta(base):
    with pytest.raises(fijadas.EstacionDesconocida) as error:
        fijadas.completar(base, fijadas.validar(ruta(100, 999)))

    assert error.value.posicion == 1


def fijar(base, *ids, cerrada=False):
    completa = fijadas.completar(base, fijadas.validar(ruta(*ids, cerrada=cerrada)))
    return fijadas.guardar(base, completa, "2026-11-16T10:00:00Z")


def test_fijar_dos_veces_la_misma_ruta_deja_una_fila(base):
    primera = fijar(base, 100, 200, cerrada=True)
    segunda = fijar(base, 200, 100, cerrada=True)

    assert primera[0] == fijadas.ESTADO_NUEVA
    assert segunda == (fijadas.ESTADO_YA_FIJADA, primera[1])
    assert len(fijadas.listar(base)) == 1


def test_el_limite_de_rutas_no_deja_fijar_una_mas(base):
    for numero in range(fijadas.MAXIMO_DE_RUTAS):
        base.execute(
            "INSERT INTO pinned_routes (clave, cerrada, paradas, creada) VALUES (?, 0, '[]', 'x')",
            (f"relleno:{numero}",),
        )

    assert fijar(base, 100, 200) == (fijadas.ESTADO_LIMITE, None)


def test_borrar_quita_solo_la_elegida(base):
    _, primera = fijar(base, 100, 200)
    _, segunda = fijar(base, 100, 300)

    fijadas.borrar(base, primera)

    assert [r["id"] for r in fijadas.listar(base)] == [segunda]


def test_listar_devuelve_de_la_mas_antigua_a_la_mas_nueva_con_sus_paradas(base):
    fijar(base, 100, 200)
    fijar(base, 300, 100, cerrada=True)

    lista = fijadas.listar(base)

    assert [r["cerrada"] for r in lista] == [False, True]
    assert [p["estacion"] for p in lista[1]["paradas"]] == ["E300", "E100"]


@pytest.mark.parametrize(
    "paradas",
    [
        "no es json",
        '{"market_id": 1}',
        "[]",
        '[{"market_id": 1}, {"market_id": 2}]',
        json.dumps([{"market_id": "1", "estacion": "a", "sistema": "b", "mercancia": None}] * 2),
    ],
)
def test_una_fila_con_la_forma_rota_se_salta_sin_romper_la_lista(base, paradas, caplog):
    _, buena = fijar(base, 100, 200)
    base.execute(
        "INSERT INTO pinned_routes (clave, cerrada, paradas, creada) VALUES ('rota', 0, ?, 'x')",
        (paradas,),
    )

    lista = fijadas.listar(base)

    assert [r["id"] for r in lista] == [buena]
    assert "paradas" not in caplog.text or "no se entiende" in caplog.text


def test_una_ruta_fijada_sobrevive_a_borrar_los_mercados(base):
    fijar(base, 100, 200)

    base.execute("DELETE FROM market_prices")
    base.execute("DELETE FROM stations")
    base.execute("DELETE FROM systems")

    lista = fijadas.listar(base)
    assert [p["estacion"] for p in lista[0]["paradas"]] == ["E100", "E200"]


def test_una_ruta_fijada_se_lee_igual_tras_cerrar_y_abrir_la_base(tmp_path):
    ruta_db = tmp_path / "luna.db"
    conexion = sqlite3.connect(ruta_db, isolation_level=None)
    esquema.migrar(conexion)
    sistema(conexion, 1, 0.0)
    sistema(conexion, 2, 1.0)
    estacion(conexion, 100, 1)
    estacion(conexion, 200, 2)
    fijar(conexion, 100, 200, cerrada=True)
    antes = fijadas.listar(conexion)
    conexion.close()

    conexion = sqlite3.connect(ruta_db, isolation_level=None)
    esquema.migrar(conexion)

    assert fijadas.listar(conexion) == antes
    conexion.close()


def test_la_migracion_12_crea_la_tabla_sobre_una_base_de_la_version_11():
    conexion = sqlite3.connect(":memory:", isolation_level=None)
    version_11 = esquema.MIGRACIONES[:11]
    for numero, script in enumerate(version_11, start=1):
        conexion.executescript(f"BEGIN;{script}PRAGMA user_version = {numero};COMMIT;")
    assert esquema.version(conexion) == 11

    esquema.migrar(conexion)

    assert esquema.version(conexion) == 12
    tablas = {f[0] for f in conexion.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "pinned_routes" in tablas
