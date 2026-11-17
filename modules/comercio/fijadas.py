"""Rutas fijadas (prefase 8, bloque 5): estaciones en orden que el usuario quiere repetir.

Se guardan las paradas y nunca cifras: los precios y los tiempos se recalculan con lo de
hoy (`estimar.py`). La tabla `pinned_routes` es zona del comandante y no depende de
`stations` ni de `systems`, así que borrar los mercados no la toca.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass

from modules.comercio.engine.perfil import PerfilInvalido

registro = logging.getLogger("luna.comercio.fijadas")

MAXIMO_DE_RUTAS = 50
MINIMO_DE_PARADAS = 2
MAXIMO_DE_PARADAS = 10
LARGO_MAXIMO_DE_MERCANCIA = 64
ENTERO_MAXIMO_DE_SQLITE = 2**63 - 1

ESTADO_NUEVA = "nueva"
ESTADO_YA_FIJADA = "ya_fijada"
ESTADO_LIMITE = "limite"


class RutaInvalida(PerfilInvalido):
    """`campo` dice qué parte de la ruta rechazar en la interfaz."""


class EstacionDesconocida(ValueError):
    """`posicion` es el lugar de la lista de la parada que la base no conoce."""

    def __init__(self, posicion: int) -> None:
        super().__init__(posicion)
        self.posicion = posicion


@dataclass(frozen=True, slots=True)
class ParadaPedida:
    market_id: int
    mercancia: str | None


@dataclass(frozen=True, slots=True)
class RutaPedida:
    cerrada: bool
    paradas: tuple[ParadaPedida, ...]


def validar(datos: object) -> RutaPedida:
    """Lo que manda la interfaz al fijar o estimar: forma exacta, sin claves de más ni de menos."""
    if not isinstance(datos, dict) or set(datos) != {"cerrada", "paradas"}:
        raise RutaInvalida("ruta")
    if not isinstance(datos["cerrada"], bool):
        raise RutaInvalida("cerrada")
    lista = datos["paradas"]
    if not isinstance(lista, list) or not MINIMO_DE_PARADAS <= len(lista) <= MAXIMO_DE_PARADAS:
        raise RutaInvalida("paradas")
    paradas = tuple(_parada(p, i) for i, p in enumerate(lista))
    ids = [p.market_id for p in paradas]
    seguidas = zip(ids, ids[1:] + ids[:1] if datos["cerrada"] else ids[1:], strict=False)
    for i, (a, b) in enumerate(seguidas):
        if a == b:
            raise RutaInvalida(f"paradas.{(i + 1) % len(ids)}.market_id")
    return RutaPedida(datos["cerrada"], paradas)


def _parada(dato: object, posicion: int) -> ParadaPedida:
    if not isinstance(dato, dict) or set(dato) != {"market_id", "mercancia"}:
        raise RutaInvalida(f"paradas.{posicion}")
    market_id, mercancia = dato["market_id"], dato["mercancia"]
    # SQLite guarda enteros de 64 bits: uno mayor lanza OverflowError al consultarlo.
    if isinstance(market_id, bool) or not isinstance(market_id, int):
        raise RutaInvalida(f"paradas.{posicion}.market_id")
    if not 0 < market_id <= ENTERO_MAXIMO_DE_SQLITE:
        raise RutaInvalida(f"paradas.{posicion}.market_id")
    if mercancia is not None and (
        not isinstance(mercancia, str)
        or not 1 <= len(mercancia) <= LARGO_MAXIMO_DE_MERCANCIA
        or not mercancia.isprintable()
    ):
        raise RutaInvalida(f"paradas.{posicion}.mercancia")
    return ParadaPedida(market_id, mercancia)


def clave(cerrada: bool, market_ids: list[int]) -> str:
    """La misma ruta da la misma clave: un bucle lo es empiece por donde empiece."""
    if not cerrada:
        return "fija:a:" + ",".join(map(str, market_ids))
    vueltas = (market_ids[i:] + market_ids[:i] for i in range(len(market_ids)))
    return "fija:c:" + ",".join(map(str, min(vueltas)))


def completar(conexion: sqlite3.Connection, pedida: RutaPedida) -> dict:
    """Añade estación y sistema de cada parada: solo se fija lo que la base conoce."""
    paradas = []
    for posicion, parada in enumerate(pedida.paradas):
        fila = conexion.execute(
            "SELECT s.nombre, y.nombre FROM stations s "
            "JOIN systems y ON y.system_address = s.system_address WHERE s.market_id = ?",
            (parada.market_id,),
        ).fetchone()
        if fila is None:
            raise EstacionDesconocida(posicion)
        paradas.append(
            {
                "market_id": parada.market_id,
                "estacion": fila[0],
                "sistema": fila[1],
                "mercancia": _conocida(conexion, parada.mercancia),
            }
        )
    return {"cerrada": pedida.cerrada, "paradas": paradas}


def _conocida(conexion: sqlite3.Connection, mercancia: str | None) -> str | None:
    if mercancia is None:
        return None
    existe = conexion.execute("SELECT 1 FROM commodities WHERE simbolo = ?", (mercancia,))
    return mercancia if existe.fetchone() else None


def guardar(conexion: sqlite3.Connection, ruta: dict, creada: str) -> tuple[str, int | None]:
    """Trabajo del escritor. Devuelve (estado, id): una repetida da su id y el límite, None."""
    clave_ = clave(ruta["cerrada"], [p["market_id"] for p in ruta["paradas"]])
    existente = conexion.execute("SELECT id FROM pinned_routes WHERE clave = ?", (clave_,))
    fila = existente.fetchone()
    if fila is not None:
        return ESTADO_YA_FIJADA, fila[0]
    if conexion.execute("SELECT COUNT(*) FROM pinned_routes").fetchone()[0] >= MAXIMO_DE_RUTAS:
        return ESTADO_LIMITE, None
    cursor = conexion.execute(
        "INSERT INTO pinned_routes (clave, cerrada, paradas, creada) VALUES (?, ?, ?, ?)",
        (clave_, int(ruta["cerrada"]), json.dumps(ruta["paradas"], ensure_ascii=False), creada),
    )
    return ESTADO_NUEVA, cursor.lastrowid


def borrar(conexion: sqlite3.Connection, id_: int) -> None:
    conexion.execute("DELETE FROM pinned_routes WHERE id = ?", (id_,))


def listar(conexion: sqlite3.Connection) -> list[dict]:
    """De la más antigua a la más nueva. Una fila que no se entiende se salta y queda anotada."""
    rutas = []
    filas = conexion.execute(
        "SELECT id, clave, cerrada, paradas, creada FROM pinned_routes ORDER BY id"
    )
    for id_, clave_, cerrada, paradas, creada in filas:
        leidas = _leer_paradas(paradas)
        if leidas is None or cerrada not in (0, 1):
            registro.warning("la ruta fijada %d no se entiende y se salta", id_)
            continue
        rutas.append(
            {
                "id": id_,
                "clave": clave_,
                "cerrada": bool(cerrada),
                "paradas": leidas,
                "creada": creada,
            }
        )
    return rutas


def _leer_paradas(texto: str) -> list[dict] | None:
    try:
        lista = json.loads(texto)
    except ValueError:
        return None
    if not isinstance(lista, list) or not MINIMO_DE_PARADAS <= len(lista) <= MAXIMO_DE_PARADAS:
        return None
    if not all(_parada_guardada(p) for p in lista):
        return None
    return lista


def _parada_guardada(dato: object) -> bool:
    if not isinstance(dato, dict) or set(dato) != {"market_id", "estacion", "sistema", "mercancia"}:
        return False
    market_id = dato["market_id"]
    return (
        isinstance(market_id, int)
        and not isinstance(market_id, bool)
        and isinstance(dato["estacion"], str)
        and isinstance(dato["sistema"], str)
        and (dato["mercancia"] is None or isinstance(dato["mercancia"], str))
    )
