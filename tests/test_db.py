import sqlite3
import threading

import pytest

from core import catalogo
from core.db import comandante, esquema
from core.db.escritor import Escritor, NoSePudoAbrir, abrir, abrir_lectura


def ficha(**cambios) -> comandante.FichaDeNave:
    base = {
        "fid": "F0000001",
        "ship_id": 14,
        "modelo": "panthermkii",
        "nombre": "nave de prueba",
        "capacidad_carga": 1120,
        "rango_vacio": 49.3,
        "rango_cargado": 33.0,
        "plataforma": "L",
        "actualizado": "2026-11-12T10:00:00Z",
    }
    return comandante.FichaDeNave(**{**base, **cambios})


@pytest.fixture
def escritor(tmp_path):
    activo = Escritor(tmp_path / "luna.db")
    activo.iniciar()
    yield activo
    activo.detener()


def leer(escritor_ruta, consulta: str) -> list[tuple]:
    conexion = abrir_lectura(escritor_ruta)
    try:
        return conexion.execute(consulta).fetchall()
    finally:
        conexion.close()


def test_migrar_crea_las_tablas_y_es_repetible(tmp_path):
    conexion = abrir(tmp_path / "luna.db")

    esquema.migrar(conexion)
    esquema.migrar(conexion)

    tablas = {f[0] for f in conexion.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"commanders", "ships"} <= tablas
    assert esquema.version(conexion) == len(esquema.MIGRACIONES)
    assert conexion.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conexion.close()


def test_una_base_de_una_version_posterior_no_se_toca(tmp_path):
    conexion = abrir(tmp_path / "luna.db")
    conexion.execute(f"PRAGMA user_version = {len(esquema.MIGRACIONES) + 1}")

    with pytest.raises(esquema.BaseDeDatosPosterior):
        esquema.migrar(conexion)
    conexion.close()


def test_una_migracion_que_falla_no_deja_la_base_a_medias(tmp_path, monkeypatch):
    monkeypatch.setattr(esquema, "MIGRACIONES", ("CREATE TABLE a (x); CREATE TABLE a (x);",))
    conexion = abrir(tmp_path / "luna.db")

    with pytest.raises(sqlite3.Error):
        esquema.migrar(conexion)
    conexion.execute("ROLLBACK")

    assert esquema.version(conexion) == 0
    assert conexion.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
    conexion.close()


def test_el_escritor_guarda_comandante_y_nave(escritor, tmp_path):
    escritor.encolar(lambda c: comandante.registrar_comandante(c, "F0000001", "CMDR Prueba", "t"))
    escritor.encolar(lambda c: comandante.guardar_nave(c, ficha()))
    escritor.detener()

    assert leer(tmp_path / "luna.db", "SELECT nombre FROM commanders") == [("CMDR Prueba",)]
    naves = leer(tmp_path / "luna.db", "SELECT modelo, plataforma FROM ships")
    assert naves == [("panthermkii", "L")]


def test_guardar_la_misma_nave_la_actualiza_sin_duplicarla(escritor, tmp_path):
    escritor.encolar(lambda c: comandante.registrar_comandante(c, "F0000001", "CMDR Prueba", "t"))
    escritor.encolar(lambda c: comandante.guardar_nave(c, ficha(capacidad_carga=1000)))
    escritor.encolar(lambda c: comandante.guardar_nave(c, ficha(capacidad_carga=1120)))
    escritor.detener()

    assert leer(tmp_path / "luna.db", "SELECT capacidad_carga FROM ships") == [(1120,)]


def test_una_nave_sin_comandante_se_rechaza_y_el_escritor_sigue(escritor, tmp_path):
    escritor.encolar(lambda c: comandante.guardar_nave(c, ficha(fid="nadie")))
    escritor.encolar(lambda c: comandante.registrar_comandante(c, "F0000001", "CMDR Prueba", "t"))
    escritor.detener()

    assert leer(tmp_path / "luna.db", "SELECT count(*) FROM ships") == [(0,)]
    assert leer(tmp_path / "luna.db", "SELECT count(*) FROM commanders") == [(1,)]


def test_un_trabajo_que_falla_deshace_todo_lo_suyo(escritor, tmp_path):
    def roto(conexion):
        comandante.registrar_comandante(conexion, "F0000009", "Fantasma", "t")
        raise RuntimeError("fallo a mitad")

    escritor.encolar(roto)
    escritor.detener()

    assert leer(tmp_path / "luna.db", "SELECT count(*) FROM commanders") == [(0,)]


def test_muchos_hilos_escriben_a_traves_de_la_cola(escritor, tmp_path):
    def desde_un_hilo(numero: int) -> None:
        for i in range(25):
            fid = f"F{numero:03d}{i:03d}"
            escritor.encolar(lambda c, fid=fid: comandante.registrar_comandante(c, fid, "x", "t"))

    hilos = [threading.Thread(target=desde_un_hilo, args=(n,)) for n in range(8)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()
    escritor.detener()

    assert leer(tmp_path / "luna.db", "SELECT count(*) FROM commanders") == [(200,)]


def test_la_conexion_de_lectura_no_puede_escribir(escritor, tmp_path):
    lectura = abrir_lectura(tmp_path / "luna.db")

    with pytest.raises(sqlite3.OperationalError):
        lectura.execute("INSERT INTO commanders VALUES ('a', 'b', 'c')")
    lectura.close()


def test_una_ruta_imposible_se_informa_en_lugar_de_colgar(tmp_path):
    ocupado = tmp_path / "es-un-archivo"
    ocupado.write_text("x", encoding="utf-8")

    with pytest.raises(NoSePudoAbrir):
        Escritor(ocupado / "luna.db").iniciar()


def test_el_catalogo_conoce_las_naves_del_juego():
    assert catalogo.nave("panthermkii").plataforma == "L"
    assert catalogo.nave("Python").nombre == "Python"
    assert catalogo.nave("naveinventada") is None
