"""Market.json: los precios de la estación cuyo mercado acaba de abrir el jugador.

El juego reescribe el archivo entero al abrir el mercado. Aquí solo se valida y
se convierte en datos; qué se guarda y dónde es cosa de `core/db/mercado.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.journal import archivos

_PREFIJO = "$"
_SUFIJO = "_name;"


@dataclass(frozen=True)
class Articulo:
    simbolo: str
    nombre: str | None
    categoria: str | None
    precio_compra: int
    precio_venta: int
    stock: int
    demanda: int
    nivel_stock: int
    nivel_demanda: int
    rara: bool

    @property
    def se_comercia(self) -> bool:
        """Market.json lista todas las mercancías, también las que la estación no mueve."""
        return self.stock > 0 or self.demanda > 0


@dataclass(frozen=True)
class Mercado:
    market_id: int
    estacion: str
    observado: str
    articulos: tuple[Articulo, ...]


def codigo_de_idioma(idioma: str | None) -> str | None:
    """`Spanish/ES` -> `es`. Otros idiomas no se aprovechan: nombre_en y nombre_es son dos."""
    nombre = (idioma or "").split("/")[0].strip().lower()
    return {"spanish": "es", "english": "en"}.get(nombre)


def simbolo(nombre_interno: object) -> str | None:
    """`$platinum_name;` -> `platinum`, la misma clave que usa EDDN."""
    if not isinstance(nombre_interno, str):
        return None
    limpio = nombre_interno.strip().lower()
    if limpio.startswith(_PREFIJO) and limpio.endswith(_SUFIJO):
        limpio = limpio[len(_PREFIJO) : -len(_SUFIJO)]
    return limpio or None


def _entero(valor: object) -> int | None:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    return int(valor)


def _texto(valor: object) -> str | None:
    return valor.strip() or None if isinstance(valor, str) else None


def _categoria(valor: object) -> str | None:
    """`$MARKET_category_metals;` -> `metals`."""
    texto = _texto(valor)
    if texto is None:
        return None
    return texto.lower().removeprefix("$market_category_").removesuffix(";") or None


def _articulo(bruto: object) -> Articulo | None:
    if not isinstance(bruto, dict):
        return None
    clave = simbolo(bruto.get("Name"))
    numeros = [
        _entero(bruto.get(campo))
        for campo in ("BuyPrice", "SellPrice", "Stock", "Demand", "StockBracket", "DemandBracket")
    ]
    if clave is None or None in numeros:
        return None
    compra, venta, stock, demanda, nivel_stock, nivel_demanda = numeros
    # Con nivel 0 el juego deja una cantidad residual (Demand 1 en lo que la
    # estación produce y no compra); EDDN la da por cero y el motor también.
    stock = stock if nivel_stock > 0 else 0
    demanda = demanda if nivel_demanda > 0 else 0
    return Articulo(
        simbolo=clave,
        nombre=_texto(bruto.get("Name_Localised")),
        categoria=_categoria(bruto.get("Category")),
        precio_compra=compra,
        precio_venta=venta,
        stock=stock,
        demanda=demanda,
        nivel_stock=nivel_stock,
        nivel_demanda=nivel_demanda,
        rara=bruto.get("Rare") is True,
    )


def convertir(contenido: dict) -> Mercado | None:
    """None si el archivo no es un mercado entero; una línea mala no lo invalida."""
    market_id = _entero(contenido.get("MarketID"))
    observado = _texto(contenido.get("timestamp"))
    brutos = contenido.get("Items")
    if market_id is None or observado is None or not isinstance(brutos, list):
        return None
    articulos = tuple(a for a in map(_articulo, brutos) if a is not None)
    return Mercado(market_id, _texto(contenido.get("StationName")) or "", observado, articulos)


def leer(carpeta: Path) -> Mercado | None:
    contenido = archivos.leer(carpeta, archivos.MERCADO)
    return None if contenido is None else convertir(contenido)
