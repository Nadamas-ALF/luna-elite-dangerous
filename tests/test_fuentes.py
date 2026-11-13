import gzip
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.db import esquema, mercado, retencion
from core.db.escritor import Escritor, abrir_lectura
from core.esfera import Esfera
from core.journal.mercado import Articulo
from core.spansh import importacion

FIXTURE = Path(__file__).parent / "fixtures" / "spansh" / "galaxy_stations_muestra.json"
T = "2026-11-01T00:00:00Z"


@pytest.fixture
def base(tmp_path):
    import sqlite3

    conexion = sqlite3.connect(":memory:", isolation_level=None)
    conexion.execute("PRAGMA foreign_keys = ON")
    esquema.migrar(conexion)
    yield conexion
    conexion.close()


def sistema(direccion=1, nombre="Colonia", x=1.0, fuente=mercado.FUENTE_EDDN):
    return mercado.Sistema(direccion, nombre, (x, 2.0, 3.0), abs(x), fuente)


def guardar(base, *sistemas):
    for s in sistemas:
        mercado.guardar_sistema(base, s, T)


def fila(base, direccion=1):
    return base.execute(
        "SELECT nombre, x, distancia_centro, fuente FROM systems WHERE system_address = ?",
        (direccion,),
    ).fetchone()


def test_un_sistema_guardado_por_eddn_se_marca_provisional(base):
    guardar(base, sistema())
    assert fila(base)[3] == "eddn"


def test_spansh_corrige_las_coordenadas_de_un_sistema_que_solo_conocia_eddn(base):
    falso = sistema(nombre="Falso", x=999.0)
    guardar(base, falso, sistema(nombre="Colonia", x=1.0, fuente="spansh"))
    assert fila(base) == ("Colonia", 1.0, 1.0, "spansh")


def test_el_journal_propio_tambien_corrige_a_eddn(base):
    guardar(base, sistema(x=999.0), sistema(x=1.0, fuente="propio"))
    assert fila(base) == ("Colonia", 1.0, 1.0, "propio")


def test_eddn_no_pisa_lo_que_dijo_una_fuente_fiable(base):
    guardar(base, sistema(x=1.0, fuente="spansh"), sistema(nombre="Falso", x=999.0))
    assert fila(base) == ("Colonia", 1.0, 1.0, "spansh")


def test_entre_fuentes_fiables_manda_la_primera(base):
    guardar(base, sistema(x=1.0, fuente="spansh"), sistema(x=5.0, fuente="propio"))
    assert fila(base)[1] == 1.0
    assert fila(base)[3] == "spansh"


def test_una_fuente_fiable_sin_coordenadas_no_borra_las_de_eddn(base):
    guardar(base, sistema(x=7.0))
    mercado.guardar_sistema(
        base, mercado.Sistema(1, "Colonia", None, None, mercado.FUENTE_PROPIO), T
    )
    assert fila(base) == ("Colonia", 7.0, 7.0, "propio")


def test_un_nombre_con_un_solo_sistema_se_resuelve(base):
    guardar(base, sistema())
    assert mercado.sistema_por_nombre(base, "Colonia").system_address == 1


def test_con_un_duplicado_gana_el_unico_de_fuente_fiable(base):
    guardar(base, sistema(1, fuente="eddn"), sistema(2, fuente="spansh"))
    assert mercado.sistema_por_nombre(base, "Colonia").system_address == 2


def test_dos_provisionales_con_el_mismo_nombre_no_se_adivinan(base):
    guardar(base, sistema(1), sistema(2))
    assert mercado.sistema_por_nombre(base, "Colonia") is None


def test_dos_de_fuente_fiable_con_el_mismo_nombre_no_se_adivinan(base):
    guardar(base, sistema(1, fuente="spansh"), sistema(2, fuente="propio"))
    assert mercado.sistema_por_nombre(base, "Colonia") is None


def test_se_detecta_un_nombre_que_ya_tiene_otra_direccion(base):
    guardar(base, sistema(1))
    assert mercado.nombre_en_uso_por_otro(base, "Colonia", 2)
    assert not mercado.nombre_en_uso_por_otro(base, "Colonia", 1)
    assert not mercado.nombre_en_uso_por_otro(base, "Otro", 2)


