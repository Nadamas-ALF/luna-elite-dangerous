import sqlite3
import threading
import time

import pytest

from core.db import escritor as modulo_escritor
from core.db import espacio, esquema
from core.db.escritor import Escritor, abrir, abrir_lectura


def modo_de(ruta) -> int:
    conexion = abrir_lectura(ruta)
    try:
        return conexion.execute("PRAGMA auto_vacuum").fetchone()[0]
    finally:
        conexion.close()


def contar_mercancias(ruta) -> int:
    conexion = abrir_lectura(ruta)
    try:
        return conexion.execute("SELECT count(*) FROM commodities").fetchone()[0]
    finally:
        conexion.close()


def crear_base_antigua(ruta, filas: int = 6000) -> None:
    """Una base como las de antes de este cambio: auto_vacuum apagado y con datos."""
    conexion = sqlite3.connect(ruta, isolation_level=None)
    conexion.execute("PRAGMA journal_mode = WAL")
    esquema.migrar(conexion)
    conexion.execute("BEGIN")
    conexion.executemany(
        "INSERT INTO commodities (simbolo, nombre_en) VALUES (?, ?)",
        [(f"m{i}", "x" * 200) for i in range(filas)],
    )
    conexion.execute("COMMIT")
    conexion.close()


def esperar(condicion, tiempo=10.0):
    limite = time.monotonic() + tiempo
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.02)
    return False


def test_una_base_nueva_se_crea_con_auto_vacuum_incremental(tmp_path):
    escritor = Escritor(tmp_path / "luna.db")
    escritor.iniciar()
    escritor.detener()
    assert modo_de(tmp_path / "luna.db") == espacio.INCREMENTAL


def test_abrir_una_base_con_datos_no_cambia_su_modo(tmp_path):
    ruta = tmp_path / "vieja.db"
    crear_base_antigua(ruta)
    conexion = abrir(ruta)
    assert espacio.modo(conexion) == 0
    conexion.close()


def test_una_base_antigua_se_convierte_al_arrancar_y_conserva_sus_datos(tmp_path):
    ruta = tmp_path / "luna.db"
    crear_base_antigua(ruta)
    escritor = Escritor(ruta)
    escritor.iniciar()
    escritor.detener()

    assert modo_de(ruta) == espacio.INCREMENTAL
    assert contar_mercancias(ruta) == 6000
    conexion = abrir_lectura(ruta)
    assert conexion.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    conexion.close()
    assert escritor.avisos == ()


def test_convertir_una_base_ya_incremental_no_hace_nada(tmp_path):
    conexion = abrir(tmp_path / "luna.db")
    esquema.migrar(conexion)
    assert espacio.convertir(conexion, tmp_path / "luna.db") == espacio.AL_DIA
    conexion.close()


def test_sin_disco_suficiente_no_se_compacta_y_la_base_sigue_funcionando(tmp_path, monkeypatch):
    ruta = tmp_path / "luna.db"
    crear_base_antigua(ruta)
    monkeypatch.setattr(espacio.shutil, "disk_usage", lambda _: type("U", (), {"free": 1000})())

    escritor = Escritor(ruta)
    escritor.iniciar()
    escritor.encolar(lambda c: c.execute("INSERT INTO commodities (simbolo) VALUES ('nuevo')"))
    escritor.detener()

    assert escritor.avisos == (espacio.AVISO_SIN_ESPACIO,)
    assert modo_de(ruta) == 0
    assert contar_mercancias(ruta) == 6001


def test_un_fallo_del_vacuum_deja_aviso_y_los_datos_intactos(tmp_path, monkeypatch):
    ruta = tmp_path / "luna.db"
    crear_base_antigua(ruta)

    class Roto(sqlite3.Connection):
        def execute(self, sql, *argumentos):
            if sql.strip().upper() == "VACUUM":
                raise sqlite3.OperationalError("disco lleno")
            return super().execute(sql, *argumentos)

    def abrir_roto(r):
        c = sqlite3.connect(r, isolation_level=None, factory=Roto)
        c.execute("PRAGMA journal_mode = WAL")
        return c

    monkeypatch.setattr(modulo_escritor, "abrir", abrir_roto)
    escritor = Escritor(ruta)
    escritor.iniciar()
    escritor.detener()

    assert escritor.avisos == (espacio.AVISO_SIN_COMPACTAR,)
    assert contar_mercancias(ruta) == 6000


