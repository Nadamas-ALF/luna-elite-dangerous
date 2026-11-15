"""Esquema de la base de datos y sus migraciones.

La versión vive en `PRAGMA user_version`. Cada migración se aplica una sola vez,
en orden, dentro de su propia transacción. Las tablas de mercado (sección 5.1)
llegan con las fases que las usan.
"""

from __future__ import annotations

import sqlite3

MIGRACIONES: tuple[str, ...] = (
    """
    CREATE TABLE commanders (
        fid     TEXT PRIMARY KEY,
        nombre  TEXT NOT NULL,
        visto   TEXT NOT NULL
    );
    CREATE TABLE ships (
        fid             TEXT    NOT NULL REFERENCES commanders(fid),
        ship_id         INTEGER NOT NULL,
        modelo          TEXT    NOT NULL,
        nombre          TEXT    NOT NULL,
        capacidad_carga INTEGER NOT NULL,
        rango_vacio     REAL,
        rango_cargado   REAL,
        plataforma      TEXT,
        actualizado     TEXT    NOT NULL,
        PRIMARY KEY (fid, ship_id)
    );
    """,
    """
    CREATE TABLE systems (
        system_address    INTEGER PRIMARY KEY,
        nombre            TEXT NOT NULL,
        x                 REAL,
        y                 REAL,
        z                 REAL,
        distancia_centro  REAL,
        actualizado       TEXT NOT NULL
    );
    CREATE TABLE stations (
        market_id       INTEGER PRIMARY KEY,
        system_address  INTEGER REFERENCES systems(system_address),
        nombre          TEXT    NOT NULL,
        categoria       TEXT    NOT NULL,
        plataforma      TEXT,
        distancia_ls    REAL,
        planetaria      INTEGER NOT NULL,
        actualizado     TEXT    NOT NULL
    );
    CREATE TABLE commodities (
        simbolo     TEXT PRIMARY KEY,
        nombre_en   TEXT,
        nombre_es   TEXT,
        categoria   TEXT,
        rara        INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE market_prices (
        market_id      INTEGER NOT NULL REFERENCES stations(market_id) ON DELETE CASCADE,
        commodity      TEXT    NOT NULL,
        buy_price      INTEGER NOT NULL,
        sell_price     INTEGER NOT NULL,
        stock          INTEGER NOT NULL,
        demand         INTEGER NOT NULL,
        stock_bracket  INTEGER NOT NULL,
        demand_bracket INTEGER NOT NULL,
        origen         TEXT    NOT NULL,
        observado      TEXT    NOT NULL,
        PRIMARY KEY (market_id, commodity)
    ) WITHOUT ROWID;
    CREATE INDEX precios_por_venta ON market_prices (commodity, sell_price);
    CREATE INDEX precios_por_compra ON market_prices (commodity, buy_price);
    """,
    # commodity/3 de EDDN trae el nombre del sistema y no su dirección.
    "CREATE INDEX sistemas_por_nombre ON systems (nombre);",
    # «Sistemas a menos de X ly»: una caja sobre este índice y la distancia exacta
    # después. R*Tree no compensa (docs/decisiones.md).
    "CREATE INDEX sistemas_por_posicion ON systems (x, y, z);",
    # De dónde salió cada sistema: lo que llega por EDDN no está autenticado y es
    # provisional; el journal propio y Spansh mandan sobre un nombre o unas coordenadas.
    "ALTER TABLE systems ADD COLUMN fuente TEXT NOT NULL DEFAULT 'eddn';",
    # La retención busca los mercados caducados por su marca sin recorrer la tabla entera.
    "CREATE INDEX precios_por_antiguedad ON market_prices (observado);",
    # Buscar las estaciones de un sistema, para borrarlas o saber si quedan.
    "CREATE INDEX estaciones_por_sistema ON stations (system_address);",
    # Perfiles de búsqueda guardados (5.2). No dependen del comandante ni de la nave:
    # se pueden usar desde cualquiera. «Panther» y «panther» son el mismo perfil.
    """
    CREATE TABLE search_profiles (
        nombre     TEXT PRIMARY KEY COLLATE NOCASE,
        parametros TEXT NOT NULL
    );
    """,
    # Muestras de tiempo (5.2, 8.1). `fin` es la marca del evento que cierra la muestra:
    # al releer el journal al arrancar, la misma muestra no se guarda dos veces.
    """
    CREATE TABLE timing_samples (
        fid          TEXT    NOT NULL REFERENCES commanders(fid),
        ship_id      INTEGER NOT NULL,
        tramo        TEXT    NOT NULL,
        fin          TEXT    NOT NULL,
        segundos     REAL    NOT NULL,
        distancia_ls REAL,
        PRIMARY KEY (fid, ship_id, tramo, fin)
    ) WITHOUT ROWID;
    """,
    # Rendimiento (5.2, 7.5). Las tres se rellenan desde el journal y se releen al
    # arrancar: cada fila tiene una clave que la identifica para no repetirla.
    # Estación y sistema van por nombre porque la retención puede borrar `stations`.
    # `trade_legs` son los tramos de despegue a despegue con su ganancia real, y
    # `sessions` los bloques de actividad que Rendimiento une en sesiones.
    """
    CREATE TABLE trades (
        fid                 TEXT    NOT NULL REFERENCES commanders(fid),
        marca               TEXT    NOT NULL,
        market_id           INTEGER NOT NULL,
        commodity           TEXT    NOT NULL,
        venta               INTEGER NOT NULL,
        cantidad            INTEGER NOT NULL,
        ship_id             INTEGER,
        estacion            TEXT,
        sistema             TEXT,
        precio              INTEGER NOT NULL,
        total               INTEGER NOT NULL,
        precio_medio_compra INTEGER,
        PRIMARY KEY (fid, marca, market_id, commodity, venta, cantidad)
    ) WITHOUT ROWID;
    CREATE TABLE trade_legs (
        fid               TEXT    NOT NULL REFERENCES commanders(fid),
        salida            TEXT    NOT NULL,
        llegada           TEXT    NOT NULL,
        ship_id           INTEGER,
        segundos          REAL    NOT NULL,
        saltos            INTEGER NOT NULL,
        origen_market_id  INTEGER,
        origen_estacion   TEXT    NOT NULL,
        origen_sistema    TEXT    NOT NULL,
        destino_market_id INTEGER,
        destino_estacion  TEXT    NOT NULL,
        destino_sistema   TEXT    NOT NULL,
        distancia_ly      REAL,
        rango             REAL,
        distancia_ls      REAL    NOT NULL,
        planetaria        INTEGER NOT NULL,
        ganancia          INTEGER NOT NULL,
        toneladas         INTEGER NOT NULL,
        mercancia         TEXT,
        PRIMARY KEY (fid, salida)
    ) WITHOUT ROWID;
    CREATE TABLE sessions (
        fid          TEXT    NOT NULL REFERENCES commanders(fid),
        inicio       TEXT    NOT NULL,
        fin          TEXT    NOT NULL,
        partida      TEXT    NOT NULL,
        pausa_previa REAL,
        saldo_inicio INTEGER,
        saldo_fin    INTEGER,
        ganancia     INTEGER NOT NULL,
        toneladas    INTEGER NOT NULL,
        saltos       INTEGER NOT NULL,
        cerrado      INTEGER NOT NULL,
        PRIMARY KEY (fid, inicio)
    ) WITHOUT ROWID;
    """,
    # Alertas (5.2, 7.4): un solo juego de umbrales (la fila 1) y los avisos emitidos.
    # `clave` identifica la ruta para no repetir el aviso; `ruta` es lo que enseña la
    # interfaz, en JSON, tal como estaba al avisar.
    """
    CREATE TABLE alert_rules (
        id                    INTEGER PRIMARY KEY CHECK (id = 1),
        activadas             INTEGER NOT NULL,
        ganancia_tonelada_min INTEGER NOT NULL,
        ganancia_hora_min     INTEGER NOT NULL,
        distancia_max_ly      REAL    NOT NULL,
        antiguedad_max_h      REAL    NOT NULL,
        repetir_min           REAL    NOT NULL,
        mejora_pct            REAL    NOT NULL
    );
    CREATE TABLE alert_log (
        id            INTEGER PRIMARY KEY,
        clave         TEXT    NOT NULL,
        momento       TEXT    NOT NULL,
        modo          TEXT    NOT NULL,
        ganancia_hora REAL    NOT NULL,
        ruta          TEXT    NOT NULL
    );
    CREATE INDEX avisos_por_momento ON alert_log (momento);
    """,
)


class BaseDeDatosPosterior(RuntimeError):
    """La base la creó una versión más nueva de LUNA y esta no la entiende."""


def version(conexion: sqlite3.Connection) -> int:
    return conexion.execute("PRAGMA user_version").fetchone()[0]


def migrar(conexion: sqlite3.Connection) -> None:
    actual = version(conexion)
    if actual > len(MIGRACIONES):
        raise BaseDeDatosPosterior(f"version {actual}, esta LUNA llega a {len(MIGRACIONES)}")
    for numero, script in enumerate(MIGRACIONES[actual:], start=actual + 1):
        # executescript confirma lo pendiente antes de ejecutar, así que la
        # transacción se abre dentro del propio script.
        conexion.executescript(f"BEGIN;{script}PRAGMA user_version = {numero};COMMIT;")
