import json
import shutil
import time
from pathlib import Path

import pytest

from core import events
from core.config import ajustes
from core.db.escritor import Escritor, abrir_lectura
from core.journal import archivos
from core.nucleo import Nucleo
from core.state import vista

FIXTURES = Path(__file__).parent / "fixtures" / "journal"
NOMBRE = "Journal.2026-11-10T033327.01.log"


def esperar(condicion, segundos: float = 10.0) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.02)
    return False


def anadir(archivo: Path, evento: dict) -> None:
    with archivo.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(evento) + "\n")


@pytest.fixture
def juego(tmp_path):
    carpeta = tmp_path / "juego"
    carpeta.mkdir()
    return carpeta


@pytest.fixture
def config(tmp_path, juego):
    ruta = tmp_path / "config.json"
    ajustes.guardar_carpeta_journal(ruta, str(juego))
    return ruta


@pytest.fixture
def arrancar():
    activos = []

    def _arrancar(config, escritor=None):
        bus = events.Bus()
        nucleo = Nucleo(config, bus, escritor)
        nucleo.iniciar()
        activos.append(nucleo)
        return nucleo, bus

    yield _arrancar
    for nucleo in activos:
        nucleo.detener()


def test_reconstruye_el_estado_de_un_journal_existente(juego, config, arrancar):
    shutil.copy(FIXTURES / "sesion_comercio.log", juego / NOMBRE)

    nucleo, _ = arrancar(config)

    assert esperar(lambda: nucleo.estado().comandante == "CMDR Prueba")
    assert nucleo.estado().sistema == "Col 285 Sector HB-C b14-2"
    assert nucleo.estado_del_journal() == vista.JOURNAL_LEYENDO


def test_sin_carpeta_de_journal_lo_dice(tmp_path, monkeypatch, arrancar):
    monkeypatch.setattr("core.journal.carpeta.por_defecto", lambda: None)

    nucleo, _ = arrancar(tmp_path / "config.json")

    assert esperar(lambda: nucleo.estado_del_journal() == vista.JOURNAL_SIN_CARPETA)


def test_carpeta_sin_journals_lo_dice(config, arrancar):
    nucleo, _ = arrancar(config)

    assert esperar(lambda: nucleo.estado_del_journal() == vista.JOURNAL_SIN_ARCHIVOS)


def test_un_evento_nuevo_llega_al_estado_y_al_bus_en_menos_de_dos_segundos(juego, config, arrancar):
    journal = juego / NOMBRE
    shutil.copy(FIXTURES / "sesion_comercio.log", journal)
    nucleo, bus = arrancar(config)
    recibidos = []
    bus.suscribir(events.DESATRACADO, recibidos.append)
    assert esperar(lambda: nucleo.estado().estacion is not None)

    inicio = time.monotonic()
    anadir(journal, {"timestamp": "2026-11-12T10:00:00Z", "event": "Undocked"})

    assert esperar(lambda: nucleo.estado().estacion is None, segundos=2.0)
    assert time.monotonic() - inicio < 2.0
    assert esperar(lambda: recibidos == [None])


def test_cambiar_de_nave_publica_el_evento(juego, config, arrancar):
    journal = juego / NOMBRE
    shutil.copy(FIXTURES / "sesion_comercio.log", journal)
    nucleo, bus = arrancar(config)
    cambios = []
    bus.suscribir(events.NAVE_CAMBIADA, cambios.append)
    assert esperar(lambda: nucleo.estado().nave is not None)
    loadout = next(
        json.loads(linea)
        for linea in journal.read_text(encoding="utf-8").splitlines()
        if '"Loadout"' in linea
    )

    anadir(journal, {**loadout, "ShipID": 3, "Ship": "python", "CargoCapacity": 192})

    assert esperar(lambda: len(cambios) == 1)
    assert nucleo.estado().nave.simbolo == "python"


