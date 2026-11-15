import json
from pathlib import Path

import pytest

from core.journal import comercio, sesiones
from core.state.estado import Estado, aplicar

FIXTURES = Path(__file__).parent / "fixtures" / "journal"
BUCLE = [
    json.loads(linea)
    for linea in (FIXTURES / "bucle_comercio.log").read_text(encoding="utf-8").splitlines()
    if linea.strip()
]


def recorrer(eventos: list[dict]) -> list[sesiones.Bloque]:
    """Los bloques cerrados y, al final, el que sigue abierto."""
    estado, actividad, bloques = Estado(), sesiones.Actividad(), []
    for evento in eventos:
        estado = aplicar(estado, evento)
        hecha = comercio.operacion(estado, evento)
        actividad, cerrado = sesiones.anotar(actividad, estado, evento, hecha)
        if cerrado:
            bloques.append(cerrado)
    if actividad.bloque:
        bloques.append(actividad.bloque)
    return bloques


def ev(nombre: str, hora: str, **campos) -> dict:
    return {"timestamp": f"2026-11-10T{hora}Z", "event": nombre, **campos}


def partida(hora: str) -> list[dict]:
    return [
        ev("Fileheader", hora, part=1, gameversion="4.4.2.1"),
        ev("Commander", hora, FID="F0000001", Name="CMDR Prueba"),
        ev("Materials", hora),
        ev("LoadGame", hora, FID="F0000001", Commander="CMDR Prueba", Credits=1000),
    ]


def test_una_partida_real_es_un_bloque_cerrado_con_su_comercio():
    bloques = recorrer(BUCLE)

    assert len(bloques) == 1
    bloque = bloques[0]
    assert (bloque.fid, bloque.inicio, bloque.fin) == (
        "F0000001",
        "2026-11-10T03:41:24Z",
        "2026-11-10T08:22:30Z",
    )
    assert (bloque.partida, bloque.pausa_previa, bloque.cerrado) == (bloque.inicio, None, True)
    assert (bloque.toneladas, bloque.saltos) == (14 * 1120, 54)
    assert bloque.ganancia == 312_382_560
    assert bloque.saldo_fin - bloque.saldo_inicio == bloque.ganancia


def test_lo_que_llega_antes_de_cargar_la_partida_no_abre_un_bloque():
    bloques = recorrer([*partida("10:00:00"), ev("FSDJump", "10:05:00")])

    assert [(b.inicio, b.saltos, b.cerrado) for b in bloques] == [
        ("2026-11-10T10:00:00Z", 1, False)
    ]


def test_una_pausa_de_una_hora_o_mas_corta_el_bloque_dentro_de_la_partida():
    bloques = recorrer([
        *partida("10:00:00"),
        ev("FSDJump", "10:05:00"),
        ev("FSDJump", "11:05:00"),
        ev("FSDJump", "11:10:00"),
        ev("Shutdown", "11:20:00"),
    ])

    assert [(b.inicio, b.fin, b.pausa_previa, b.saltos, b.cerrado) for b in bloques] == [
        ("2026-11-10T10:00:00Z", "2026-11-10T10:05:00Z", None, 1, True),
        ("2026-11-10T11:05:00Z", "2026-11-10T11:20:00Z", 3600, 2, True),
    ]
    assert {b.partida for b in bloques} == {"2026-11-10T10:00:00Z"}


def test_una_pausa_corta_no_corta_el_bloque():
    bloques = recorrer([*partida("10:00:00"), ev("FSDJump", "10:05:00"), ev("FSDJump", "11:04:59")])

    assert len(bloques) == 1


def test_un_journal_nuevo_sin_cierre_termina_el_bloque_en_su_ultimo_evento():
    bloques = recorrer([*partida("10:00:00"), ev("FSDJump", "10:05:00"), *partida("10:30:00")])

    assert [(b.inicio, b.fin, b.partida, b.cerrado) for b in bloques] == [
        ("2026-11-10T10:00:00Z", "2026-11-10T10:05:00Z", "2026-11-10T10:00:00Z", True),
        ("2026-11-10T10:30:00Z", "2026-11-10T10:30:00Z", "2026-11-10T10:30:00Z", False),
    ]


def test_la_continuacion_de_un_journal_no_corta_el_bloque():
    bloques = recorrer([
        *partida("10:00:00"),
        ev("FSDJump", "10:05:00"),
        ev("Fileheader", "10:06:00", part=2),
        ev("FSDJump", "10:07:00"),
    ])

    assert [(b.saltos, b.cerrado) for b in bloques] == [(2, False)]


def test_empezar_a_leer_a_mitad_de_partida_abre_un_bloque_con_el_primer_evento():
    estado = Estado(fid="F0000001", creditos=500)
    actividad, _ = sesiones.anotar(sesiones.Actividad(), estado, ev("FSDJump", "10:00:00"), None)

    assert (actividad.bloque.inicio, actividad.bloque.saltos) == ("2026-11-10T10:00:00Z", 1)


def test_las_ventas_suman_ganancia_y_toneladas_y_las_compras_no():
    venta = comercio.Operacion(
        "2026-11-10T10:10:00Z", 1, "A", "S", "gold", True, 100, 10_000, 1_000_000, 9_000
    )
    compra = comercio.Operacion("2026-11-10T10:05:00Z", 1, "A", "S", "gold", False, 100, 9_000, 0)
    estado = Estado(fid="F0000001", creditos=500)
    actividad, _ = sesiones.anotar(sesiones.Actividad(), estado, ev("LoadGame", "10:00:00"), None)
    actividad, _ = sesiones.anotar(actividad, estado, ev("MarketBuy", "10:05:00"), compra)
    actividad, _ = sesiones.anotar(actividad, estado, ev("MarketSell", "10:10:00"), venta)

    assert (actividad.bloque.ganancia, actividad.bloque.toneladas) == (100_000, 100)


@pytest.mark.parametrize("marca", [None, "ayer", 5])
def test_un_evento_sin_marca_legible_se_ignora(marca):
    actividad = sesiones.Actividad()
    evento = {"timestamp": marca, "event": "LoadGame"}

    assert sesiones.anotar(actividad, Estado(fid="F1"), evento, None) == (actividad, None)


def test_legacy_no_da_bloques():
    actividad, cerrado = sesiones.anotar(
        sesiones.Actividad(), Estado(fid="F1", legacy=True), ev("LoadGame", "10:00:00"), None
    )

    assert (actividad.bloque, cerrado) == (None, None)
