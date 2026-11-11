import sqlite3
import sys


def test_version_minima_de_python():
    """La 3.12 es la de SPEC.md; una posterior sirve, una anterior no."""
    assert sys.version_info >= (3, 12)


def test_sqlite_trae_rtree():
    """Verificacion 1 de la fase 0: el filtro por esfera depende de R*Tree."""
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE sistemas USING rtree(id, min_x, max_x)")
    finally:
        con.close()


def test_sqlite_acepta_modo_wal(tmp_path):
    """WAL falla en unidades de red; el archivo de la base vive en disco local."""
    con = sqlite3.connect(tmp_path / "prueba.db")
    try:
        modo = con.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    finally:
        con.close()
    assert modo == "wal"
