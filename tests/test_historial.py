import shutil
import threading
import time
from pathlib import Path

import pytest

from core.db.escritor import Escritor, abrir_lectura
from core.journal import historial, plegado

FIXTURES = Path(__file__).parent / "fixtures" / "journal"


def esperar(condicion, segundos: float = 10.0) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def carpeta(tmp_path):
    juego = tmp_path / "juego"
    juego.mkdir()
    shutil.copy(FIXTURES / "legacy_sintetico.log", juego / "Journal.2021-03-01T100000.01.log")
    shutil.copy(FIXTURES / "sesion_comercio.log", juego / "Journal.2026-11-10T033327.01.log")
    shutil.copy(FIXTURES / "bucle_comercio.log", juego / "Journal.2026-11-15T180000.01.log")
    return juego


@pytest.fixture
def escritor(tmp_path):
    hilo = Escritor(tmp_path / "luna.db")
    hilo.iniciar()
    yield hilo
    hilo.detener()


def terminar(importador) -> dict:
    assert esperar(lambda: importador.estado()["fase"] != historial.IMPORTANDO)
    return importador.estado()


def contar(tmp_path) -> dict[str, int]:
    conexion = abrir_lectura(tmp_path / "luna.db")
    try:
        return {
            tabla: conexion.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]  # noqa: S608
            for tabla in ("trades", "trade_legs", "sessions", "timing_samples")
        }
    finally:
        conexion.close()


def importar(importador, carpeta, escritor) -> dict:
    assert importador.iniciar(carpeta)
    estado = terminar(importador)
    # La fase final llega cuando el escritor ya guardó: nada queda en cola.
    assert escritor.pendientes() == 0
    return estado


def test_importa_los_journals_salta_legacy_y_guarda_lo_del_comandante(
    carpeta, escritor, tmp_path
):
    importador = historial.Importador(escritor)

    estado = importar(importador, carpeta, escritor)

    assert estado["fase"] == historial.TERMINADA
    assert (estado["total"], estado["leidos"], estado["saltados"]) == (3, 3, 1)
    assert estado["operaciones"] > 0
    filas = contar(tmp_path)
    # Una operación idéntica en el mismo segundo se ignora (E-19), por eso no es una igualdad.
    assert 0 < filas["trades"] <= estado["operaciones"]
    assert 0 < filas["trade_legs"] <= estado["tramos"]
    assert filas["sessions"] > 0


def test_importar_dos_veces_deja_las_mismas_filas(carpeta, escritor, tmp_path):
    importador = historial.Importador(escritor)
    importar(importador, carpeta, escritor)
    una_vez = contar(tmp_path)

    importar(importador, carpeta, escritor)

    assert contar(tmp_path) == una_vez


def test_un_journal_ilegible_se_cuenta_y_no_detiene_el_resto(carpeta, escritor, tmp_path):
    (carpeta / "Journal.2026-11-12T000000.01.log").mkdir()
    importador = historial.Importador(escritor)

    estado = importar(importador, carpeta, escritor)

    assert estado["fase"] == historial.TERMINADA
    assert estado["ilegibles"] == 1
    assert estado["leidos"] == 3
    assert 0 < contar(tmp_path)["trade_legs"] <= estado["tramos"]


def test_cancelar_antes_de_leer_deja_la_fase_cancelada_y_nada_guardado(
    carpeta, escritor, tmp_path
):
    importador = historial.Importador(escritor)

    class Cancelado:
        """Cancelada desde el primer journal, como un clic durante la lectura."""

        def is_set(self) -> bool:
            return True

        def clear(self) -> None:
            pass

    importador._parar = Cancelado()
    assert importador.iniciar(carpeta)
    estado = terminar(importador)

    assert estado["fase"] == historial.CANCELADA
    assert estado["leidos"] == 0
    assert contar(tmp_path) == {"trades": 0, "trade_legs": 0, "sessions": 0, "timing_samples": 0}


def test_cancelada_solo_cuando_el_escritor_guardo_lo_leido(carpeta, escritor, tmp_path):
    importador = historial.Importador(escritor)

    class TrasElPrimero:
        """Cancelada después de leer el primer journal."""

        def __init__(self) -> None:
            self.preguntas = 0

        def is_set(self) -> bool:
            self.preguntas += 1
            return self.preguntas > 1

        def clear(self) -> None:
            pass

    importador._parar = TrasElPrimero()
    bloqueo = threading.Event()
    escritor.encolar(lambda _conexion: bloqueo.wait(10))
    assert importador.iniciar(carpeta)
    # Con el escritor ocupado, lo leído sigue en la cola: aún no está cancelada.
    assert not esperar(lambda: importador.estado()["fase"] != historial.IMPORTANDO, 0.3)
    bloqueo.set()
    estado = terminar(importador)

    assert (estado["fase"], estado["leidos"]) == (historial.CANCELADA, 1)
    assert escritor.pendientes() == 0


