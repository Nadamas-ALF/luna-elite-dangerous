"""Tablas de mercado (sección 5.1): trabajos para el hilo escritor.

Los datos propios los escribe el hilo del núcleo y los de EDDN su suscriptor,
los dos por la cola del escritor. Spansh (fase 4) reutilizará `guardar_de_red`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from core.journal.mercado import Articulo

ORIGEN_PROPIO = "propio"
ORIGEN_EDDN = "eddn"


@dataclass(frozen=True)
class Sistema:
    system_address: int
    nombre: str
    posicion: tuple[float, float, float] | None
    distancia_centro: float | None


@dataclass(frozen=True)
class Estacion:
    market_id: int
    nombre: str
    categoria: str
    plataforma: str | None
    distancia_ls: float | None
    planetaria: bool


def guardar_sistema(conexion: sqlite3.Connection, sistema: Sistema, observado: str) -> None:
    """Las coordenadas y el nombre de un sistema no cambian: lo ya guardado no se pisa.

    Así un mensaje falso de EDDN no puede mover un sistema que ya conocemos.
    """
    x, y, z = sistema.posicion or (None, None, None)
    conexion.execute(
        "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, actualizado) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(system_address) DO UPDATE SET "
        "x = COALESCE(x, excluded.x), y = COALESCE(y, excluded.y), z = COALESCE(z, excluded.z), "
        "distancia_centro = COALESCE(distancia_centro, excluded.distancia_centro), "
        "actualizado = MAX(actualizado, excluded.actualizado)",
        (sistema.system_address, sistema.nombre, x, y, z, sistema.distancia_centro, observado),
    )


def guardar_estacion(
    conexion: sqlite3.Connection, estacion: Estacion, system_address: int | None, observado: str
) -> None:
    conexion.execute(
        "INSERT INTO stations (market_id, system_address, nombre, categoria, plataforma, "
        "distancia_ls, planetaria, actualizado) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(market_id) DO UPDATE SET "
        "system_address = COALESCE(excluded.system_address, system_address), "
        "nombre = excluded.nombre, categoria = excluded.categoria, "
        "plataforma = COALESCE(excluded.plataforma, plataforma), "
        "distancia_ls = COALESCE(excluded.distancia_ls, distancia_ls), "
        "planetaria = excluded.planetaria, actualizado = MAX(actualizado, excluded.actualizado)",
        (
            estacion.market_id,
            system_address,
            estacion.nombre,
            estacion.categoria,
            estacion.plataforma,
            estacion.distancia_ls,
            int(estacion.planetaria),
            observado,
        ),
    )


def guardar_precios(
    conexion: sqlite3.Connection,
    market_id: int,
    articulos: tuple[Articulo, ...],
    origen: str,
    observado: str,
) -> bool:
    """Sustituye el mercado de la estación si el dato es más reciente que el guardado.

    Regla 1 de la sección 5.4: gana la marca de tiempo, venga de donde venga.
    Devuelve False cuando ya había un dato igual de reciente o más.
    """
    (guardado,) = conexion.execute(
        "SELECT MAX(observado) FROM market_prices WHERE market_id = ?", (market_id,)
    ).fetchone()
    if guardado is not None and guardado >= observado:
        return False
    conexion.execute("DELETE FROM market_prices WHERE market_id = ?", (market_id,))
    conexion.executemany(
        "INSERT INTO market_prices (market_id, commodity, buy_price, sell_price, stock, demand, "
        "stock_bracket, demand_bracket, origen, observado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                market_id,
                a.simbolo,
                a.precio_compra,
                a.precio_venta,
                a.stock,
                a.demanda,
                a.nivel_stock,
                a.nivel_demanda,
                origen,
                observado,
            )
            for a in articulos
            if a.se_comercia
        ],
    )
    return True


def guardar_mercancias(
    conexion: sqlite3.Connection, articulos: tuple[Articulo, ...], idioma: str | None
) -> None:
    """Nombres de las mercancías; solo se toma el localizado si se sabe en qué idioma está."""
    columna = {"es": "nombre_es", "en": "nombre_en"}.get(idioma or "")
    for a in articulos:
        conexion.execute(
            "INSERT INTO commodities (simbolo, categoria, rara) VALUES (?, ?, ?) "
            "ON CONFLICT(simbolo) DO UPDATE SET "
            "categoria = COALESCE(excluded.categoria, categoria), rara = excluded.rara",
            (a.simbolo, a.categoria, int(a.rara)),
        )
        if columna and a.nombre:
            conexion.execute(
                f"UPDATE commodities SET {columna} = ? WHERE simbolo = ?",  # noqa: S608 - columna de una lista fija
                (a.nombre, a.simbolo),
            )


def sembrar_mercancias(
    conexion: sqlite3.Connection, tabla: dict[str, tuple[str | None, str | None]]
) -> None:
    """Nombres de la tabla estática; nunca pisan uno que ya salió del juego."""
    conexion.executemany(
        "INSERT INTO commodities (simbolo, nombre_en, nombre_es) VALUES (?, ?, ?) "
        "ON CONFLICT(simbolo) DO UPDATE SET "
        "nombre_en = COALESCE(nombre_en, excluded.nombre_en), "
        "nombre_es = COALESCE(nombre_es, excluded.nombre_es)",
        [(simbolo, en, es) for simbolo, (en, es) in tabla.items()],
    )


@dataclass(frozen=True)
class MercadoPropio:
    sistema: Sistema | None
    estacion: Estacion
    observado: str
    articulos: tuple[Articulo, ...]
    idioma: str | None


def guardar_propio(conexion: sqlite3.Connection, mercado: MercadoPropio) -> bool:
    """Un mercado abierto por el jugador, entero. False si ya había uno más reciente."""
    if mercado.sistema is not None:
        guardar_sistema(conexion, mercado.sistema, mercado.observado)
    direccion = mercado.sistema.system_address if mercado.sistema else None
    guardar_estacion(conexion, mercado.estacion, direccion, mercado.observado)
    guardar_mercancias(conexion, mercado.articulos, mercado.idioma)
    return guardar_precios(
        conexion,
        mercado.estacion.market_id,
        mercado.articulos,
        ORIGEN_PROPIO,
        mercado.observado,
    )


def sistema_por_nombre(conexion: sqlite3.Connection, nombre: str) -> Sistema | None:
    """Un sistema con coordenadas conocidas. Para leer desde otro hilo, con conexión propia."""
    fila = conexion.execute(
        "SELECT system_address, x, y, z, distancia_centro FROM systems "
        "WHERE nombre = ? AND x IS NOT NULL AND y IS NOT NULL AND z IS NOT NULL LIMIT 1",
        (nombre,),
    ).fetchone()
    if fila is None:
        return None
    return Sistema(fila[0], nombre, (fila[1], fila[2], fila[3]), fila[4])


def sistema_por_direccion(conexion: sqlite3.Connection, system_address: int) -> Sistema | None:
    """Como `sistema_por_nombre`, por la clave primaria."""
    fila = conexion.execute(
        "SELECT nombre, x, y, z, distancia_centro FROM systems "
        "WHERE system_address = ? AND x IS NOT NULL AND y IS NOT NULL AND z IS NOT NULL",
        (system_address,),
    ).fetchone()
    if fila is None:
        return None
    return Sistema(system_address, fila[0], (fila[1], fila[2], fila[3]), fila[4])


def registrar_estacion(
    conexion: sqlite3.Connection, estacion: Estacion, system_address: int, observado: str
) -> None:
    """Alta de una estación de la que solo se sabe el nombre, sin pisar lo ya conocido.

    Un mercado de EDDN no dice qué tipo de estación es: si un `Docked` ya la
    describió, esa descripción vale más que la categoría «desconocida».
    """
    conexion.execute(
        "INSERT INTO stations (market_id, system_address, nombre, categoria, plataforma, "
        "distancia_ls, planetaria, actualizado) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(market_id) DO UPDATE SET "
        "system_address = excluded.system_address, "
        "actualizado = MAX(actualizado, excluded.actualizado)",
        (
            estacion.market_id,
            system_address,
            estacion.nombre,
            estacion.categoria,
            estacion.plataforma,
            estacion.distancia_ls,
            int(estacion.planetaria),
            observado,
        ),
    )


def guardar_de_red(
    conexion: sqlite3.Connection,
    sistema: Sistema,
    estacion: Estacion,
    articulos: tuple[Articulo, ...],
    origen: str,
    observado: str,
) -> bool:
    """Un mercado llegado de la red. False si ya había uno igual de reciente o más."""
    guardar_sistema(conexion, sistema, observado)
    registrar_estacion(conexion, estacion, sistema.system_address, observado)
    return guardar_precios(conexion, estacion.market_id, articulos, origen, observado)


def guardar_visita(
    conexion: sqlite3.Connection, sistema: Sistema, estacion: Estacion | None, observado: str
) -> None:
    """Un sistema visto por alguien (y la estación donde atracó, si la hubo)."""
    guardar_sistema(conexion, sistema, observado)
    if estacion is not None:
        guardar_estacion(conexion, estacion, sistema.system_address, observado)
