import sqlite3
from datetime import UTC, datetime

import pytest

from core.db import comandante, esquema
from core.journal import sesiones
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


def test_un_tramo_que_cruza_una_pausa_suma_ganancia_pero_no_cuenta_en_la_cr_h(conexion):
    """E-18: la pausa no es tiempo de ruta; sin ella, la Cr/h real saldría más baja."""
    salida, llegada, segundos, ganancia = conexion.execute(
        "SELECT salida, llegada, segundos, ganancia FROM trade_legs "
        "WHERE destino_estacion = 'Beregovoi Colony' ORDER BY salida LIMIT 1"
    ).fetchone()
    sin_pausa = rendimiento.rutas(conexion, "F0000001", None, lambda _: timing.POR_DEFECTO)
    pausas = [llegada]  # el bloque tras la pausa empieza dentro del tramo

    rutas = rendimiento.rutas(conexion, "F0000001", None, lambda _: timing.POR_DEFECTO, pausas)

    antes, ida = sin_pausa[0], rutas[0]
    assert (ida.viajes, ida.ganancia, ida.con_pausa) == (7, antes.ganancia, 1)
    assert ida.ganancia_medida == antes.ganancia - ganancia
    assert ida.segundos == antes.segundos - segundos
    assert ida.comparacion.tramos == 6
    assert rendimiento.cruza_una_pausa(pausas, salida, llegada)
    assert sum(r.con_pausa for r in rutas) == 1


def test_una_pausa_fuera_del_tramo_no_lo_toca():
    pausas = rendimiento.pausas_de(PARTIDA)

    assert pausas == ["2026-11-10T12:30:00Z", "2026-11-10T18:00:00Z"]
    assert not rendimiento.cruza_una_pausa(pausas, "2026-11-10T10:10:00Z", "2026-11-10T10:40:00Z")
    assert not rendimiento.cruza_una_pausa(pausas, "2026-11-10T12:30:00Z", "2026-11-10T12:50:00Z")
    assert rendimiento.cruza_una_pausa(pausas, "2026-11-10T10:50:00Z", "2026-11-10T12:40:00Z")


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


# --- Informe: historial sin sesiones vacías y comparación con la anterior ---

AHORA = datetime(2026, 11, 20, 12, tzinfo=UTC)


def en_dia(dia: int, ganancia: int, **cambios) -> sesiones.Bloque:
    """Un bloque de una hora, de las 10:00 a las 11:00 del día de noviembre dado."""
    inicio = f"2026-11-{dia:02d}T10:00:00Z"
    datos = {
        "fid": "F0000001",
        "inicio": inicio,
        "fin": f"2026-11-{dia:02d}T11:00:00Z",
        "partida": inicio,
        "pausa_previa": None,
        "saldo_inicio": 0,
        "saldo_fin": ganancia,
        "ganancia": ganancia,
        "toneladas": 10,
        "saltos": 1,
        "cerrado": True,
    }
    return sesiones.Bloque(**{**datos, **cambios})


@pytest.fixture
def base():
    conexion = sqlite3.connect(":memory:")
    esquema.migrar(conexion)
    comandante.registrar_comandante(conexion, "F0000001", "CMDR Prueba", "2026-11-10")
    # Día 10: 100 000/h. Día 12: sin ganancia. Día 14: 150 000/h.
    comandante.guardar_bloques(conexion, [en_dia(10, 100_000), en_dia(12, 0), en_dia(14, 150_000)])
    yield conexion
    conexion.close()


def informe(conexion, sesion=None, omitir=True):
    return rendimiento.informe(conexion, "F0000001", sesion, (1, False), AHORA, omitir, 5_000_000)


def inicios(respuesta) -> list[str]:
    return [s["inicio"][:10] for s in respuesta["sesiones"]]


def test_omitir_vacias_esconde_las_sesiones_sin_ganancia_de_la_lista(base):
    assert inicios(informe(base)) == ["2026-11-14", "2026-11-10"]
    assert inicios(informe(base, omitir=False)) == ["2026-11-14", "2026-11-12", "2026-11-10"]


def test_una_sesion_oculta_no_se_puede_elegir(base):
    with pytest.raises(rendimiento.SesionDesconocida):
        informe(base, "2026-11-12T10:00:00Z")


def test_todo_cuenta_las_sesiones_vacias_aunque_la_lista_las_omita(base):
    resumen = informe(base, rendimiento.TODO)["resumen"]

    assert resumen["sesiones"] == 3
    assert resumen["segundos"] == 3 * 3600


def test_la_sesion_en_curso_no_se_omite_aunque_no_haya_vendido(base):
    ahora = datetime(2026, 11, 16, 10, 30, tzinfo=UTC)
    comandante.guardar_bloques(base, [en_dia(16, 0, cerrado=False)])
    respuesta = rendimiento.informe(base, "F0000001", None, (1, False), ahora, True, None)

    assert inicios(respuesta)[0] == "2026-11-16"
    assert respuesta["sesiones"][0]["en_curso"]


def test_compara_con_la_ultima_sesion_anterior_que_gano_algo(base):
    contra = informe(base)["resumen"]["contra_anterior"]

    # La del día 12 no ganó nada: la anterior comparable es la del día 10.
    assert contra["inicio"] == "2026-11-10T10:00:00Z"
    assert contra["por_hora"] == pytest.approx(100_000)
    assert contra["variacion"] == pytest.approx(0.5)


def test_la_comparacion_no_depende_de_la_casilla(base):
    asi = informe(base, omitir=False)["resumen"]["contra_anterior"]

    assert asi == informe(base)["resumen"]["contra_anterior"]


def test_sin_sesion_anterior_con_ganancia_no_se_compara(base):
    assert informe(base, "2026-11-10T10:00:00Z")["resumen"]["contra_anterior"] is None


def test_todo_no_se_compara(base):
    assert informe(base, rendimiento.TODO)["resumen"]["contra_anterior"] is None


def test_lleva_el_saldo_actual_y_el_ajuste(base):
    respuesta = informe(base)

    assert respuesta["saldo_actual"] == 5_000_000
    assert respuesta["ajuste"]["omitir_vacias"] is True


def test_cuenta_las_sesiones_ocultas(base):
    assert informe(base)["ocultas"] == 1
    assert informe(base, omitir=False)["ocultas"] == 0
