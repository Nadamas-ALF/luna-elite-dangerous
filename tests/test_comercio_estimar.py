import pytest

from modules.comercio import estimar, fijadas, timing
from modules.comercio.engine import candidatos, rutas
from modules.comercio.engine.calculo import Curva
from modules.comercio.engine.perfil import PerfilInvalido
from tests.mercado_de_prueba import (
    AHORA,
    base_vacia,
    compra,
    estacion,
    perfil,
    sistema,
    vende,
)

CURVA = Curva()
TIEMPOS = timing.POR_DEFECTO
ORIGEN = (0.0, 0.0, 0.0)


@pytest.fixture
def base():
    conexion = base_vacia()
    for numero in range(1, 5):
        sistema(conexion, numero, 10.0 * numero)
        estacion(conexion, numero * 100, numero)
    conexion.execute("INSERT INTO commodities (simbolo, nombre_es, rara) VALUES ('gold', 'Oro', 0)")
    conexion.execute("INSERT INTO commodities (simbolo, nombre_es, rara) VALUES ('tea', 'Té', 0)")
    # Oro de la 100 a la 200 y té de la 200 a la 100: un bucle bueno en las dos direcciones.
    vende(conexion, 100, "gold", 9_000)
    compra(conexion, 200, "gold", 30_000)
    vende(conexion, 200, "tea", 1_000)
    compra(conexion, 100, "tea", 5_000)
    yield conexion
    conexion.close()


def ruta(base, *ids, cerrada=False, mercancias=None) -> dict:
    mercancias = mercancias or [None] * len(ids)
    pedida = {
        "cerrada": cerrada,
        "paradas": [{"market_id": i, "mercancia": m} for i, m in zip(ids, mercancias, strict=True)],
    }
    return fijadas.completar(base, fijadas.validar(pedida))


def estimada(base, datos, **cambios):
    contexto = estimar.leer_contexto(
        base,
        {x["market_id"] for x in datos["paradas"]},
        AHORA,
        ORIGEN,
        perfil(**cambios),
        CURVA,
        TIEMPOS,
    )
    return estimar.estimar(contexto, datos)


def test_un_salto_da_las_mismas_cifras_que_la_busqueda_sin_filtros(base):
    p = perfil()
    cargados = candidatos.cargar(base, p, ORIGEN, AHORA)
    desde_100 = [
        t for t in rutas.un_salto(cargados, p, CURVA, TIEMPOS) if t.compra.estacion.market_id == 100
    ]
    buscado = max(desde_100, key=lambda t: t.puntuacion)

    resultado = estimada(base, ruta(base, 100, 200))

    assert resultado["estado"] == estimar.ESTADO_OK
    assert resultado["resumen"]["ganancia_viaje"] == buscado.ganancia_viaje
    assert resultado["resumen"]["segundos"] == pytest.approx(buscado.segundos)
    assert resultado["resumen"]["ganancia_hora"] == pytest.approx(buscado.ganancia_hora)


def test_un_bucle_da_las_mismas_cifras_que_el_motor(base):
    p = perfil()
    cargados = candidatos.cargar(base, p, ORIGEN, AHORA)
    [buscado] = rutas.bucle(cargados, p, CURVA, TIEMPOS)

    resultado = estimada(base, ruta(base, 100, 200, cerrada=True))

    assert resultado["resumen"]["ganancia_viaje"] == buscado.ganancia_viaje
    assert resultado["resumen"]["ganancia_hora"] == pytest.approx(buscado.ganancia_hora)
    assert resultado["detalle"]["cerrada"] is True
    assert len(resultado["detalle"]["paradas"]) == 2


def test_una_ruta_de_cuatro_paradas_cerrada_suma_sus_cuatro_tramos(base):
    vende(base, 300, "gold", 9_000)
    compra(base, 400, "gold", 20_000)
    vende(base, 400, "tea", 1_000)
    compra(base, 300, "tea", 4_000)

    resultado = estimada(base, ruta(base, 100, 200, 300, 400, cerrada=True))

    assert resultado["estado"] == estimar.ESTADO_OK
    assert len(resultado["tramos"]) == 4
    assert len(resultado["detalle"]["paradas"]) == 4
    total = sum(p["vender"][0]["ganancia"] for p in resultado["detalle"]["paradas"])
    assert resultado["resumen"]["ganancia_viaje"] == total


