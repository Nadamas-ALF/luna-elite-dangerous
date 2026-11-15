import json
from pathlib import Path

import pytest

from core.journal import tiempos
from core.journal.tiempos import Cronometro, Muestra

FIXTURES = Path(__file__).parent / "fixtures" / "journal"
VIAJE = [
    json.loads(linea)
    for linea in (FIXTURES / "viaje_tiempos.log").read_text(encoding="utf-8").splitlines()
    if linea.strip()
]


def medir_todo(eventos: list[dict]) -> list[Muestra]:
    crono, muestras = Cronometro(), []
    for evento in eventos:
        crono, nuevas = tiempos.medir(crono, evento)
        muestras += nuevas
    return muestras


def de(tramo: str, muestras: list[Muestra]) -> list[float]:
    return [m.segundos for m in muestras if m.tramo == tramo]


def ev(nombre: str, hora: str, **campos) -> dict:
    return {"timestamp": f"2026-11-10T{hora}Z", "event": nombre, **campos}


def test_un_viaje_real_da_cada_tramo_con_su_duracion():
    muestras = medir_todo(VIAJE)

    # Undocked 03:52:30 → FSDJump 03:53:55; tras Edyth 2, con supercrucero antes de saltar.
    assert de(tiempos.SALIDA, muestras) == [85, 151, 95]
    assert de(tiempos.SALTO, muestras)[:2] == [50, 2053]
    assert len(de(tiempos.SALTO, muestras)) == 8
    # St4r F0x's Salt Shack: SupercruiseExit 05:09:59 → Docked 05:12:30.
    assert de(tiempos.ATRAQUE_ORBITAL, muestras) == [151, 147]
    assert de(tiempos.COMERCIO, muestras) == [241, 1726]
    assert de(tiempos.APROXIMACION_PLANETARIA, muestras) == []


def test_el_supercrucero_lleva_la_distancia_de_la_estacion():
    supercruceros = [m for m in medir_todo(VIAJE) if m.tramo == tiempos.SUPERCRUCERO]

    assert [m.segundos for m in supercruceros] == [1765, 67]
    assert supercruceros[0].distancia_ls == pytest.approx(4.499601)
    assert supercruceros[0].fin == "2026-11-10T05:12:30Z"


def test_un_cierre_del_juego_descarta_lo_que_estaba_a_medias():
    eventos = [
        ev("Undocked", "10:00:00", MarketID=1),
        ev("Shutdown", "10:00:30"),
        ev("LoadGame", "11:00:00"),
        ev("FSDJump", "11:01:00"),
        ev("Docked", "11:05:00", MarketID=2, StationType="Coriolis", DistFromStarLS=100),
    ]

    assert medir_todo(eventos) == []


def test_una_parada_en_el_camino_anula_la_salida_y_el_supercrucero():
    eventos = [
        ev("Undocked", "10:00:00", MarketID=1),
        ev("SupercruiseExit", "10:01:00", BodyType="Planet"),
        ev("SupercruiseEntry", "10:03:00"),
        ev("FSDJump", "10:04:00"),
        ev("SupercruiseExit", "10:06:00", BodyType="Signal"),
        ev("SupercruiseEntry", "10:08:00"),
        ev("SupercruiseExit", "10:09:00", BodyType="Station"),
        ev("Docked", "10:10:00", MarketID=2, StationType="Coriolis", DistFromStarLS=100),
    ]

    muestras = medir_todo(eventos)

    assert de(tiempos.SALIDA, muestras) == []
    assert de(tiempos.SUPERCRUCERO, muestras) == []
    # El atraque sí se mide: desde la última salida de supercrucero.
    assert de(tiempos.ATRAQUE_ORBITAL, muestras) == [60]


def test_la_aproximacion_planetaria_se_mide_aparte():
    eventos = [
        ev("FSDJump", "10:00:00"),
        ev("SupercruiseExit", "10:02:00", BodyType="Planet"),
        ev("Docked", "10:05:00", MarketID=2, StationType="CraterOutpost", DistFromStarLS=50),
    ]

    muestras = medir_todo(eventos)

    assert de(tiempos.APROXIMACION_PLANETARIA, muestras) == [180]
    assert de(tiempos.ATRAQUE_ORBITAL, muestras) == []
    assert de(tiempos.SUPERCRUCERO, muestras) == [120]


def test_el_comercio_solo_cuenta_si_despegas_de_la_misma_estacion():
    eventos = [
        ev("Docked", "10:00:00", MarketID=1, StationType="Coriolis"),
        ev("Undocked", "10:02:00", MarketID=99),
    ]

    assert medir_todo(eventos) == []


@pytest.mark.parametrize(
    "evento",
    [
        {"event": "FSDJump"},
        {"event": "FSDJump", "timestamp": "ayer"},
        {"event": "FSDJump", "timestamp": 12},
    ],
)
def test_una_marca_ilegible_reinicia_sin_romper(evento):
    crono = Cronometro(desatraque=1.0, ultimo_salto=2.0)

    assert tiempos.medir(crono, evento) == (Cronometro(), ())


def test_una_distancia_ilegible_deja_el_atraque_sin_supercrucero():
    eventos = [
        ev("FSDJump", "10:00:00"),
        ev("SupercruiseExit", "10:02:00", BodyType="Station"),
        ev("Docked", "10:03:00", MarketID=2, StationType="Orbis", DistFromStarLS="lejos"),
    ]

    muestras = medir_todo(eventos)

    assert de(tiempos.SUPERCRUCERO, muestras) == []
    assert de(tiempos.ATRAQUE_ORBITAL, muestras) == [60]


@pytest.mark.parametrize("campo", ["Taxi", "Multicrew"])
def test_un_viaje_en_taxi_o_en_la_nave_de_otro_no_da_muestras(campo):
    eventos = [
        ev("Docked", "09:58:00", MarketID=1, StationType="Coriolis"),
        ev("Undocked", "10:00:00", MarketID=1, **{campo: True}),
        ev("FSDJump", "10:04:00", **{campo: True}),
        ev("SupercruiseExit", "10:08:00", BodyType="Station", **{campo: True}),
        ev(
            "Docked",
            "10:10:00",
            MarketID=2,
            StationType="Coriolis",
            DistFromStarLS=50,
            **{campo: True},
        ),
    ]

    assert medir_todo(eventos) == []


def test_una_distancia_no_finita_no_da_supercrucero():
    eventos = [
        ev("FSDJump", "10:00:00"),
        ev("SupercruiseExit", "10:02:00", BodyType="Station"),
        ev("Docked", "10:03:00", MarketID=2, StationType="Orbis", DistFromStarLS=float("nan")),
    ]

    assert de(tiempos.SUPERCRUCERO, medir_todo(eventos)) == []
