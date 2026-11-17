"""Tablas del comandante (sección 5.2): trabajos para el hilo escritor.

Nunca se borran automáticamente (regla 7 de la sección 5.4), por eso solo hay
altas y actualizaciones.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from core.journal.comercio import Operacion, Tramo
from core.journal.sesiones import Bloque


@dataclass(frozen=True)
class FichaDeNave:
    fid: str
    ship_id: int
    modelo: str
    nombre: str
    capacidad_carga: int
    rango_vacio: float | None
    rango_cargado: float | None
    plataforma: str | None
    actualizado: str


def registrar_comandante(conexion: sqlite3.Connection, fid: str, nombre: str, visto: str) -> None:
    conexion.execute(
        "INSERT INTO commanders (fid, nombre, visto) VALUES (?, ?, ?) "
        "ON CONFLICT(fid) DO UPDATE SET nombre = excluded.nombre, visto = excluded.visto",
        (fid, nombre, visto),
    )


def guardar_nave(conexion: sqlite3.Connection, ficha: FichaDeNave) -> None:
    conexion.execute(
        "INSERT INTO ships (fid, ship_id, modelo, nombre, capacidad_carga, rango_vacio, "
        "rango_cargado, plataforma, actualizado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(fid, ship_id) DO UPDATE SET modelo = excluded.modelo, "
        "nombre = excluded.nombre, capacidad_carga = excluded.capacidad_carga, "
        "rango_vacio = excluded.rango_vacio, rango_cargado = excluded.rango_cargado, "
        "plataforma = excluded.plataforma, actualizado = excluded.actualizado",
        (
            ficha.fid,
            ficha.ship_id,
            ficha.modelo,
            ficha.nombre,
            ficha.capacidad_carga,
            ficha.rango_vacio,
            ficha.rango_cargado,
            ficha.plataforma,
            ficha.actualizado,
        ),
    )


@dataclass(frozen=True)
class MuestraDeTiempo:
    fid: str
    ship_id: int
    tramo: str
    fin: str
    segundos: float
    distancia_ls: float | None


def guardar_muestras(conexion: sqlite3.Connection, muestras: list[MuestraDeTiempo]) -> None:
    """Al reconstruir se relee el journal: una muestra ya guardada se deja como está."""
    conexion.executemany(
        "INSERT OR IGNORE INTO timing_samples (fid, ship_id, tramo, fin, segundos, distancia_ls) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(m.fid, m.ship_id, m.tramo, m.fin, m.segundos, m.distancia_ls) for m in muestras],
    )


def guardar_operaciones(
    conexion: sqlite3.Connection, operaciones: list[tuple[str, int | None, Operacion]]
) -> None:
    """Cada compra o venta con su comandante y nave; las ya guardadas se dejan como están."""
    conexion.executemany(
        "INSERT OR IGNORE INTO trades (fid, marca, market_id, commodity, venta, cantidad, "
        "ship_id, estacion, sistema, precio, total, precio_medio_compra) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                fid,
                o.marca,
                o.market_id,
                o.simbolo,
                int(o.venta),
                o.cantidad,
                ship_id,
                o.estacion,
                o.sistema,
                o.precio,
                o.total,
                o.precio_medio_compra,
            )
            for fid, ship_id, o in operaciones
        ],
    )


def guardar_tramos(conexion: sqlite3.Connection, tramos: list[tuple[str, Tramo]]) -> None:
    conexion.executemany(
        "INSERT OR IGNORE INTO trade_legs (fid, salida, llegada, ship_id, segundos, saltos, "
        "origen_market_id, origen_estacion, origen_sistema, destino_market_id, "
        "destino_estacion, destino_sistema, distancia_ly, rango, distancia_ls, planetaria, "
        "ganancia, toneladas, mercancia) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?)",
        [
            (
                fid,
                t.salida,
                t.llegada,
                t.ship_id,
                t.segundos,
                t.saltos,
                t.origen.market_id,
                t.origen.estacion,
                t.origen.sistema,
                t.destino.market_id,
                t.destino.estacion,
                t.destino.sistema,
                t.distancia_ly,
                t.rango,
                t.distancia_ls,
                int(t.planetaria),
                t.ganancia,
                t.toneladas,
                t.mercancia,
            )
            for fid, t in tramos
        ],
    )


def guardar_bloques(conexion: sqlite3.Connection, bloques: list[Bloque]) -> None:
    """El bloque abierto se va actualizando; los bloques no se solapan.

    Si la relectura empieza en la continuación de un journal, el primer bloque sale
    recortado: si cae dentro de uno guardado se descarta, y si uno guardado cae
    dentro del nuevo, el nuevo lo sustituye. Una copia más vieja del bloque abierto
    (la importación lo leyó antes que el seguimiento en vivo) no pisa la guardada ni
    reabre un bloque ya cerrado.
    """
    for b in bloques:
        if _dentro_de_otro(conexion, b) or _mas_viejo_que_el_guardado(conexion, b):
            continue
        conexion.execute(
            "DELETE FROM sessions WHERE fid = ? AND inicio > ? AND inicio <= ?",
            (b.fid, b.inicio, b.fin),
        )
        conexion.execute(
            "INSERT OR REPLACE INTO sessions (fid, inicio, fin, partida, pausa_previa, "
            "saldo_inicio, saldo_fin, ganancia, toneladas, saltos, cerrado) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                b.fid,
                b.inicio,
                b.fin,
                b.partida,
                b.pausa_previa,
                b.saldo_inicio,
                b.saldo_fin,
                b.ganancia,
                b.toneladas,
                b.saltos,
                int(b.cerrado),
            ),
        )


def _mas_viejo_que_el_guardado(conexion: sqlite3.Connection, bloque: Bloque) -> bool:
    fila = conexion.execute(
        "SELECT 1 FROM sessions WHERE fid = ? AND inicio = ? "
        "AND (fin > ? OR (fin = ? AND cerrado > ?))",
        (bloque.fid, bloque.inicio, bloque.fin, bloque.fin, int(bloque.cerrado)),
    ).fetchone()
    return fila is not None


def _dentro_de_otro(conexion: sqlite3.Connection, bloque: Bloque) -> bool:
    fila = conexion.execute(
        "SELECT 1 FROM sessions WHERE fid = ? AND inicio < ? AND fin >= ? LIMIT 1",
        (bloque.fid, bloque.inicio, bloque.inicio),
    ).fetchone()
    return fila is not None