def test_cargo_json_se_lee_cuando_el_juego_lo_reescribe(juego, config, arrancar):
    shutil.copy(FIXTURES / "sesion_comercio.log", juego / NOMBRE)
    nucleo, bus = arrancar(config)
    cambios = []
    bus.suscribir(events.CARGA_CAMBIADA, cambios.append)
    assert esperar(lambda: nucleo.estado().carga == ())
    inventario = [{"Name": "gold", "Name_Localised": "Oro", "Count": 5}]

    (juego / archivos.CARGO).write_text(
        json.dumps({"event": "Cargo", "Vessel": "Ship", "Count": 5, "Inventory": inventario}),
        encoding="utf-8",
    )

    assert esperar(lambda: nucleo.estado().carga and nucleo.estado().carga[0].nombre == "Oro")
    assert len(cambios) == 1


def test_un_archivo_a_medio_escribir_se_reintenta(juego, config, arrancar):
    shutil.copy(FIXTURES / "sesion_comercio.log", juego / NOMBRE)
    (juego / archivos.STATUS).write_text('{"event": "Sta', encoding="utf-8")
    nucleo, _ = arrancar(config)
    assert esperar(lambda: nucleo.estado().comandante is not None)

    (juego / archivos.STATUS).write_text(
        json.dumps({"event": "Status", "Fuel": {"FuelMain": 9.5}}), encoding="utf-8"
    )

    assert esperar(lambda: nucleo.estado().combustible == 9.5)


def test_un_journal_legacy_se_marca(juego, config, arrancar):
    shutil.copy(FIXTURES / "legacy_sintetico.log", juego / "Journal.2021-03-01T100000.01.log")

    nucleo, _ = arrancar(config)

    assert esperar(lambda: nucleo.estado().legacy is True)


def test_cambiar_la_carpeta_reconstruye_desde_cero(tmp_path, juego, config, arrancar):
    shutil.copy(FIXTURES / "sesion_comercio.log", juego / NOMBRE)
    otra = tmp_path / "otra"
    otra.mkdir()
    shutil.copy(FIXTURES / "legacy_sintetico.log", otra / "Journal.2021-03-01T100000.01.log")
    nucleo, _ = arrancar(config)
    assert esperar(lambda: nucleo.estado().legacy is False)

    ajustes.guardar_carpeta_journal(config, str(otra))
    nucleo.reiniciar_journal()

    assert esperar(lambda: nucleo.estado().legacy is True)


def test_cambiar_a_una_carpeta_sin_journals_olvida_el_estado_anterior(
    tmp_path, juego, config, arrancar
):
    shutil.copy(FIXTURES / "sesion_comercio.log", juego / NOMBRE)
    vacia = tmp_path / "vacia"
    vacia.mkdir()
    nucleo, _ = arrancar(config)
    assert esperar(lambda: nucleo.estado().comandante == "CMDR Prueba")

    ajustes.guardar_carpeta_journal(config, str(vacia))
    nucleo.reiniciar_journal()

    assert esperar(lambda: nucleo.estado().comandante is None)
    assert esperar(lambda: nucleo.estado_del_journal() == vista.JOURNAL_SIN_ARCHIVOS)


def test_guarda_comandante_y_nave_en_la_base(tmp_path, juego, config, arrancar):
    shutil.copy(FIXTURES / "sesion_comercio.log", juego / NOMBRE)
    ruta_base = tmp_path / "luna.db"
    escritor = Escritor(ruta_base)
    escritor.iniciar()
    nucleo, _ = arrancar(config, escritor)
    assert esperar(lambda: nucleo.estado().nave is not None)
    nucleo.detener()
    escritor.detener()

    conexion = abrir_lectura(ruta_base)
    try:
        comandantes = conexion.execute("SELECT fid, nombre FROM commanders").fetchall()
        modelo, capacidad, plataforma, vacio = conexion.execute(
            "SELECT modelo, capacidad_carga, plataforma, rango_vacio FROM ships"
        ).fetchone()
    finally:
        conexion.close()
    assert comandantes == [("F0000001", "CMDR Prueba")]
    assert (modelo, capacidad, plataforma) == ("panthermkii", 1120, "L")
    assert abs(vacio - 49.302464) < 0.001


