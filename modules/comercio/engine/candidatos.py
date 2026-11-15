"""Lo que el motor lee de la base: estaciones y precios que pasan los filtros del perfil.

El filtro se hace en SQLite (sección 2: no se mandan miles de precios a la
interfaz, y tampoco al motor). La esfera de búsqueda es una caja sobre
`sistemas_por_posicion` y la distancia exacta se comprueba después, como en la
retención. Los niveles de stock y demanda no se usan: Spansh los deja en -1
(«desconocido») y la cantidad dice lo mismo cuando se conoce.

Estación sin plataforma o sin distancia a la estrella: fuera. No se puede saber
si la nave cabe ni cuánto tarda en llegar.
"""

from __future__ import annotations

import math
import sqlite3
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from modules.comercio.engine.perfil import (
    PLATAFORMAS,
    TIPO_ASENTAMIENTO,
    TIPO_COLONIZACION,
    TIPO_ORBITAL,
    TIPO_PLANETARIO,
    TIPO_PUESTO,
    Perfil,
)

Posicion = tuple[float, float, float]

FORMATO_MARCA = "%Y-%m-%dT%H:%M:%SZ"

# Cada cuántas filas se mira si la búsqueda se canceló: casi todo su tiempo se va en leer.
FILAS_ENTRE_COMPROBACIONES = 5_000

# Fragmentos fijos: nada de lo que manda la interfaz entra en el texto de la consulta.
_CONDICION_DE_TIPO = {
    TIPO_ORBITAL: "(s.categoria = 'orbital' AND s.planetaria = 0)",
    TIPO_PUESTO: "(s.categoria = 'puesto_avanzado' AND s.planetaria = 0)",
    TIPO_PLANETARIO: "(s.categoria IN ('orbital', 'puesto_avanzado') AND s.planetaria = 1)",
    TIPO_ASENTAMIENTO: "s.categoria = 'asentamiento'",
    TIPO_COLONIZACION: "s.categoria = 'colonizacion'",
}
# Una estación de EDDN sin `Docked` previo no tiene categoría; si tiene plataforma, vale.
_SIEMPRE = "s.categoria = 'desconocida'"

_DESDE = (
    "FROM stations s JOIN systems y ON y.system_address = s.system_address "
    "WHERE y.x BETWEEN ? AND ? AND y.y BETWEEN ? AND ? AND y.z BETWEEN ? AND ? "
    "AND s.distancia_ls <= ? AND s.plataforma IN ({plataformas}) AND ({tipos})"
)

_ESTACIONES = (
    "SELECT s.market_id, s.nombre, y.nombre, y.x, y.y, y.z, s.distancia_ls, s.planetaria " + _DESDE
)

_PRECIOS = (
    "SELECT p.market_id, p.commodity, p.buy_price, p.sell_price, p.stock, p.demand, "  # noqa: S608
    "p.origen, p.observado FROM market_prices p WHERE p.market_id IN (SELECT s.market_id "
    + _DESDE
    + ") AND p.observado >= ? AND p.origen IN ({origenes}) "
    "AND ((p.stock >= ? AND p.buy_price > 0) OR (p.demand > 0 AND p.sell_price > 0)) "
    "AND (? OR p.commodity NOT IN (SELECT simbolo FROM commodities WHERE rara = 1))"
)


class BusquedaCancelada(Exception):
    """Llegó una búsqueda nueva antes de que esta terminara (E-16)."""


@dataclass(frozen=True, slots=True)
class Estacion:
    market_id: int
    nombre: str
    sistema: str
    posicion: Posicion
    distancia_ls: float
    planetaria: bool
    distancia_origen: float


@dataclass(frozen=True, slots=True)
class Precio:
    """Un lado de un trato: lo que cuesta o lo que pagan, y cuánto hay."""

    estacion: Estacion
    mercancia: str
    precio: int
    cantidad: int
    origen: str
    observado: str
    horas: float


@dataclass
class Candidatos:
    estaciones: dict[int, Estacion] = field(default_factory=dict)
    ofertas: dict[str, list[Precio]] = field(default_factory=lambda: defaultdict(list))
    demandas: dict[str, list[Precio]] = field(default_factory=lambda: defaultdict(list))
    ofertas_de: dict[int, dict[str, Precio]] = field(default_factory=lambda: defaultdict(dict))
    demandas_de: dict[int, dict[str, Precio]] = field(default_factory=lambda: defaultdict(dict))

    def anadir_oferta(self, precio: Precio) -> None:
        self.ofertas[precio.mercancia].append(precio)
        self.ofertas_de[precio.estacion.market_id][precio.mercancia] = precio

    def anadir_demanda(self, precio: Precio) -> None:
        self.demandas[precio.mercancia].append(precio)
        self.demandas_de[precio.estacion.market_id][precio.mercancia] = precio


def marca(momento: datetime) -> str:
    return momento.astimezone(UTC).strftime(FORMATO_MARCA)


def _plataformas_validas(necesaria: str) -> tuple[str, ...]:
    return PLATAFORMAS[PLATAFORMAS.index(necesaria) :]


def _consulta(plantilla: str, perfil: Perfil) -> str:
    plataformas = _plataformas_validas(perfil.plataforma)
    tipos = " OR ".join([_SIEMPRE, *(_CONDICION_DE_TIPO[t] for t in perfil.tipos)])
    return plantilla.format(
        plataformas=", ".join("?" * len(plataformas)),
        tipos=tipos,
        origenes=", ".join("?" * len(perfil.origenes)),
    )


def _parametros_de_estacion(perfil: Perfil, centro: Posicion) -> list:
    caja = [
        v for eje in centro for v in (eje - perfil.distancia_max_ly, eje + perfil.distancia_max_ly)
    ]
    return [*caja, perfil.distancia_max_ls, *_plataformas_validas(perfil.plataforma)]