def estacion_con_precios(base, market_id, direccion):
    base.execute(
        "INSERT INTO stations (market_id, system_address, nombre, categoria, planetaria, "
        "actualizado) VALUES (?, ?, 'E', 'orbital', 0, ?)",
        (market_id, direccion, T),
    )
    mercado.guardar_precios(
        base, market_id, (Articulo("gold", None, None, 0, 9, 0, 5, 3, 3, False),), "eddn", T
    )


def test_purgar_borra_al_impostor_con_sus_estaciones_y_precios(base):
    guardar(base, sistema(1, fuente="spansh"), sistema(2))
    estacion_con_precios(base, 10, 1)
    estacion_con_precios(base, 20, 2)
    assert mercado.purgar_impostores(base) == 1
    assert base.execute("SELECT system_address FROM systems").fetchall() == [(1,)]
    assert base.execute("SELECT market_id FROM stations").fetchall() == [(10,)]
    assert base.execute("SELECT DISTINCT market_id FROM market_prices").fetchall() == [(10,)]


def test_purgar_no_toca_a_los_provisionales_sin_rival_fiable(base):
    guardar(base, sistema(1, "A"), sistema(2, "B"), sistema(3, "C", fuente="spansh"))
    assert mercado.purgar_impostores(base) == 0
    assert base.execute("SELECT count(*) FROM systems").fetchone() == (3,)


def test_purgar_no_toca_a_dos_provisionales_iguales(base):
    guardar(base, sistema(1), sistema(2))
    assert mercado.purgar_impostores(base) == 0


def test_la_limpieza_periodica_tambien_purga_impostores(base):
    guardar(base, sistema(1, fuente="propio"), sistema(2))
    resultado = retencion.limpiar(
        base,
        Esfera("S", (0.0, 0.0, 0.0), 1e6),
        retencion.Reglas(),
        datetime(2026, 11, 2, tzinfo=UTC),
    )
    assert resultado.impostores == 1
    assert base.execute("SELECT count(*) FROM systems").fetchone() == (1,)


def test_la_migracion_marca_lo_anterior_como_provisional(tmp_path):
    import sqlite3

    conexion = sqlite3.connect(tmp_path / "vieja.db", isolation_level=None)
    conexion.executescript(
        "BEGIN;" + ";".join(esquema.MIGRACIONES[:4]) + ";PRAGMA user_version = 4;COMMIT;"
    )
    conexion.execute(
        "INSERT INTO systems (system_address, nombre, x, y, z, actualizado) "
        "VALUES (1, 'Vieja', 1, 2, 3, 't')"
    )
    esquema.migrar(conexion)
    assert conexion.execute("SELECT fuente FROM systems").fetchone() == ("eddn",)
    conexion.close()


@pytest.fixture
def escritor(tmp_path):
    activo = Escritor(tmp_path / "luna.db")
    activo.iniciar()
    yield activo
    activo.detener()


def test_importar_spansh_elimina_al_impostor_y_corrige_las_coordenadas(tmp_path, escritor):
    # En la muestra, «HD 168444» es el sistema 2523303; EDDN lo conocía mal y hay un duplicado.
    def sembrar(conexion):
        mercado.guardar_sistema(conexion, sistema(2523303, "HD 168444", x=999.0), T)
        mercado.guardar_sistema(conexion, sistema(777, "HD 168444", x=5.0), T)
        estacion_con_precios(conexion, 55, 777)

    escritor.encolar(sembrar)
    archivo = tmp_path / "volcado.json.gz"
    archivo.write_bytes(gzip.compress(FIXTURE.read_bytes()))
    importacion.importar(
        archivo,
        Esfera("Galaxia", (0.0, 0.0, 0.0), 1_000_000.0),
        escritor,
        threading.Event(),
        lambda _: None,
        datetime(2026, 12, 1, tzinfo=UTC),
    )
    escritor.detener()

    conexion = abrir_lectura(tmp_path / "luna.db")
    try:
        filas = conexion.execute(
            "SELECT system_address, x, fuente FROM systems WHERE nombre = 'HD 168444'"
        ).fetchall()
        estaciones = conexion.execute(
            "SELECT count(*) FROM stations WHERE market_id = 55"
        ).fetchone()
    finally:
        conexion.close()
    assert len(filas) == 1
    assert filas[0][0] == 2523303
    assert filas[0][1] != 999.0
    assert filas[0][2] == "spansh"
    assert estaciones == (0,)
