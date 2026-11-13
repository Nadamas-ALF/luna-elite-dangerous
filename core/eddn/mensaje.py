"""Un mensaje de EDDN convertido en datos tipados (sección 4.2).

EDDN es un canal público: cualquiera puede enviar lo que quiera. Aquí se
comprueba todo antes de que algo llegue a la base: tamaño tras descomprimir,
tipos, rangos y marcas de tiempo. Un mensaje dudoso se descarta entero, porque
un mercado a medias es peor que ninguno.

Solo se interpretan `commodity/3` y los `journal/1` que traen coordenadas.
"""

from __future__ import annotations

import json
import math
import re
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core import estacion as clasificacion
from core.db.mercado import Estacion
from core.journal.mercado import Articulo

ESQUEMA_MERCADO = "https://eddn.edcd.io/schemas/commodity/3"
ESQUEMA_JOURNAL = "https://eddn.edcd.io/schemas/journal/1"

# Un commodity/3 de 400 mercancías ronda los 60 KB descomprimido.
TAMANO_MAXIMO = 1_048_576
MERCANCIAS_MAXIMAS = 500
LARGO_MAXIMO = 100
VALOR_MAXIMO = 2**53
COORDENADA_MAXIMA = 200_000.0
# Margen para relojes desajustados; más allá, la marca no es creíble.
ADELANTO_MAXIMO = timedelta(seconds=60)
ANTIGUEDAD_MAXIMA = timedelta(days=30)

MOTIVO_PRUEBA = "prueba"
MOTIVO_LEGACY = "legacy"
MOTIVO_MAL_FORMADO = "mal_formado"
MOTIVO_FECHA = "fecha"
MOTIVO_ESQUEMA = "esquema"

_MARCA = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)")


class Descartado(Exception):  # noqa: N818 - no es un error: es el desenlace normal de un mensaje ajeno
    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


@dataclass(frozen=True)
class Visita:
    """Un sistema con coordenadas y, si fue un `Docked`, la estación."""

    nombre: str
    system_address: int
    posicion: tuple[float, float, float]
    observado: str
    estacion: Estacion | None


@dataclass(frozen=True)
class MercadoDeRed:
    """Un mercado entero. No trae coordenadas: el sistema se busca por nombre."""

    sistema: str
    estacion: Estacion
    observado: str
    articulos: tuple[Articulo, ...]


def interpretar(crudo: bytes, ahora: datetime | None = None) -> Visita | MercadoDeRed | None:
    """None si el mensaje es válido pero no sirve; `Descartado` si hay que tirarlo."""
    mensaje = _json(_descomprimir(crudo))
    esquema = mensaje.get("$schemaRef")
    if not isinstance(esquema, str):
        raise Descartado(MOTIVO_MAL_FORMADO)
    if esquema.endswith("/test"):
        raise Descartado(MOTIVO_PRUEBA)
    if esquema not in (ESQUEMA_MERCADO, ESQUEMA_JOURNAL):
        raise Descartado(MOTIVO_ESQUEMA)
    cabecera, cuerpo = mensaje.get("header"), mensaje.get("message")
    if not isinstance(cabecera, dict) or not isinstance(cuerpo, dict):
        raise Descartado(MOTIVO_MAL_FORMADO)
    _exigir_live(cabecera)
    if esquema == ESQUEMA_MERCADO:
        return _mercado(
            cuerpo, _marca_de(cuerpo.get("timestamp"), cabecera, ahora, ANTIGUEDAD_MAXIMA)
        )
    # EDMC reenvía journals de hace semanas, y las coordenadas de un sistema no caducan.
    return _visita(cuerpo, _marca_de(cuerpo.get("timestamp"), cabecera, ahora, None))


def _descomprimir(crudo: bytes) -> bytes:
    """Con tope: un zlib pequeño puede expandirse a gigabytes."""
    descompresor = zlib.decompressobj()
    try:
        datos = descompresor.decompress(crudo, TAMANO_MAXIMO + 1)
    except zlib.error as error:
        raise Descartado(MOTIVO_MAL_FORMADO) from error
    if len(datos) > TAMANO_MAXIMO:
        raise Descartado(MOTIVO_MAL_FORMADO)
    return datos


def _json(datos: bytes) -> dict:
    try:
        mensaje = json.loads(datos)
    except (ValueError, RecursionError) as error:
        raise Descartado(MOTIVO_MAL_FORMADO) from error
    if not isinstance(mensaje, dict):
        raise Descartado(MOTIVO_MAL_FORMADO)
    return mensaje


def _exigir_live(cabecera: dict) -> None:
    """Sin versión se acepta: hay herramientas que no la envían. Legacy, no."""
    version = cabecera.get("gameversion")
    if not isinstance(version, str):
        return
    if "legacy" in version.lower() or re.match(r"[0-3]\.", version):
        raise Descartado(MOTIVO_LEGACY)


def _fecha(valor: object) -> datetime | None:
    if not isinstance(valor, str) or not _MARCA.fullmatch(valor):
        return None
    try:
        fecha = datetime.fromisoformat(valor)
    except ValueError:
        return None
    return fecha.astimezone(UTC) if fecha.tzinfo else None


def _marca_de(
    valor: object, cabecera: dict, ahora: datetime | None, antiguedad: timedelta | None
) -> str:
    """Marca normalizada. Se compara con la hora de la pasarela, que no la pone el emisor."""
    fecha = _fecha(valor)
    if fecha is None:
        raise Descartado(MOTIVO_MAL_FORMADO)
    referencia = _fecha(cabecera.get("gatewayTimestamp")) or ahora or datetime.now(UTC)
    demasiado_vieja = antiguedad is not None and referencia - fecha > antiguedad
    if fecha > referencia + ADELANTO_MAXIMO or demasiado_vieja:
        raise Descartado(MOTIVO_FECHA)
    return fecha.strftime("%Y-%m-%dT%H:%M:%SZ")