def test_las_naves_de_dos_comandantes_se_guardan_con_su_comandante(
    tmp_path, juego, config, arrancar
):
    """Una cuenta alternativa en los últimos días no debe perder las naves de la otra."""
    original = (FIXTURES / "sesion_comercio.log").read_text(encoding="utf-8")
    for nombre, fid in (
        ("Journal.2026-11-10T033327.01.log", "F0000001"),
        ("Journal.2026-11-11T033327.01.log", "F0000002"),
    ):
        (juego / nombre).write_text(original.replace("F0000001", fid), encoding="utf-8")
    escritor = Escritor(tmp_path / "luna.db")
    escritor.iniciar()
    nucleo, _ = arrancar(config, escritor)
    assert esperar(lambda: nucleo.estado().fid == "F0000002")
    nucleo.detener()
    escritor.detener()

    conexion = abrir_lectura(tmp_path / "luna.db")
    try:
        comandantes = conexion.execute("SELECT fid FROM commanders ORDER BY fid").fetchall()
        naves = conexion.execute("SELECT fid FROM ships ORDER BY fid").fetchall()
    finally:
        conexion.close()
    assert comandantes == [("F0000001",), ("F0000002",)]
    assert naves == [("F0000001",), ("F0000002",)]


def test_sin_eventos_nuevos_no_escribe_en_la_base(tmp_path, juego, config, arrancar):
    shutil.copy(FIXTURES / "sesion_comercio.log", juego / NOMBRE)
    escritor = Escritor(tmp_path / "luna.db")
    escritor.iniciar()
    trabajos = []
    original = escritor.encolar

    def contando(trabajo):
        trabajos.append(trabajo)
        original(trabajo)

    escritor.encolar = contando
    nucleo, _ = arrancar(config, escritor)
    assert esperar(lambda: nucleo.estado().nave is not None)
    escritos = len(trabajos)

    time.sleep(1.5)

    assert len(trabajos) == escritos
    nucleo.detener()
    escritor.detener()


def test_un_config_corrupto_cae_a_la_carpeta_automatica(tmp_path, juego, monkeypatch, arrancar):
    ruta = tmp_path / "config.json"
    ruta.write_text("{ esto no es json", encoding="utf-8")
    monkeypatch.setattr("core.journal.carpeta.por_defecto", lambda: juego)
    shutil.copy(FIXTURES / "sesion_comercio.log", juego / NOMBRE)

    nucleo, _ = arrancar(ruta)

    assert esperar(lambda: nucleo.estado().comandante == "CMDR Prueba")


@pytest.fixture
def atracado(tmp_path, juego, config, arrancar):
    """Un núcleo con base de datos, atracado en la estación del fixture de Market.json."""
    shutil.copy(FIXTURES / "sesion_comercio.log", juego / NOMBRE)
    ruta = tmp_path / "luna.db"
    escritor = Escritor(ruta)
    escritor.iniciar()
    nucleo, bus = arrancar(config, escritor)
    assert esperar(lambda: nucleo.estado().estacion is not None)
    yield nucleo, bus, ruta, juego
    nucleo.detener()
    escritor.detener()


def consultar(ruta: Path, consulta: str) -> list[tuple]:
    conexion = abrir_lectura(ruta)
    try:
        return conexion.execute(consulta).fetchall()
    finally:
        conexion.close()


