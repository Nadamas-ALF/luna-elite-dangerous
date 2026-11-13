"""Tablas de mercado (sección 5.1): trabajos para el hilo escritor.

Los datos propios los escribe el hilo del núcleo y los de EDDN su suscriptor,
los dos por la cola del escritor. Spansh (fase 4) reutilizará `guardar_de_red`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from core.catalogo import Mercancia
from core.journal.mercado import Articulo

ORIGEN_PROPIO = "propio"
ORIGEN_EDDN = "eddn"
ORIGEN_SPANSH = "spansh"

# Qué tan fiable es la fuente de un sistema. Solo EDDN es provisional.
FUENTE_PROPIO = "propio"
FUENTE_SPANSH = "spansh"
FUENTE_EDDN = "eddn"


@dataclass(frozen=True)
class Sistema:
    system_address: int
    nombre: str
    posicion: tuple[float, float, float] | None
    distancia_centro: float | None
    fuente: str = FUENTE_EDDN


@dataclass(frozen=True)
class Estacion:
    market_id: int
    nombre: str
    categoria: str
    plataforma: str | None
    distancia_ls: float | None
    planetaria: bool


# Un dato de fuente fiable sustituye al de un sistema provisional; entre iguales manda el guardado.
_MANDA_LA_NUEVA = "(fuente = 'eddn' AND excluded.fuente != 'eddn')"


def _conservar(columna: str) -> str:
    return (
        f"{columna} = CASE WHEN {_MANDA_LA_NUEVA} THEN COALESCE(excluded.{columna}, {columna}) "
        f"ELSE COALESCE({columna}, excluded.{columna}) END"
    )


_GUARDAR_SISTEMA = (
    "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, actualizado, fuente) "  # noqa: S608, E501
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(system_address) DO UPDATE SET "
    f"nombre = CASE WHEN {_MANDA_LA_NUEVA} THEN excluded.nombre ELSE nombre END, "
    f"{_conservar('x')}, {_conservar('y')}, {_conservar('z')}, "
    f"{_conservar('distancia_centro')}, "
    "actualizado = MAX(actualizado, excluded.actualizado), "
    "fuente = CASE WHEN fuente = 'eddn' THEN excluded.fuente ELSE fuente END"
)


def guardar_sistema(conexion: sqlite3.Connection, sistema: Sistema, observado: str) -> None:
    """Las coordenadas y el nombre de un sistema no cambian: lo ya guardado no se pisa.

    Así un mensaje falso de EDDN no puede mover un sistema que ya conocemos. La
    excepción es un sistema solo conocido por EDDN, que el journal propio o Spansh
    corrigen.
    """
    x, y, z = sistema.posicion or (None, None, None)
    conexion.execute(
        _GUARDAR_SISTEMA,
        (
            sistema.system_address,
            sistema.nombre,
            x,
            y,
            z,
            sistema.distancia_centro,
            observado,
            sistema.fuente,
        ),
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
            "categoria = COALESCE(excluded.categoria, categoria), rara = MAX(rara, excluded.rara)",
            (a.simbolo, a.categoria, int(a.rara)),
        )
        if columna and a.nombre:
            conexion.execute(
                f"UPDATE commodities SET {columna} = ? WHERE simbolo = ?",  # noqa: S608 - columna de una lista fija
                (a.nombre, a.simbolo),
            )


def sembrar_mercancias(conexion: sqlite3.Connection, tabla: dict[str, Mercancia]) -> None:
    """Datos de la tabla estática; nunca pisan un nombre que ya salió del juego.

    La marca «rara» solo sube: EDDN y Spansh no la traen, y sin ella el filtro de
    mercancías raras de la búsqueda las trataría como corrientes.
    """
    conexion.executemany(
        "INSERT INTO commodities (simbolo, nombre_en, nombre_es, categoria, rara) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(simbolo) DO UPDATE SET "
        "nombre_en = COALESCE(nombre_en, excluded.nombre_en), "
        "nombre_es = COALESCE(nombre_es, excluded.nombre_es), "
        "categoria = COALESCE(categoria, excluded.categoria), "
        "rara = MAX(rara, excluded.rara)",
        [(s, m.en, m.es, m.categoria, int(m.rara)) for s, m in tabla.items()],
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
    """El sistema con ese nombre y coordenadas conocidas; None si no hay o es dudoso.

    Los nombres son únicos en el juego: si hay dos con el mismo, uno es falso. Gana
    el único de fuente fiable; si no lo hay, no se adivina. Para leer desde otro
    hilo, con conexión propia.
    """
    filas = conexion.execute(
        "SELECT system_address, x, y, z, distancia_centro, fuente FROM systems "
        "WHERE nombre = ? AND x IS NOT NULL AND y IS NOT NULL AND z IS NOT NULL",
        (nombre,),
    ).fetchall()
    if len(filas) > 1:
        filas = [f for f in filas if f[5] != FUENTE_EDDN]
    if len(filas) != 1:
        return None
    fila = filas[0]
    return Sistema(fila[0], nombre, (fila[1], fila[2], fila[3]), fila[4], fila[5])


def nombre_en_uso_por_otro(conexion: sqlite3.Connection, nombre: str, direccion: int) -> bool:
    """True si la base ya tiene ese nombre con otra dirección: el recién llegado no cuadra."""
    fila = conexion.execute(
        "SELECT 1 FROM systems WHERE nombre = ? AND system_address != ? LIMIT 1",
        (nombre, direccion),
    ).fetchone()
    return fila is not None


def purgar_impostores(conexion: sqlite3.Connection) -> int:
    """Borra los sistemas provisionales que repiten el nombre de uno de fuente fiable.

    También sus estaciones y precios. Devuelve cuántos sistemas se fueron.
    """
    direcciones = [
        d
        for (d,) in conexion.execute(
            "SELECT i.system_address FROM systems i WHERE i.fuente = 'eddn' AND EXISTS ("
            "SELECT 1 FROM systems t WHERE t.nombre = i.nombre AND t.fuente != 'eddn' "
            "AND t.system_address != i.system_address)"
        )
    ]
    for direccion in direcciones:
        conexion.execute("DELETE FROM stations WHERE system_address = ?", (direccion,))
        conexion.execute("DELETE FROM systems WHERE system_address = ?", (direccion,))
    return len(direcciones)


def sistema_por_direccion(conexion: sqlite3.Connection, system_address: int) -> Sistema | None:
    """Como `sistema_por_nombre`, por la clave primaria."""
    fila = conexion.execute(
        "SELECT nombre, x, y, z, distancia_centro, fuente FROM systems "
        "WHERE system_address = ? AND x IS NOT NULL AND y IS NOT NULL AND z IS NOT NULL",
        (system_address,),
    ).fetchone()
    if fila is None:
        return None
    return Sistema(system_address, fila[0], (fila[1], fila[2], fila[3]), fila[4], fila[5])


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


def completar_estacion(
    conexion: sqlite3.Connection, estacion: Estacion, system_address: int, observado: str
) -> None:
    """Alta de una estación descrita por Spansh, que solo completa lo que falte.

    Lo que vio el propio jugador en un `Docked` vale más; Spansh solo sustituye
    a «desconocida» (una estación que EDDN conoció por su mercado) y rellena huecos.
    """
    conexion.execute(
        "INSERT INTO stations (market_id, system_address, nombre, categoria, plataforma, "
        "distancia_ls, planetaria, actualizado) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(market_id) DO UPDATE SET "
        "system_address = excluded.system_address, "
        "categoria = CASE WHEN categoria = 'desconocida' THEN excluded.categoria "
        "ELSE categoria END, "
        "planetaria = CASE WHEN categoria = 'desconocida' THEN excluded.planetaria "
        "ELSE planetaria END, "
        "plataforma = COALESCE(plataforma, excluded.plataforma), "
        "distancia_ls = COALESCE(distancia_ls, excluded.distancia_ls), "
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