def _texto(valor: object) -> str:
    if not isinstance(valor, str):
        raise Descartado(MOTIVO_MAL_FORMADO)
    limpio = valor.strip()
    if not limpio or len(limpio) > LARGO_MAXIMO or not limpio.isprintable():
        raise Descartado(MOTIVO_MAL_FORMADO)
    return limpio


def _entero(valor: object, minimo: int = 0, maximo: int = VALOR_MAXIMO) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int) or not minimo <= valor <= maximo:
        raise Descartado(MOTIVO_MAL_FORMADO)
    return valor


def _posicion(valor: object) -> tuple[float, float, float]:
    if not isinstance(valor, list) or len(valor) != 3:
        raise Descartado(MOTIVO_MAL_FORMADO)
    for eje in valor:
        numero_valido = isinstance(eje, (int, float)) and not isinstance(eje, bool)
        if not numero_valido or not math.isfinite(eje) or abs(eje) > COORDENADA_MAXIMA:
            raise Descartado(MOTIVO_MAL_FORMADO)
    return float(valor[0]), float(valor[1]), float(valor[2])


def _nivel(valor: object) -> int:
    """Los Fleet Carrier mandan una cadena vacía en el nivel que no tienen."""
    return 0 if valor == "" else _entero(valor, 0, 3)


def _articulo(bruto: object) -> Articulo:
    if not isinstance(bruto, dict):
        raise Descartado(MOTIVO_MAL_FORMADO)
    nivel_stock = _nivel(bruto.get("stockBracket"))
    nivel_demanda = _nivel(bruto.get("demandBracket"))
    stock = _entero(bruto.get("stock"))
    demanda = _entero(bruto.get("demand"))
    return Articulo(
        simbolo=_texto(bruto.get("name")).lower(),
        nombre=None,
        categoria=None,
        precio_compra=_entero(bruto.get("buyPrice")),
        precio_venta=_entero(bruto.get("sellPrice")),
        # Con nivel 0 la cantidad es un residuo del juego; igual que en Market.json.
        stock=stock if nivel_stock > 0 else 0,
        demanda=demanda if nivel_demanda > 0 else 0,
        nivel_stock=nivel_stock,
        nivel_demanda=nivel_demanda,
        rara=False,
    )


def _articulos(brutos: object) -> tuple[Articulo, ...]:
    if not isinstance(brutos, list) or len(brutos) > MERCANCIAS_MAXIMAS:
        raise Descartado(MOTIVO_MAL_FORMADO)
    articulos = tuple(_articulo(b) for b in brutos)
    if len({a.simbolo for a in articulos}) != len(articulos):
        raise Descartado(MOTIVO_MAL_FORMADO)
    return articulos


def _es_carrier(economias: object) -> bool:
    if not isinstance(economias, list):
        return False
    return any(isinstance(e, dict) and e.get("name") == "Carrier" for e in economias)


def _mercado(cuerpo: dict, marca: str) -> MercadoDeRed:
    # commodity/3 no dice qué tipo de estación es; se delatan los Fleet Carrier y la colonización.
    categoria = clasificacion.FLEET_CARRIER if _es_carrier(cuerpo.get("economies")) else None
    nombre = _texto(cuerpo.get("stationName"))
    estacion = Estacion(
        market_id=_entero(cuerpo.get("marketId"), 1),
        nombre=nombre,
        categoria=categoria or clasificacion.categoria(None, nombre),
        plataforma=None,
        distancia_ls=None,
        planetaria=False,
    )
    return MercadoDeRed(
        sistema=_texto(cuerpo.get("systemName")),
        estacion=estacion,
        observado=marca,
        articulos=_articulos(cuerpo.get("commodities")),
    )


def _distancia_ls(valor: object) -> float | None:
    numero_valido = isinstance(valor, (int, float)) and not isinstance(valor, bool)
    return float(valor) if numero_valido and 0 <= valor <= 1e9 else None


def _estacion_de_docked(cuerpo: dict) -> Estacion | None:
    """Un `Docked` sin estación utilizable sigue sirviendo como visita al sistema."""
    try:
        tipo = _texto(cuerpo.get("StationType"))
        nombre = _texto(cuerpo.get("StationName"))
        return Estacion(
            market_id=_entero(cuerpo.get("MarketID"), 1),
            nombre=nombre,
            categoria=clasificacion.categoria(tipo, nombre),
            plataforma=clasificacion.plataforma_maxima(cuerpo.get("LandingPads")),
            distancia_ls=_distancia_ls(cuerpo.get("DistFromStarLS")),
            planetaria=clasificacion.es_planetaria(tipo),
        )
    except Descartado:
        return None


def _visita(cuerpo: dict, marca: str) -> Visita | None:
    """La mayoría de los eventos del journal no traen `StarPos`: no sirven y no son un error."""
    if "StarPos" not in cuerpo:
        return None
    estacion = _estacion_de_docked(cuerpo) if cuerpo.get("event") == "Docked" else None
    return Visita(
        nombre=_texto(cuerpo.get("StarSystem")),
        system_address=_entero(cuerpo.get("SystemAddress"), 1, 2**63 - 1),
        posicion=_posicion(cuerpo.get("StarPos")),
        observado=marca,
        estacion=estacion,
    )
