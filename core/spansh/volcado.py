"""Una línea del volcado `galaxy_stations.json.gz` convertida en datos (sección 4.3).

Es un arreglo JSON con un sistema por línea. Casi todos quedan fuera de la
esfera, así que primero se lee la cabecera con una expresión regular y solo los
que caen dentro pasan por `json.loads`.

Spansh no es de fiar a ciegas: se valida todo antes de que llegue a la base. Un
sistema dudoso se descarta entero (`Descartado`); una estación dudosa se omite y
se cuenta, para que el importador note un cambio de formato.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core import estacion as clasificacion
from core import validacion
from core.db.mercado import FUENTE_SPANSH, Estacion, Sistema
from core.esfera import Esfera
from core.journal.mercado import Articulo
from core.validacion import MOTIVO_MAL_FORMADO, Descartado

TAMANO_MAXIMO_DE_LINEA = 32 * 1024 * 1024
MERCANCIAS_MAXIMAS = 500
# Holgura para un reloj atrasado: con una mayor, mercados recientes se tomarían por futuros.
ADELANTO_MAXIMO = timedelta(days=1)
# Spansh no publica los niveles de stock y demanda.
NIVEL_DESCONOCIDO = -1

_NUMERO = rb"(-?[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)"
_CABECERA = re.compile(
    rb'\{"id64":[0-9]+,"name":"(?:[^"\\]|\\.)*","coords":\{"x":'
    + _NUMERO
    + rb',"y":'
    + _NUMERO
    + rb',"z":'
    + _NUMERO
    + rb"\}"
)
_LARGO_DE_CABECERA = 1024


@dataclass(frozen=True)
class EstacionDeVolcado:
    estacion: Estacion
    observado: str | None
    # None: Spansh no trae mercado, y entonces no se toca el que hubiera guardado.
    articulos: tuple[Articulo, ...] | None


@dataclass(frozen=True)
class SistemaDeVolcado:
    sistema: Sistema
    observado: str
    estaciones: tuple[EstacionDeVolcado, ...]
    estaciones_descartadas: int


def interpretar(
    linea: bytes, esfera: Esfera, ahora: datetime | None = None
) -> SistemaDeVolcado | None:
    """None si la línea es de estructura (`[`, `]`) o el sistema cae fuera de la esfera."""
    if len(linea) > TAMANO_MAXIMO_DE_LINEA:
        raise Descartado(MOTIVO_MAL_FORMADO)
    contenido = linea.strip().rstrip(b",")
    if contenido in (b"", b"[", b"]") or _fuera_de_la_esfera(contenido, esfera):
        return None
    sistema = _json(contenido)
    posicion = _posicion_de(sistema)
    if not esfera.contiene(posicion):
        return None
    estaciones, descartadas = _estaciones(sistema, ahora or datetime.now(UTC))
    return SistemaDeVolcado(
        sistema=Sistema(
            system_address=validacion.entero(sistema.get("id64"), 1, 2**63 - 1),
            nombre=validacion.texto(sistema.get("name")),
            posicion=posicion,
            distancia_centro=esfera.distancia(posicion),
            fuente=FUENTE_SPANSH,
        ),
        observado=_marca(sistema.get("date")),
        estaciones=estaciones,
        estaciones_descartadas=descartadas,
    )


def serializar(sistema: SistemaDeVolcado) -> bytes:
    """Una línea compacta con lo que se guardará; el original trae cientos de KB de cuerpos."""
    s = sistema.sistema
    estaciones = [
        [
            e.estacion.market_id,
            e.estacion.nombre,
            e.estacion.categoria,
            e.estacion.plataforma,
            e.estacion.distancia_ls,
            e.estacion.planetaria,
            e.observado,
            None if e.articulos is None else [_a_lista(a) for a in e.articulos],
        ]
        for e in sistema.estaciones
    ]
    datos = [
        [s.system_address, s.nombre, list(s.posicion or ()), s.distancia_centro, s.fuente],
        sistema.observado,
        estaciones,
        sistema.estaciones_descartadas,
    ]
    return json.dumps(datos, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def deserializar(linea: bytes) -> SistemaDeVolcado:
    """Inversa de `serializar`. Lo leyó LUNA misma hace un momento, así que no se revalida."""
    (direccion, nombre, posicion, distancia, fuente), observado, estaciones, descartadas = (
        json.loads(linea)
    )
    return SistemaDeVolcado(
        sistema=Sistema(direccion, nombre, tuple(posicion) or None, distancia, fuente),
        observado=observado,
        estaciones=tuple(_estacion_guardada(e) for e in estaciones),
        estaciones_descartadas=descartadas,
    )


def _a_lista(a: Articulo) -> list:
    return [
        a.simbolo,
        a.precio_compra,
        a.precio_venta,
        a.stock,
        a.demanda,
        a.nivel_stock,
        a.nivel_demanda,
    ]


def _estacion_guardada(datos: list) -> EstacionDeVolcado:
    market_id, nombre, categoria, plataforma, ls, planetaria, observado, articulos = datos
    return EstacionDeVolcado(
        Estacion(market_id, nombre, categoria, plataforma, ls, planetaria),
        observado,
        None if articulos is None else tuple(_articulo_guardado(a) for a in articulos),
    )


def _articulo_guardado(datos: list) -> Articulo:
    simbolo, compra, venta, stock, demanda, nivel_stock, nivel_demanda = datos
    return Articulo(
        simbolo, None, None, compra, venta, stock, demanda, nivel_stock, nivel_demanda, False
    )


def _fuera_de_la_esfera(contenido: bytes, esfera: Esfera) -> bool:
    cabecera = _CABECERA.match(contenido[:_LARGO_DE_CABECERA])
    if cabecera is None:
        return False
    try:
        x, y, z = (float(eje) for eje in cabecera.groups())
    except ValueError:
        return False
    return not esfera.contiene((x, y, z))


def _json(contenido: bytes) -> dict:
    try:
        sistema = json.loads(contenido)
    except (ValueError, RecursionError) as error:
        raise Descartado(MOTIVO_MAL_FORMADO) from error
    if not isinstance(sistema, dict):
        raise Descartado(MOTIVO_MAL_FORMADO)
    return sistema


def _posicion_de(sistema: dict) -> tuple[float, float, float]:
    coordenadas = sistema.get("coords")
    if not isinstance(coordenadas, dict):
        raise Descartado(MOTIVO_MAL_FORMADO)
    return validacion.posicion([coordenadas.get(eje) for eje in ("x", "y", "z")])


def _marca(valor: object) -> str:
    fecha = validacion.fecha(valor)
    if fecha is None:
        raise Descartado(MOTIVO_MAL_FORMADO)
    return fecha.strftime("%Y-%m-%dT%H:%M:%SZ")


def _lista(valor: object) -> list:
    return valor if isinstance(valor, list) else []


def _estaciones(sistema: dict, ahora: datetime) -> tuple[tuple[EstacionDeVolcado, ...], int]:
    """Las del sistema y las de cada cuerpo, donde están las planetarias."""
    brutas = [(b, False) for b in _lista(sistema.get("stations"))]
    for cuerpo in _lista(sistema.get("bodies")):
        if isinstance(cuerpo, dict):
            brutas.extend((b, True) for b in _lista(cuerpo.get("stations")))
    vistas: dict[int, EstacionDeVolcado] = {}
    descartadas = 0
    for bruta, en_cuerpo in brutas:
        try:
            estacion = _estacion(bruta, en_cuerpo, ahora)
        except Descartado:
            descartadas += 1
            continue
        vistas.setdefault(estacion.estacion.market_id, estacion)
    return tuple(vistas.values()), descartadas


def _estacion(bruta: object, en_cuerpo: bool, ahora: datetime) -> EstacionDeVolcado:
    if not isinstance(bruta, dict):
        raise Descartado(MOTIVO_MAL_FORMADO)
    tipo = bruta.get("type") if isinstance(bruta.get("type"), str) else None
    nombre = validacion.texto(bruta.get("name"))
    estacion = Estacion(
        market_id=validacion.entero(bruta.get("id"), 1),
        nombre=nombre,
        categoria=clasificacion.categoria_de_spansh(tipo, nombre, en_cuerpo),
        plataforma=clasificacion.plataforma_maxima(_plataformas(bruta.get("landingPads"))),
        distancia_ls=validacion.distancia_ls(bruta.get("distanceToArrival")),
        planetaria=clasificacion.es_planetaria_de_spansh(tipo, en_cuerpo),
    )
    mercado = bruta.get("market")
    if not isinstance(mercado, dict):
        return EstacionDeVolcado(estacion, None, None)
    observado = _marca(mercado.get("updateTime"))
    # Una marca del futuro ganaría para siempre la precedencia (regla 1 de la 5.4).
    if validacion.fecha(observado) > ahora + ADELANTO_MAXIMO:
        raise Descartado(MOTIVO_MAL_FORMADO)
    return EstacionDeVolcado(estacion, observado, _articulos(mercado.get("commodities")))


def _plataformas(valor: object) -> dict | None:
    """Spansh las nombra en minúscula; el clasificador espera las del journal."""
    if not isinstance(valor, dict):
        return None
    return {str(nombre).capitalize(): cantidad for nombre, cantidad in valor.items()}


def _articulos(brutos: object) -> tuple[Articulo, ...]:
    if not isinstance(brutos, list) or len(brutos) > MERCANCIAS_MAXIMAS:
        raise Descartado(MOTIVO_MAL_FORMADO)
    articulos = tuple(_articulo(b) for b in brutos)
    if len({a.simbolo for a in articulos}) != len(articulos):
        raise Descartado(MOTIVO_MAL_FORMADO)
    return articulos


def _articulo(bruto: object) -> Articulo:
    if not isinstance(bruto, dict):
        raise Descartado(MOTIVO_MAL_FORMADO)
    oferta = validacion.entero(bruto.get("supply"))
    demanda = validacion.entero(bruto.get("demand"))
    return Articulo(
        # En minúsculas es la misma clave que usan el journal y EDDN.
        simbolo=validacion.texto(bruto.get("symbol")).lower(),
        nombre=None,
        categoria=None,
        precio_compra=validacion.entero(bruto.get("buyPrice")),
        precio_venta=validacion.entero(bruto.get("sellPrice")),
        stock=oferta,
        # Con oferta la demanda es siempre 1: el mismo residuo que trae Market.json.
        demanda=0 if oferta > 0 else demanda,
        nivel_stock=NIVEL_DESCONOCIDO,
        nivel_demanda=NIVEL_DESCONOCIDO,
        rara=False,
    )
