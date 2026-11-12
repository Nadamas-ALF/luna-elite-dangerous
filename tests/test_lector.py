import json
import os
import shutil
from pathlib import Path

from core.journal import archivos, carpeta, lector

FIXTURES = Path(__file__).parent / "fixtures" / "journal"
SESION = FIXTURES / "sesion_comercio.log"
EVENTOS_DE_LA_SESION = 12


def journal(carpeta_de_pruebas: Path, nombre: str, contenido: str) -> Path:
    destino = carpeta_de_pruebas / nombre
    destino.write_text(contenido, encoding="utf-8", newline="\n")
    return destino


def linea(evento: str) -> str:
    return json.dumps({"timestamp": "2026-11-12T10:00:00Z", "event": evento}) + "\n"


def test_iniciar_lee_el_journal_entero(tmp_path):
    shutil.copy(SESION, tmp_path / "Journal.2026-11-10T033327.01.log")

    resultado = lector.Seguidor(tmp_path).iniciar(dias=7)

    assert len(resultado.eventos) == EVENTOS_DE_LA_SESION
    assert resultado.archivo == "Journal.2026-11-10T033327.01.log"
    assert resultado.eventos[0]["event"] == "Fileheader"


def test_sin_journals_no_hay_eventos(tmp_path):
    seguidor = lector.Seguidor(tmp_path)

    assert seguidor.iniciar(dias=7) == lector.Lectura([], None)
    assert seguidor.nuevos().eventos == []


def test_solo_llegan_las_lineas_nuevas(tmp_path):
    archivo = journal(tmp_path, "Journal.2026-11-12T100000.01.log", linea("Fileheader"))
    seguidor = lector.Seguidor(tmp_path)
    seguidor.iniciar(dias=7)

    assert seguidor.nuevos().eventos == []
    with archivo.open("a", encoding="utf-8", newline="\n") as f:
        f.write(linea("Docked"))

    assert [e["event"] for e in seguidor.nuevos().eventos] == ["Docked"]
    assert seguidor.nuevos().eventos == []


def test_una_linea_a_medias_espera_a_estar_completa(tmp_path):
    archivo = journal(tmp_path, "Journal.2026-11-12T100000.01.log", linea("Fileheader"))
    seguidor = lector.Seguidor(tmp_path)
    seguidor.iniciar(dias=7)
    entera = linea("Docked")

    with archivo.open("a", encoding="utf-8", newline="\n") as f:
        f.write(entera[:20])
    assert seguidor.nuevos().eventos == []

    with archivo.open("a", encoding="utf-8", newline="\n") as f:
        f.write(entera[20:])
    assert [e["event"] for e in seguidor.nuevos().eventos] == ["Docked"]


def test_un_journal_nuevo_no_pierde_el_final_del_anterior(tmp_path):
    viejo = journal(tmp_path, "Journal.2026-11-12T100000.01.log", linea("Fileheader"))
    seguidor = lector.Seguidor(tmp_path)
    seguidor.iniciar(dias=7)

    with viejo.open("a", encoding="utf-8", newline="\n") as f:
        f.write(linea("Shutdown"))
    journal(tmp_path, "Journal.2026-11-12T110000.01.log", linea("Fileheader") + linea("LoadGame"))

    resultado = seguidor.nuevos()

    assert [e["event"] for e in resultado.eventos] == ["Shutdown", "Fileheader", "LoadGame"]
    assert resultado.archivo == "Journal.2026-11-12T110000.01.log"


def test_las_lineas_ilegibles_se_saltan(tmp_path):
    contenido = linea("Fileheader") + "esto no es json\n" + "[1, 2]\n" + linea("Docked")
    journal(tmp_path, "Journal.2026-11-12T100000.01.log", contenido)

    resultado = lector.Seguidor(tmp_path).iniciar(dias=7)

    assert [e["event"] for e in resultado.eventos] == ["Fileheader", "Docked"]


def test_los_bytes_invalidos_no_rompen_la_lectura(tmp_path):
    archivo = tmp_path / "Journal.2026-11-12T100000.01.log"
    corrupta = b'{"event": "X\xff"}\n'
    archivo.write_bytes(linea("Fileheader").encode() + corrupta + linea("Docked").encode())

    resultado = lector.Seguidor(tmp_path).iniciar(dias=7)

    assert [e["event"] for e in resultado.eventos] == ["Fileheader", "X�", "Docked"]


def test_los_dias_descartan_journals_viejos_pero_nunca_el_ultimo(tmp_path):
    ahora = 1_800_000_000.0
    antiguo = journal(tmp_path, "Journal.2026-10-01T100000.01.log", linea("Antiguo"))
    reciente = journal(tmp_path, "Journal.2026-11-10T100000.01.log", linea("Reciente"))
    ultimo = journal(tmp_path, "Journal.2026-11-11T100000.01.log", linea("Ultimo"))
    os.utime(antiguo, (ahora - 30 * 86_400,) * 2)
    os.utime(reciente, (ahora - 2 * 86_400,) * 2)
    os.utime(ultimo, (ahora - 20 * 86_400,) * 2)

    resultado = lector.Seguidor(tmp_path).iniciar(dias=7, ahora=ahora)

    assert [e["event"] for e in resultado.eventos] == ["Reciente", "Ultimo"]


def test_los_archivos_que_no_son_journal_se_ignoran(tmp_path):
    journal(tmp_path, "Journal.2026-11-12T100000.01.log", linea("Fileheader"))
    journal(tmp_path, "Journal.2026-11-12T100000.cache", "basura")
    journal(tmp_path, "Market.json", "{}")

    assert [j.name for j in lector.listar(tmp_path)] == ["Journal.2026-11-12T100000.01.log"]


def test_el_lector_no_modifica_el_journal(tmp_path):
    archivo = shutil.copy(SESION, tmp_path / "Journal.2026-11-10T033327.01.log")
    antes = Path(archivo).read_bytes()
    mtime = Path(archivo).stat().st_mtime_ns

    lector.Seguidor(tmp_path).iniciar(dias=7)

    assert Path(archivo).read_bytes() == antes
    assert Path(archivo).stat().st_mtime_ns == mtime


def test_archivos_de_estado_tolerantes(tmp_path):
    assert archivos.leer(tmp_path, archivos.CARGO) is None
    (tmp_path / archivos.CARGO).write_text("", encoding="utf-8")
    assert archivos.leer(tmp_path, archivos.CARGO) is None
    (tmp_path / archivos.CARGO).write_text("[1]", encoding="utf-8")
    assert archivos.leer(tmp_path, archivos.CARGO) is None
    (tmp_path / archivos.CARGO).write_text('{"Count": 3}', encoding="utf-8")
    assert archivos.leer(tmp_path, archivos.CARGO) == {"Count": 3}
    assert archivos.marca(tmp_path, archivos.STATUS) is None


def test_la_carpeta_se_resuelve_por_windows():
    detectada = carpeta.por_defecto()

    assert detectada is None or detectada.parts[-2:] == carpeta.SUBCARPETA


def test_una_carpeta_configurada_que_no_existe_cae_a_la_de_windows(tmp_path):
    assert carpeta.resolver(str(tmp_path)) == tmp_path
    assert carpeta.resolver(str(tmp_path / "no-existe")) == carpeta.resolver(None)