def test_una_excepcion_inesperada_al_cuidar_el_espacio_no_mata_al_escritor(tmp_path, monkeypatch):
    def revienta(*_):
        raise RuntimeError("inesperado")

    monkeypatch.setattr(espacio, "convertir", revienta)
    escritor = Escritor(tmp_path / "luna.db")
    escritor.iniciar()
    escritor.encolar(lambda c: c.execute("INSERT INTO commodities (simbolo) VALUES ('sigue')"))
    escritor.detener()

    assert escritor.avisos == (espacio.AVISO_SIN_COMPACTAR,)
    assert contar_mercancias(tmp_path / "luna.db") == 1


def test_el_arranque_no_espera_a_la_conversion_y_avisa_mientras_dura(tmp_path, monkeypatch):
    ruta = tmp_path / "luna.db"
    crear_base_antigua(ruta)
    original = espacio.convertir
    puerta, convertida = threading.Event(), threading.Event()

    def lenta(conexion, r, al_empezar):
        al_empezar()
        puerta.wait(10)
        convertida.set()
        return original(conexion, r, lambda: None)

    monkeypatch.setattr(espacio, "convertir", lenta)
    escritor = Escritor(ruta)
    escritor.iniciar()
    assert not convertida.is_set()
    try:
        assert esperar(lambda: escritor.avisos == (espacio.AVISO_COMPACTANDO,))
    finally:
        puerta.set()
    assert esperar(lambda: escritor.avisos == ())
    escritor.detener()


def base_con_espacio_libre(tmp_path):
    ruta = tmp_path / "luna.db"
    conexion = abrir(ruta)
    esquema.migrar(conexion)
    conexion.execute("BEGIN")
    conexion.executemany(
        "INSERT INTO commodities (simbolo, nombre_en) VALUES (?, ?)",
        [(f"m{i}", "x" * 200) for i in range(30000)],
    )
    conexion.execute("COMMIT")
    conexion.execute("DELETE FROM commodities WHERE rowid % 10 != 0")
    conexion.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return conexion, ruta


def test_devolver_libera_paginas_y_el_archivo_encoge(tmp_path):
    conexion, ruta = base_con_espacio_libre(tmp_path)
    antes = ruta.stat().st_size
    assert espacio.paginas_libres(conexion) > 1000

    conexion.execute("BEGIN IMMEDIATE")
    libres_antes, libres_despues = espacio.devolver(conexion)
    conexion.execute("COMMIT")
    conexion.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    assert libres_despues < libres_antes
    assert ruta.stat().st_size < antes
    conexion.close()


def test_devolver_por_tandas_pequenas_acaba_vaciando_las_libres(tmp_path):
    conexion, _ = base_con_espacio_libre(tmp_path)
    for _ in range(100):
        conexion.execute("BEGIN IMMEDIATE")
        antes, despues = espacio.devolver(conexion, paginas=200)
        conexion.execute("COMMIT")
        if despues == 0:
            break
        assert despues < antes
    assert espacio.paginas_libres(conexion) == 0
    assert conexion.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    conexion.close()


def test_devolver_en_una_base_sin_auto_vacuum_no_hace_nada(tmp_path):
    ruta = tmp_path / "vieja.db"
    crear_base_antigua(ruta)
    conexion = abrir(ruta)
    conexion.execute("DELETE FROM commodities WHERE rowid % 10 != 0")
    libres = espacio.paginas_libres(conexion)
    assert libres > 0
    assert espacio.devolver(conexion) == (libres, libres)
    conexion.close()


@pytest.mark.parametrize("paginas", [0, 1])
def test_devolver_sin_paginas_libres_no_toca_nada(tmp_path, paginas):
    conexion = abrir(tmp_path / "luna.db")
    esquema.migrar(conexion)
    assert espacio.devolver(conexion, paginas) == (0, 0)
    conexion.close()


def test_el_wal_vuelve_a_un_tamano_razonable_tras_una_transaccion_enorme(tmp_path, monkeypatch):
    monkeypatch.setattr(modulo_escritor, "LIMITE_DEL_WAL", 1_000_000)
    ruta = tmp_path / "luna.db"
    conexion = abrir(ruta)
    esquema.migrar(conexion)
    conexion.execute("BEGIN")
    conexion.executemany(
        "INSERT INTO commodities (simbolo, nombre_en) VALUES (?, ?)",
        [(f"m{i}", "x" * 200) for i in range(60000)],
    )
    conexion.execute("COMMIT")
    wal = tmp_path / "luna.db-wal"
    assert wal.stat().st_size > 5_000_000

    conexion.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall()
    conexion.execute("INSERT INTO commodities (simbolo) VALUES ('reinicia_el_wal')")

    assert wal.stat().st_size < 2_000_000
    conexion.close()
