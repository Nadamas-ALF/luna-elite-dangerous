"""Operaciones de mercado y tramos de comercio (sección 7.5) sacados del journal.

Una operación es un `MarketBuy` o un `MarketSell`. Un tramo va de despegar de una
estación donde comerciaste a terminar en la siguiente donde comerciaste, y solo
cuenta si en ella vendes con ganancia: reposicionarse no es la ruta. La parada de
destino termina al despegar o, si el juego se cierra atracado, en su última
operación. Un cierre del juego, una muerte o un viaje que no es de tu nave por medio
anulan el tramo (`docs/decisiones.md`, «Fase 7»).

`Libro` es inmutable, como `Estado` y `Cronometro`: `anotar` devuelve uno nuevo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime

from core import estacion as clasificacion
from core import nave as modelo_nave
from core.journal import mercado, tiempos
from core.state.estado import Estado


@dataclass(frozen=True, slots=True)
class Operacion:
    marca: str
    market_id: int
    estacion: str | None
    sistema: str | None
    simbolo: str
    venta: bool
    cantidad: int
    precio: int
    total: int
    # Solo en las ventas: lo que pagaste de media por lo vendido (`AvgPricePaid`).
    precio_medio_compra: int | None = None

    @property
    def ganancia(self) -> int | None:
        """Lo vendido menos lo que costó; None si no es una venta o el juego no sabe lo pagado."""
        if not self.venta or not self.precio_medio_compra:
            return None
        return self.cantidad * (self.precio - self.precio_medio_compra)


@dataclass(frozen=True, slots=True)
class Lugar:
    market_id: int | None
    estacion: str
    sistema: str
    posicion: tuple[float, float, float] | None


@dataclass(frozen=True, slots=True)
class Tramo:
    """`salida` (el despegue del origen) identifica el tramo al releer el journal."""

    ship_id: int | None
    origen: Lugar
    destino: Lugar
    salida: str
    llegada: str
    segundos: float
    saltos: int
    distancia_ly: float | None
    rango: float | None
    distancia_ls: float
    planetaria: bool
    ganancia: int
    toneladas: int
    mercancia: str | None


@dataclass(frozen=True, slots=True)
class _Parada:
    lugar: Lugar
    distancia_ls: float
    planetaria: bool
    rango: float | None
    ship_id: int | None
    despegue: str | None = None
    ultima_operacion: str | None = None
    operaciones: int = 0
    ganancia: int = 0
    vendido: tuple[tuple[str, int], ...] = ()

    @property
    def fin(self) -> str | None:
        return self.despegue or self.ultima_operacion


@dataclass(frozen=True, slots=True)
class Libro:
    # La última parada con comercio de la que despegaste: el origen del próximo tramo.
    origen: _Parada | None = None
    actual: _Parada | None = None
    saltos: int = 0


def operacion(estado: Estado, evento: dict) -> Operacion | None:
    """La compra o venta del evento con la estación donde estás; None si no se entiende."""
    venta = evento.get("event") == "MarketSell"
    if not venta and evento.get("event") != "MarketBuy":
        return None
    simbolo = mercado.simbolo(evento.get("Type"))
    marca, market_id = evento.get("timestamp"), evento.get("MarketID")
    cantidad = _entero(evento.get("Count"))
    precio = _entero(evento.get("SellPrice" if venta else "BuyPrice"))
    total = _entero(evento.get("TotalSale" if venta else "TotalCost"))
    if simbolo is None or segundos(marca) is None or _entero(market_id) is None:
        return None
    if not cantidad or cantidad < 0 or precio is None or total is None:
        return None
    estacion = estado.estacion
    if estacion is not None and estacion.market_id != market_id:
        estacion = None
    return Operacion(
        marca=marca,
        market_id=market_id,
        estacion=estacion.nombre if estacion else None,
        sistema=estado.sistema if estacion else None,
        simbolo=simbolo,
        venta=venta,
        cantidad=cantidad,
        precio=precio,
        total=total,
        precio_medio_compra=_entero(evento.get("AvgPricePaid")) if venta else None,
    )


def anotar(libro: Libro, estado: Estado, evento: dict) -> tuple[Libro, Tramo | None]:
    """El libro tras el evento y el tramo que cierra, si cierra uno que cuenta.

    `estado` es el de después de aplicar el evento: trae la posición y la nave.
    """
    nombre = evento.get("event")
    if nombre in tiempos.INTERRUPCIONES or _no_es_tu_nave(evento):
        return _cerrar(libro, despegue=None, tras=Libro())
    if nombre == "FSDJump":
        return replace(libro, saltos=libro.saltos + 1), None
    # Tras cargar la partida en una estación no hay `Docked`: lo dice `Location`.
    if nombre == "Docked" or (nombre == "Location" and evento.get("Docked") is True):
        return replace(libro, actual=_parada(estado, evento)), None
    if nombre in ("MarketBuy", "MarketSell") and libro.actual is not None:
        return replace(libro, actual=_operar(libro.actual, operacion(estado, evento))), None
    if nombre == "Undocked" and libro.actual is not None:
        return _despegar(libro, evento.get("timestamp"))
    return libro, None


def _no_es_tu_nave(evento: dict) -> bool:
    """En un taxi de Apex o en la nave de otro, el viaje no es de tu ruta."""
    return evento.get("Taxi") is True or evento.get("Multicrew") is True


def _despegar(libro: Libro, marca: object) -> tuple[Libro, Tramo | None]:
    if not libro.actual.operaciones:
        # Una parada sin comercio no es origen ni destino: el tramo sigue abierto.
        return replace(libro, actual=None), None
    despegue = marca if segundos(marca) is not None else None
    return _cerrar(libro, despegue, tras=None)


def _cerrar(libro: Libro, despegue: str | None, tras: Libro | None) -> tuple[Libro, Tramo | None]:
    """Termina la parada actual; `tras` es el libro que queda si no es la de despegar."""
    destino = libro.actual
    if destino is None or not destino.operaciones:
        return tras or replace(libro, actual=None), None
    destino = replace(destino, despegue=despegue)
    tramo = _tramo(libro.origen, destino, libro.saltos)
    return tras or Libro(origen=destino), tramo


def _operar(parada: _Parada, hecha: Operacion | None) -> _Parada:
    if hecha is None:
        return parada
    parada = replace(parada, operaciones=parada.operaciones + 1, ultima_operacion=hecha.marca)
    if not hecha.venta:
        return parada
    return replace(
        parada,
        ganancia=parada.ganancia + (hecha.ganancia or 0),
        vendido=(*parada.vendido, (hecha.simbolo, hecha.cantidad)),
    )


def _parada(estado: Estado, evento: dict) -> _Parada:
    nave = estado.nave
    distancia = evento.get("DistFromStarLS")
    return _Parada(
        lugar=Lugar(
            market_id=_entero(evento.get("MarketID")),
            estacion=str(evento.get("StationName") or "?"),
            sistema=str(evento.get("StarSystem") or estado.sistema or "?"),
            posicion=estado.posicion,
        ),
        distancia_ls=float(distancia) if _es_distancia(distancia) else 0.0,
        planetaria=clasificacion.es_planetaria(evento.get("StationType")),
        rango=_rango(estado),
        ship_id=nave.ship_id if nave else None,
    )


def _tramo(origen: _Parada | None, destino: _Parada, saltos: int) -> Tramo | None:
    if origen is None or origen.despegue is None or destino.fin is None or destino.ganancia <= 0:
        return None
    duracion = segundos(destino.fin) - segundos(origen.despegue)
    if duracion <= 0:
        return None
    toneladas: dict[str, int] = {}
    for simbolo, cantidad in destino.vendido:
        toneladas[simbolo] = toneladas.get(simbolo, 0) + cantidad
    distancia = None
    if origen.lugar.posicion and destino.lugar.posicion:
        distancia = math.dist(origen.lugar.posicion, destino.lugar.posicion)
    return Tramo(
        ship_id=origen.ship_id,
        origen=origen.lugar,
        destino=destino.lugar,
        salida=origen.despegue,
        llegada=destino.fin,
        segundos=duracion,
        saltos=saltos,
        distancia_ly=distancia,
        rango=origen.rango,
        distancia_ls=destino.distancia_ls,
        planetaria=destino.planetaria,
        ganancia=destino.ganancia,
        toneladas=sum(toneladas.values()),
        mercancia=max(toneladas, key=toneladas.get) if toneladas else None,
    )


def _rango(estado: Estado) -> float | None:
    nave = estado.nave
    if nave is None or nave.datos is None:
        return None
    return modelo_nave.rango_de_comercio(nave.datos)


def segundos(marca: object) -> float | None:
    if not isinstance(marca, str):
        return None
    try:
        return datetime.fromisoformat(marca).timestamp()
    except ValueError:
        return None


def _es_distancia(valor: object) -> bool:
    return (
        isinstance(valor, (int, float))
        and not isinstance(valor, bool)
        and math.isfinite(valor)
        and valor >= 0
    )


def _entero(valor: object) -> int | None:
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None