def _estaciones(
    conexion: sqlite3.Connection, perfil: Perfil, centro: Posicion
) -> dict[int, Estacion]:
    sql = _consulta(_ESTACIONES, perfil)
    estaciones = {}
    for market_id, nombre, sistema, x, y, z, ls, planetaria in conexion.execute(
        sql, _parametros_de_estacion(perfil, centro)
    ):
        distancia = math.dist(centro, (x, y, z))
        if distancia <= perfil.distancia_max_ly:
            estaciones[market_id] = Estacion(
                market_id, nombre, sistema, (x, y, z), ls, bool(planetaria), distancia
            )
    return estaciones


def _momento(observado: str) -> datetime | None:
    """`Market.json` llega sin validar su marca: una ilegible descarta el precio, no la búsqueda."""
    try:
        momento = datetime.fromisoformat(observado)
    except (TypeError, ValueError):
        return None
    return momento if momento.tzinfo is not None else None


class _Edades:
    """Horas desde cada marca; un mercado entero comparte la suya, así que se recuerdan."""

    def __init__(self, ahora: datetime) -> None:
        self._ahora = ahora
        self._vistas: dict[str, float | None] = {}

    def horas(self, observado: str) -> float | None:
        if observado not in self._vistas:
            momento = _momento(observado)
            self._vistas[observado] = (
                None
                if momento is None
                else max((self._ahora - momento).total_seconds() / 3600, 0.0)
            )
        return self._vistas[observado]


def cargar(
    conexion: sqlite3.Connection,
    perfil: Perfil,
    centro: Posicion,
    ahora: datetime,
    raras: bool | None = None,
    parar: threading.Event | None = None,
) -> Candidatos:
    """`raras` None sigue al perfil; vender la carga las incluye siempre (ya están compradas).

    Si `parar` se activa, lanza `BusquedaCancelada`: así una búsqueda nueva no
    espera ni suma memoria a la anterior.
    """
    candidatos = Candidatos(estaciones=_estaciones(conexion, perfil, centro))
    limite = marca(ahora - timedelta(hours=perfil.antiguedad_max_h))
    # Con stock mínimo 0 seguiría sin valer una oferta vacía.
    stock_minimo = max(perfil.stock_minimo, 1)
    parametros = [
        *_parametros_de_estacion(perfil, centro),
        limite,
        *perfil.origenes,
        stock_minimo,
        perfil.raras if raras is None else raras,
    ]
    edades = _Edades(ahora)
    for n, fila in enumerate(conexion.execute(_consulta(_PRECIOS, perfil), parametros)):
        if parar is not None and n % FILAS_ENTRE_COMPROBACIONES == 0 and parar.is_set():
            raise BusquedaCancelada
        _anadir(candidatos, fila, stock_minimo, edades)
    return candidatos


def _anadir(candidatos: Candidatos, fila: tuple, stock_minimo: int, edades: _Edades) -> None:
    market_id, mercancia, compra, venta, stock, demanda, origen, observado = fila
    estacion = candidatos.estaciones.get(market_id)
    if estacion is None:  # dentro de la caja pero fuera de la esfera
        return
    horas = edades.horas(observado)
    if horas is None:
        return
    if stock >= stock_minimo and compra > 0:
        candidatos.anadir_oferta(
            Precio(estacion, mercancia, compra, stock, origen, observado, horas)
        )
    if demanda > 0 and venta > 0:
        candidatos.anadir_demanda(
            Precio(estacion, mercancia, venta, demanda, origen, observado, horas)
        )


_ESTACION_ACTUAL = (
    "SELECT s.market_id, s.nombre, y.nombre, y.x, y.y, y.z, s.distancia_ls, s.planetaria "
    "FROM stations s JOIN systems y ON y.system_address = s.system_address "
    "WHERE s.market_id = ? AND y.x IS NOT NULL AND y.y IS NOT NULL AND y.z IS NOT NULL"
)

_OFERTAS_ACTUALES = (
    "SELECT commodity, buy_price, stock, origen, observado FROM market_prices "
    "WHERE market_id = ? AND stock >= ? AND buy_price > 0 AND origen IN ({origenes}) "
    "AND (? OR commodity NOT IN (SELECT simbolo FROM commodities WHERE rara = 1))"
)


def _estacion_actual(conexion: sqlite3.Connection, market_id: int) -> Estacion | None:
    fila = conexion.execute(_ESTACION_ACTUAL, (market_id,)).fetchone()
    if fila is None:
        return None
    market_id, nombre, sistema, x, y, z, ls, planetaria = fila
    return Estacion(market_id, nombre, sistema, (x, y, z), ls or 0.0, bool(planetaria), 0.0)


def ofertas_de_la_estacion(
    conexion: sqlite3.Connection, market_id: int, perfil: Perfil, ahora: datetime
) -> list[Precio]:
    """Lo que vende la estación donde estás atracado.

    Ni el tipo, ni la plataforma, ni los ls, ni la antigüedad la excluyen: ya
    estás en ella. La antigüedad cuenta en la confianza y se enseña.
    """
    estacion = _estacion_actual(conexion, market_id)
    if estacion is None:
        return []
    sql = _OFERTAS_ACTUALES.format(origenes=", ".join("?" * len(perfil.origenes)))
    parametros = [market_id, max(perfil.stock_minimo, 1), *perfil.origenes, perfil.raras]
    edades = _Edades(ahora)
    return [
        Precio(estacion, mercancia, compra, stock, origen, observado, horas)
        for mercancia, compra, stock, origen, observado in conexion.execute(sql, parametros)
        if (horas := edades.horas(observado)) is not None
    ]