def test_sin_estaciones_ni_precios_cada_tramo_dice_que_no_hay_precios_pero_la_ruta_conserva_nombres(
    base,
):
    datos = ruta(base, 100, 200, cerrada=True)
    base.execute("DELETE FROM market_prices")
    base.execute("DELETE FROM stations")
    base.execute("DELETE FROM systems")

    resultado = estimada(base, datos)

    assert resultado["estado"] == estimar.ESTADO_INCOMPLETA
    assert [t["estado"] for t in resultado["tramos"]] == [estimar.TRAMO_SIN_PRECIOS] * 2
    assert [p["estacion"] for p in resultado["paradas"]] == ["E100", "E200"]
    assert resultado["detalle"] is None
    assert resultado["resumen"] is None


def test_una_estacion_sin_precios_marca_solo_los_tramos_que_la_tocan(base):
    base.execute("DELETE FROM market_prices WHERE market_id = 200")

    resultado = estimada(base, ruta(base, 100, 200, 300))

    assert [t["estado"] for t in resultado["tramos"]] == [estimar.TRAMO_SIN_PRECIOS] * 2


def test_un_tramo_con_precios_y_sin_ganancia_sale_sin_trato(base):
    compra(base, 300, "gold", 8_000)

    resultado = estimada(base, ruta(base, 100, 300))

    assert [t["estado"] for t in resultado["tramos"]] == [estimar.TRAMO_SIN_TRATO]
    assert resultado["resumen"] is None


def test_una_plataforma_pequena_marca_la_estacion_donde_la_nave_no_cabe(base):
    base.execute("UPDATE stations SET plataforma = 'S' WHERE market_id = 200")

    resultado = estimada(base, ruta(base, 100, 200), plataforma="L")

    assert [p["no_cabe"] for p in resultado["paradas"]] == [False, True]
    assert resultado["estado"] == estimar.ESTADO_OK


def test_una_mercancia_distinta_de_la_fijada_se_informa(base):
    resultado = estimada(base, ruta(base, 100, 200, mercancias=["tea", None]))

    [tramo] = resultado["tramos"]
    assert tramo["cambiada"] is True
    assert tramo["mercancia"]["simbolo"] == "gold"
    assert tramo["mercancia_fijada"] == {"simbolo": "tea", "nombre": "Té"}


def test_la_misma_mercancia_que_la_fijada_no_se_marca_como_cambiada(base):
    resultado = estimada(base, ruta(base, 100, 200, mercancias=["gold", None]))

    assert resultado["tramos"][0]["cambiada"] is False


def test_un_dato_viejo_o_raro_no_excluye_la_estacion(base):
    base.execute("UPDATE market_prices SET observado = '2026-01-01T00:00:00Z'")
    base.execute("UPDATE commodities SET rara = 1 WHERE simbolo = 'gold'")

    resultado = estimada(base, ruta(base, 100, 200))

    assert resultado["estado"] == estimar.ESTADO_OK
    assert resultado["resumen"]["confianza"] == CURVA.minimo


def test_el_perfil_de_la_nave_quita_los_filtros_de_busqueda():
    datos = perfil().a_dict() | {"ganancia_min": 5_000, "tipos": ["orbital"], "raras": False}

    p = estimar.perfil_de_la_nave(datos, 7, "Sol", 1_000)

    assert p.ganancia_min == 0
    assert p.raras is True
    assert len(p.tipos) == 5
    assert p.capacidad == 100
    assert p.creditos == 1_000


def test_sin_nave_el_perfil_no_se_puede_construir():
    with pytest.raises(PerfilInvalido):
        estimar.perfil_de_la_nave({"limitar_saldo": True}, 7, "Sol", None)
