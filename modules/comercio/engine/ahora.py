"""Modos de la pantalla Ahora (sección 7.3): vender la carga y comprar desde aquí."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from modules.comercio import timing
from modules.comercio.engine import calculo
from modules.comercio.engine.calculo import Curva
from modules.comercio.engine.candidatos import Candidatos, Posicion, Precio
from modules.comercio.engine.perfil import Perfil
from modules.comercio.engine.tramo import Tramo, evaluar, mejores

DESTINOS_POR_MERCANCIA = 10


@dataclass(frozen=True, slots=True)
class Carga:
    mercancia: str
    cantidad: int
    precio_compra: int | None


@dataclass(frozen=True, slots=True)
class Venta:
    """Vender lo que ya llevas: lo comprado está pagado, así que manda el ingreso."""

    carga: Carga
    venta: Precio
    toneladas: int
    distancia_ly: float
    saltos: int
    segundos: float
    confianza: float

    @property
    def ingreso(self) -> int:
        return self.toneladas * self.venta.precio

    @property
    def ingreso_hora(self) -> float:
        return calculo.por_hora(self.ingreso, self.segundos)

    @property
    def ganancia(self) -> int | None:
        if self.carga.precio_compra is None:
            return None
        return self.toneladas * (self.venta.precio - self.carga.precio_compra)

    @property
    def puntuacion(self) -> float:
        return self.ingreso_hora * self.confianza


def _vender(carga: Carga, venta: Precio, origen: Posicion, perfil: Perfil, curva: Curva) -> Venta:
    distancia = math.dist(origen, venta.estacion.posicion)
    saltos = calculo.saltos(distancia, perfil.rango)
    destino = venta.estacion
    return Venta(
        carga=carga,
        venta=venta,
        toneladas=min(carga.cantidad, venta.cantidad),
        distancia_ly=distancia,
        saltos=saltos,
        segundos=timing.tramo(saltos, destino.distancia_ls, destino.planetaria),
        confianza=calculo.confianza(venta.horas, curva),
    )


def vender_carga(
    candidatos: Candidatos, carga: list[Carga], origen: Posicion, perfil: Perfil, curva: Curva
) -> dict[str, list[Venta]]:
    """Los mejores compradores de cada mercancía de la bodega; vacía si nadie la compra."""
    return {
        articulo.mercancia: heapq.nlargest(
            DESTINOS_POR_MERCANCIA,
            (
                _vender(articulo, venta, origen, perfil, curva)
                for venta in candidatos.demandas.get(articulo.mercancia, ())
            ),
            key=lambda v: v.puntuacion,
        )
        for articulo in carga
    }


def desde_aqui(
    candidatos: Candidatos, ofertas: list[Precio], perfil: Perfil, curva: Curva
) -> list[Tramo]:
    """Lo que vende tu estación contra todos los compradores del radio, no solo los K mejores."""
    tramos = (
        evaluar(oferta, venta, perfil, curva)
        for oferta in ofertas
        for venta in candidatos.demandas.get(oferta.mercancia, ())
    )
    return mejores((t for t in tramos if t is not None), perfil.orden)
