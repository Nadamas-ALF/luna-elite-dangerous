"""Reglas de retención de los mercados (sección 5.4).

Todo corre dentro de un trabajo del hilo escritor. Los datos del comandante
(regla 7) viven en otras tablas y aquí no se tocan.

- Un precio con más de `antiguedad_maxima` se borra, esté donde esté (regla 4).
- Fuera de la esfera solo se conservan los mercados que visitó el jugador
  (origen «propio») y solo `visitados` días (regla 3). Lo demás que quede fuera,
  por ejemplo tras cambiar el centro o el radio, se borra (regla 6).
- Dentro de la esfera se conserva el dato más reciente de cada estación (regla 2).
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.db.mercado import ORIGEN_PROPIO, purgar_impostores
from core.esfera import Esfera

VISITADOS_POR_DEFECTO = 3.0
ANTIGUEDAD_MAXIMA_POR_DEFECTO = 30.0

# El cuadrado de la distancia evita depender de sqrt() en SQLite. El margen impide
# que un sistema en el borde, que Python acepta, lo borre SQL por redondeo.
_MARGEN = 1 + 1e-9

_DENTRO = (
    "COALESCE((s.x - :cx) * (s.x - :cx) + (s.y - :cy) * (s.y - :cy) + (s.z - :cz) * (s.z - :cz)"
    " <= :r2, 0)"
)
# Cada trabajo del escritor borra a lo sumo esto: una transacción de millones de filas
# bloquea el escritor durante minutos y se deshace entera si LUNA se cierra a mitad.
LOTE_DE_MERCADOS = 500


@dataclass(frozen=True)
class Reglas:
    visitados_dias: float = VISITADOS_POR_DEFECTO
    antiguedad_maxima_dias: float = ANTIGUEDAD_MAXIMA_POR_DEFECTO


@dataclass(frozen=True)
class Limpieza:
    precios_viejos: int = 0
    precios_fuera: int = 0
    estaciones: int = 0
    sistemas: int = 0
    impostores: int = 0
    # Quedó trabajo por hacer: hay que volver a llamar para el siguiente lote.
    incompleta: bool = False

    @property
    def total(self) -> int:
        suma = self.precios_viejos + self.precios_fuera + self.estaciones + self.sistemas
        return suma + self.impostores

    def __add__(self, otra: Limpieza) -> Limpieza:
        """Suma de lotes; `incompleta` es la del último."""
        return Limpieza(
            self.precios_viejos + otra.precios_viejos,
            self.precios_fuera + otra.precios_fuera,
            self.estaciones + otra.estaciones,
            self.sistemas + otra.sistemas,
            self.impostores + otra.impostores,
            otra.incompleta,
        )


def _marca(fecha: datetime) -> str:
    return fecha.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parametros(esfera: Esfera) -> dict[str, float]:
    cx, cy, cz = esfera.centro
    return {"cx": cx, "cy": cy, "cz": cz, "r2": esfera.radio * esfera.radio * _MARGEN}


# Sin INDEXED BY, SQLite recorre la tabla entera en cada lote y no usa el índice.
CONSULTA_DE_CADUCADOS = (
    "SELECT DISTINCT market_id FROM market_prices INDEXED BY precios_por_antiguedad "
    "WHERE observado < ? LIMIT ?"
)


def _mercados_caducados(conexion: sqlite3.Connection, corte: str, lote: int) -> list[int]:
    return [m for (m,) in conexion.execute(CONSULTA_DE_CADUCADOS, (corte, lote))]


def _mercados_de_fuera(conexion: sqlite3.Connection, parametros: dict, lote: int) -> list[int]:
    """Mercados fuera de la esfera que no son un mercado visitado reciente."""
    # Se parte de las estaciones (pocas) y se consulta la clave de los precios; partir de los
    # precios recorrería millones de filas en cada lote.
    consulta = (
        "SELECT st.market_id FROM stations st "  # noqa: S608 - fragmentos constantes
        "LEFT JOIN systems s ON s.system_address = st.system_address "
        f"WHERE NOT {_DENTRO} AND EXISTS (SELECT 1 FROM market_prices p "
        "WHERE p.market_id = st.market_id AND (p.origen != :propio OR p.observado < :corte)) "
        "LIMIT :lote"
    )
    return [m for (m,) in conexion.execute(consulta, parametros | {"lote": lote})]


def _estaciones_de_fuera_sin_precios(
    conexion: sqlite3.Connection, parametros: dict, lote: int
) -> list[int]:
    consulta = (
        "SELECT st.market_id FROM stations st "  # noqa: S608 - fragmentos constantes
        "LEFT JOIN systems s ON s.system_address = st.system_address "
        f"WHERE NOT {_DENTRO} "
        "AND NOT EXISTS (SELECT 1 FROM market_prices p WHERE p.market_id = st.market_id) "
        "LIMIT :lote"
    )
    return [m for (m,) in conexion.execute(consulta, parametros | {"lote": lote})]


def _sistemas_de_fuera_sin_estaciones(
    conexion: sqlite3.Connection, parametros: dict, lote: int
) -> list[int]:
    consulta = (
        "SELECT s.system_address FROM systems s "  # noqa: S608 - fragmentos constantes
        f"WHERE NOT {_DENTRO} "
        "AND NOT EXISTS (SELECT 1 FROM stations st WHERE st.system_address = s.system_address) "
        "LIMIT :lote"
    )
    return [d for (d,) in conexion.execute(consulta, parametros | {"lote": lote})]


def limpiar(
    conexion: sqlite3.Connection,
    esfera: Esfera,
    reglas: Reglas,
    ahora: datetime,
    lote: int = LOTE_DE_MERCADOS,
) -> Limpieza:
    """Un lote de limpieza; si `incompleta`, quedan más y hay que volver a llamar."""
    parametros = _parametros(esfera)
    corte_general = _marca(ahora - timedelta(days=reglas.antiguedad_maxima_dias))
    parametros |= {
        "propio": ORIGEN_PROPIO,
        "corte": _marca(ahora - timedelta(days=reglas.visitados_dias)),
    }

    caducados = _mercados_caducados(conexion, corte_general, lote)
    viejos = conexion.executemany(
        "DELETE FROM market_prices WHERE market_id = ? AND observado < ?",
        [(m, corte_general) for m in caducados],
    ).rowcount

    de_fuera = _mercados_de_fuera(conexion, parametros, lote)
    fuera = conexion.executemany(
        "DELETE FROM market_prices WHERE market_id = :m "
        "AND (origen != :propio OR observado < :corte)",
        [parametros | {"m": m} for m in de_fuera],
    ).rowcount

    estaciones_ids = _estaciones_de_fuera_sin_precios(conexion, parametros, lote)
    estaciones = conexion.executemany(
        "DELETE FROM stations WHERE market_id = ?", [(m,) for m in estaciones_ids]
    ).rowcount

    sistemas_ids = _sistemas_de_fuera_sin_estaciones(conexion, parametros, lote)
    sistemas = conexion.executemany(
        "DELETE FROM systems WHERE system_address = ?", [(d,) for d in sistemas_ids]
    ).rowcount

    llenos = (len(caducados), len(de_fuera), len(estaciones_ids), len(sistemas_ids))
    return Limpieza(
        viejos,
        fuera,
        estaciones,
        sistemas,
        purgar_impostores(conexion),
        incompleta=any(n >= lote for n in llenos),
    )


def borrar_mercados(
    conexion: sqlite3.Connection, lote: int = LOTE_DE_MERCADOS, *, conservar: str | None = None
) -> bool:
    """Un lote del vaciado de la zona de mercado; True si borró algo y hay que volver a llamar.

    Primero las estaciones (sus precios se van con ellas por la cascada) y, cuando no queda
    ninguna, los sistemas. Solo toca `systems`, `stations` y `market_prices`: el resto de la
    base son datos del comandante (regla 7 de la 5.4) y no se mira.

    El sistema llamado `conservar` (el centro de la esfera) se queda sin sus estaciones: sin
    él no se podría revisar ni cambiar la esfera por su nombre hasta volver a verlo (E-37).
    """
    estaciones = [m for (m,) in conexion.execute("SELECT market_id FROM stations LIMIT ?", (lote,))]
    if estaciones:
        conexion.executemany("DELETE FROM stations WHERE market_id = ?", [(m,) for m in estaciones])
        return True
    consulta = (
        "SELECT system_address FROM systems "
        "WHERE nombre IS NULL OR nombre <> COALESCE(?, '') COLLATE NOCASE LIMIT ?"
    )
    sistemas = [d for (d,) in conexion.execute(consulta, (conservar, lote))]
    conexion.executemany("DELETE FROM systems WHERE system_address = ?", [(d,) for d in sistemas])
    return bool(sistemas)


def _distancia(x: float, y: float, z: float, cx: float, cy: float, cz: float) -> float:
    return math.dist((x, y, z), (cx, cy, cz))


def recalcular_distancias(conexion: sqlite3.Connection, esfera: Esfera) -> int:
    """`distancia_centro` de cada sistema respecto al centro vigente."""
    conexion.create_function("luna_distancia", 6, _distancia, deterministic=True)
    return conexion.execute(
        "UPDATE systems SET distancia_centro = luna_distancia(x, y, z, ?, ?, ?) "
        "WHERE x IS NOT NULL AND y IS NOT NULL AND z IS NOT NULL",
        esfera.centro,
    ).rowcount


def aplicar_esfera(
    conexion: sqlite3.Connection,
    esfera: Esfera,
    reglas: Reglas,
    ahora: datetime,
    lote: int = LOTE_DE_MERCADOS,
) -> Limpieza:
    """Tras cambiar el centro o el radio: distancias nuevas y fuera lo que ya no cabe."""
    recalcular_distancias(conexion, esfera)
    return limpiar(conexion, esfera, reglas, ahora, lote)
