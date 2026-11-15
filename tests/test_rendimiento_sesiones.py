import sqlite3

import pytest

from core.db import esquema
from modules.comercio import rendimiento, timing
from modules.comercio.rendimiento import Bloque
from tests.bucle_de_prueba import guardar_el_bucle


def bloque(inicio: str, fin: str, pausa: float | None = None, **cambios) -> Bloque:
    datos = {
        "inicio": f"2026-11-10T{inicio}Z",
        "fin": f"2026-11-10T{fin}Z",
        "partida": "2026-11-10T10:00:00Z",
        "pausa_previa": pausa,
        "saldo_inicio": 100,
        "saldo_fin": 200,
        "ganancia": 1000,
        "toneladas": 10,
        "saltos": 2,
        "cerrado": True,
    }
    return Bloque(**{**datos, **cambios})


# Una partida con dos pausas: 1,5 h y 5 h.
PARTIDA = [
    bloque("10:00:00", "11:00:00"),
    bloque("12:30:00", "13:00:00", pausa=5400.0),
    bloque("18:00:00", "19:00:00", pausa=18000.0, cerrado=False, saldo_fin=900),
]


@pytest.mark.parametrize(
    ("horas", "por_partida", "esperadas"),
    [(1, False, 3), (2, False, 2), (6, False, 1), (1, True, 1)],
)
def test_el_umbral_decide_que_pausas_parten_la_sesion(horas, por_partida, esperadas):
    assert len(rendimiento.unir(PARTIDA, horas, por_partida)) == esperadas


def test_una_sesion_unida_suma_sus_bloques_y_cuenta_las_pausas_de_dentro():
    (sesion,) = rendimiento.unir(PARTIDA, 6, False)

    assert (sesion.inicio, sesion.fin) == ("2026-11-10T10:00:00Z", "2026-11-10T19:00:00Z")
    assert (sesion.ganancia, sesion.toneladas, sesion.saltos, sesion.bloques) == (3000, 30, 6, 3)
    assert (sesion.saldo_inicio, sesion.saldo_fin) == (100, 900)
    assert sesion.segundos == 9 * 3600
    assert sesion.abierta


def test_dos_partidas_nunca_se_unen_aunque_esten_seguidas():
    otra = bloque("11:10:00", "12:00:00", partida="2026-11-10T11:10:00Z")

    assert len(rendimiento.unir([PARTIDA[0], otra], 12, True)) == 2


@pytest.fixture
def conexion():
    conexion = sqlite3.connect(":memory:")
    esquema.migrar(conexion)
    guardar_el_bucle(conexion)
    yield conexion
    conexion.close()


def test_un_bucle_da_una_ruta_por_sentido_con_su_comparacion(conexion):
    rutas = rendimiento.rutas(conexion, "F0000001", None, lambda _: timing.POR_DEFECTO)

    assert [(r.origen[0], r.destino[0], r.viajes, r.mercancias) for r in rutas] == [
        ("Antonelli Arsenal", "Beregovoi Colony", 7, ("bauxite",)),
        ("Beregovoi Colony", "Antonelli Arsenal", 7, ("titanium",)),
    ]
    ida = rutas[0]
    assert ida.ganancia == sum(
        [40231520, 39896640, 39586400, 39098080, 38731840, 38270400, 37898560]
    )
    assert ida.segundos == 571 + 519 + 1634 + 597 + 572 + 699 + 573
    # 62,9 ly con 32 ly de rango: 2 saltos en línea recta. Los ls cambian un poco
    # entre visitas porque los cuerpos se mueven.
    estimado = sum(timing.POR_DEFECTO.tramo(2, ls, False) for ls in ls_de_llegada(conexion))
    assert ida.comparacion.tramos == 7
    assert ida.comparacion.segundos_estimados == pytest.approx(estimado)
    assert ida.comparacion.segundos_reales == ida.segundos


def ls_de_llegada(conexion: sqlite3.Connection) -> list[float]:
    filas = conexion.execute(
        "SELECT distancia_ls FROM trade_legs WHERE destino_estacion = 'Beregovoi Colony'"
    )
    return [ls for (ls,) in filas]


def test_el_periodo_limita_los_tramos(conexion):
    periodo = ("2026-11-10T06:00:00Z", "2026-11-10T06:20:00Z")

    rutas = rendimiento.rutas(conexion, "F0000001", periodo, lambda _: timing.POR_DEFECTO)

    assert sum(r.viajes for r in rutas) == 3


def test_un_tramo_sin_posicion_no_entra_en_la_comparacion(conexion):
    conexion.execute("UPDATE trade_legs SET distancia_ly = NULL WHERE salida < '2026-11-10T06:20'")

    rutas = rendimiento.rutas(conexion, "F0000001", None, lambda _: timing.POR_DEFECTO)

    assert sum(r.viajes for r in rutas) == 14
    assert sum(r.comparacion.tramos for r in rutas) == 11


def test_lo_vendido_por_mercancia(conexion):
    vendidas = rendimiento.mercancias(conexion, "F0000001", None)

    assert [(m.simbolo, m.ventas, m.toneladas, m.sin_precio_de_compra) for m in vendidas] == [
        ("bauxite", 7, 7 * 1120, 0),
        ("titanium", 7, 7 * 1120, 0),
    ]
    assert sum(m.ganancia for m in vendidas) == 312_382_560


def test_una_venta_sin_precio_de_compra_cuenta_aparte(conexion):
    conexion.execute("UPDATE trades SET precio_medio_compra = 0 WHERE commodity = 'titanium'")

    titanio = next(
        m for m in rendimiento.mercancias(conexion, "F0000001", None) if m.simbolo == "titanium"
    )

    assert (titanio.ganancia, titanio.sin_precio_de_compra) == (0, 7)


def test_por_hora_sin_tiempo_no_da_cifra():
    assert rendimiento.por_hora(1000, 0) is None
    assert rendimiento.por_hora(1000, 1800) == 2000