def test_un_fallo_de_una_importacion_anterior_no_cuenta_en_la_nueva(
    carpeta, escritor, monkeypatch
):
    avisos = []
    original = plegado.guardar

    def guardar(escritor_, lote, fallo):
        avisos.append(fallo)
        original(escritor_, lote, fallo)

    monkeypatch.setattr(plegado, "guardar", guardar)
    importador = historial.Importador(escritor)
    importar(importador, carpeta, escritor)
    de_la_primera = avisos[0]

    bloqueo = threading.Event()
    escritor.encolar(lambda _conexion: bloqueo.wait(10))
    assert importador.iniciar(carpeta)
    de_la_primera(RuntimeError("trabajo de la importación anterior"))
    bloqueo.set()

    assert terminar(importador)["fase"] == historial.TERMINADA


def test_un_journal_con_el_nombre_antiguo_no_cierra_la_sesion_de_hoy(escritor, tmp_path):
    juego = tmp_path / "juego"
    juego.mkdir()
    texto = (FIXTURES / "sesion_comercio.log").read_text(encoding="utf-8")
    (juego / "Journal.2026-11-10T033327.01.log").write_text(texto, encoding="utf-8", newline="\n")
    importador = historial.Importador(escritor)
    importar(importador, juego, escritor)
    de_hoy = sesiones(tmp_path)

    antiguo = texto.replace("2026-11-10", "2021-10-01")
    (juego / "Journal.211001033327.01.log").write_text(antiguo, encoding="utf-8", newline="\n")
    importar(importador, juego, escritor)

    assert [fila for fila in sesiones(tmp_path) if fila[0].startswith("2026")] == de_hoy


def sesiones(tmp_path) -> list[tuple]:
    conexion = abrir_lectura(tmp_path / "luna.db")
    try:
        return conexion.execute(
            "SELECT inicio, fin, ganancia, cerrado FROM sessions ORDER BY inicio"
        ).fetchall()
    finally:
        conexion.close()


def test_no_arranca_dos_a_la_vez(carpeta, escritor):
    importador = historial.Importador(escritor)
    with importador._candado:
        importador._fase = historial.IMPORTANDO

    assert not importador.iniciar(carpeta)


def test_sin_base_no_se_puede_importar(carpeta):
    assert not historial.Importador(None).iniciar(carpeta)


def test_una_carpeta_sin_journals_termina_con_cero(tmp_path, escritor):
    vacia = tmp_path / "vacia"
    vacia.mkdir()
    importador = historial.Importador(escritor)

    estado = importar(importador, vacia, escritor)

    assert (estado["fase"], estado["total"], estado["leidos"]) == (historial.TERMINADA, 0, 0)


def test_el_nucleo_importa_la_carpeta_que_sigue(carpeta, escritor, tmp_path):
    from core import events
    from core.config import ajustes
    from core.nucleo import Nucleo

    config = tmp_path / "config.json"
    ajustes.guardar_carpeta_journal(config, str(carpeta))
    nucleo = Nucleo(config, events.Bus(), escritor)
    try:
        assert nucleo.importar_historial() == {"error": "sin_carpeta"}
        nucleo.iniciar()
        assert esperar(lambda: nucleo.estado_del_journal() != "sin_carpeta")

        assert nucleo.importar_historial()["fase"] == historial.IMPORTANDO
        assert nucleo.importar_historial() == {"error": "en_marcha"}
        assert esperar(lambda: nucleo.estado_de_la_importacion()["fase"] != historial.IMPORTANDO)
    finally:
        nucleo.detener()

    assert nucleo.estado_de_la_importacion()["fase"] == historial.TERMINADA


def test_el_nucleo_sin_base_no_importa(carpeta):
    from core import events
    from core.nucleo import Nucleo

    nucleo = Nucleo(carpeta / "config.json", events.Bus(), None)

    assert nucleo.importar_historial() == {"error": "sin_base"}


def test_el_nucleo_avisa_si_la_carpeta_ya_no_existe(carpeta, escritor, tmp_path):
    from core import events
    from core.nucleo import Nucleo

    nucleo = Nucleo(tmp_path / "config.json", events.Bus(), escritor)
    nucleo._carpeta = carpeta
    shutil.rmtree(carpeta)

    assert nucleo.importar_historial() == {"error": "sin_carpeta"}
    assert nucleo.estado_de_la_importacion()["fase"] == historial.INACTIVA


def test_si_el_escritor_no_puede_cerrar_la_importacion_acaba_en_error(tmp_path):
    class EscritorRoto:
        """Cada trabajo falla, como con la base bloqueada o un error de disco."""

        def encolar(self, _trabajo, despues=None, fallo=None) -> None:
            if fallo is not None:
                fallo(RuntimeError("base bloqueada"))

    vacia = tmp_path / "vacia"
    vacia.mkdir()
    importador = historial.Importador(EscritorRoto())

    assert importador.iniciar(vacia)

    assert terminar(importador)["fase"] == historial.ERROR