def test_abrir_el_mercado_guarda_los_precios_con_origen_propio(atracado):
    nucleo, bus, ruta, juego = atracado
    avisos = []
    bus.suscribir(events.MERCADO_ACTUALIZADO, avisos.append)

    shutil.copy(FIXTURES / "Market.json", juego / archivos.MERCADO)

    assert esperar(lambda: avisos == [4220195075])
    precios = consultar(
        ruta, "SELECT commodity, buy_price, origen, observado FROM market_prices ORDER BY 1"
    )
    assert ("palladium", 48293, "propio", "2026-11-10T05:13:02Z") in precios
    assert "platinum" not in {f[0] for f in precios}
    estacion = consultar(ruta, "SELECT nombre, categoria, plataforma, distancia_ls FROM stations")
    assert estacion[0][:3] == ("St4r F0x's Salt Shack", "orbital", "L")
    assert consultar(ruta, "SELECT nombre_es FROM commodities WHERE simbolo = 'gold'") == [("Oro",)]
    assert consultar(ruta, "SELECT nombre, fuente FROM systems") == [
        ("Col 285 Sector HB-C b14-2", "propio")
    ]


def test_un_market_json_de_otra_estacion_no_se_guarda(atracado):
    _, _, ruta, juego = atracado
    ajeno = json.loads((FIXTURES / "Market.json").read_text(encoding="utf-8"))
    ajeno["MarketID"] = 1

    (juego / archivos.MERCADO).write_text(json.dumps(ajeno), encoding="utf-8")
    time.sleep(1.2)

    assert consultar(ruta, "SELECT COUNT(*) FROM market_prices") == [(0,)]


def test_el_mismo_market_json_no_avisa_dos_veces(atracado):
    _, bus, _, juego = atracado
    avisos = []
    bus.suscribir(events.MERCADO_ACTUALIZADO, avisos.append)

    shutil.copy(FIXTURES / "Market.json", juego / archivos.MERCADO)
    assert esperar(lambda: len(avisos) == 1)
    time.sleep(1.2)

    assert len(avisos) == 1


def test_un_market_json_a_medio_escribir_se_reintenta(atracado):
    _, _, ruta, juego = atracado
    completo = (FIXTURES / "Market.json").read_text(encoding="utf-8")

    (juego / archivos.MERCADO).write_text(completo[:200], encoding="utf-8")
    time.sleep(1.2)
    (juego / archivos.MERCADO).write_text(completo, encoding="utf-8")

    assert esperar(lambda: consultar(ruta, "SELECT COUNT(*) FROM market_prices") != [(0,)])


def test_el_market_json_de_antes_de_arrancar_se_guarda_si_sigues_atracado(
    tmp_path, juego, config, arrancar
):
    shutil.copy(FIXTURES / "sesion_comercio.log", juego / NOMBRE)
    shutil.copy(FIXTURES / "Market.json", juego / archivos.MERCADO)
    ruta = tmp_path / "luna.db"
    escritor = Escritor(ruta)
    escritor.iniciar()

    arrancar(config, escritor)

    assert esperar(lambda: consultar(ruta, "SELECT COUNT(*) FROM market_prices") != [(0,)])
    escritor.detener()


def test_la_distancia_de_un_sistema_propio_se_mide_desde_el_centro_configurado(
    tmp_path, juego, config, arrancar
):
    config.write_text(
        '{"esfera": {"centro": {"nombre": "C", "x": 1, "y": 2, "z": 2}, "radio": 50}}',
        encoding="utf-8",
    )
    shutil.copy(FIXTURES / "sesion_comercio.log", juego / NOMBRE)
    ruta = tmp_path / "luna.db"
    escritor = Escritor(ruta)
    escritor.iniciar()
    nucleo, bus = arrancar(config, escritor)
    avisos = []
    bus.suscribir(events.MERCADO_ACTUALIZADO, avisos.append)
    assert esperar(lambda: nucleo.estado().estacion is not None)
    try:
        shutil.copy(FIXTURES / "Market.json", juego / archivos.MERCADO)
        assert esperar(lambda: avisos)
        x, y, z, distancia = consultar(ruta, "SELECT x, y, z, distancia_centro FROM systems")[0]
        assert distancia == pytest.approx(((x - 1) ** 2 + (y - 2) ** 2 + (z - 2) ** 2) ** 0.5)
    finally:
        nucleo.detener()
        escritor.detener()
