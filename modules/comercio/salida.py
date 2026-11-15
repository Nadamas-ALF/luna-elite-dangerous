"""Resultados del motor como datos simples para la interfaz (columnas de la 7.2).

Solo números, códigos y nombres propios; las frases las pone la interfaz con
`ui/i18n/es.json`. El nombre de la mercancía sale de `commodities`: el español si
se conoce, si no el inglés, y como último recurso el símbolo.
"""

from __future__ import annotations

import sqlite3

from modules.comercio import timing
from modules.comercio.engine.ahora import Venta
from modules.comercio.engine.candidatos import Precio
from modules.comercio.engine.rutas import Bucle
from modules.comercio.engine.tramo import Tramo


def nombres_de_mercancias(conexion: sqlite3.Connection) -> dict[str, str]:
    return {
        simbolo: nombre
        for simbolo, nombre in conexion.execute(
            "SELECT simbolo, COALESCE(nombre_es, nombre_en) FROM commodities"
        )
        if nombre
    }


def mercancia(simbolo: str, nombres: dict[str, str]) -> dict:
    return {"simbolo": simbolo, "nombre": nombres.get(simbolo, simbolo)}


def lado(precio: Precio) -> dict:
    estacion = precio.estacion
    return {
        "market_id": estacion.market_id,
        "estacion": estacion.nombre,
        "sistema": estacion.sistema,
        "distancia_ls": estacion.distancia_ls,
        "planetaria": estacion.planetaria,
        "distancia_origen": estacion.distancia_origen,
        "precio": precio.precio,
        "cantidad": precio.cantidad,
        "origen": precio.origen,
        "observado": precio.observado,
        "horas": precio.horas,
    }


def _tiempo(saltos: int, destino: Precio) -> dict:
    return {
        **timing.desglose(saltos, destino.estacion.distancia_ls, destino.estacion.planetaria),
        "fuente": timing.FUENTE_POR_DEFECTO,
    }


def tramo(resultado: Tramo, nombres: dict[str, str], horas_sesion: float) -> dict:
    return {
        "mercancia": mercancia(resultado.compra.mercancia, nombres),
        "compra": lado(resultado.compra),
        "venta": lado(resultado.venta),
        "ganancia_tonelada": resultado.ganancia_tonelada,
        "toneladas": resultado.toneladas,
        "ganancia_viaje": resultado.ganancia_viaje,
        "saltos": resultado.saltos,
        "distancia_ly": resultado.distancia_ly,
        "segundos": resultado.segundos,
        "tiempo": _tiempo(resultado.saltos, resultado.venta),
        "ganancia_hora": resultado.ganancia_hora,
        "ganancia_sesion": resultado.ganancia_hora * horas_sesion,
        "confianza": resultado.confianza,
        "puntuacion": resultado.puntuacion,
    }


def bucle(resultado: Bucle, nombres: dict[str, str], horas_sesion: float) -> dict:
    return {
        "ida": tramo(resultado.ida, nombres, horas_sesion),
        "vuelta": tramo(resultado.vuelta, nombres, horas_sesion),
        "ganancia_tonelada": resultado.ganancia_tonelada,
        "ganancia_viaje": resultado.ganancia_viaje,
        "distancia_ly": resultado.distancia_ly,
        "segundos": resultado.segundos,
        "ganancia_hora": resultado.ganancia_hora,
        "ganancia_sesion": resultado.ganancia_hora * horas_sesion,
        "confianza": resultado.confianza,
        "puntuacion": resultado.puntuacion,
    }


def venta(resultado: Venta) -> dict:
    return {
        "venta": lado(resultado.venta),
        "toneladas": resultado.toneladas,
        "distancia_ly": resultado.distancia_ly,
        "saltos": resultado.saltos,
        "segundos": resultado.segundos,
        "tiempo": _tiempo(resultado.saltos, resultado.venta),
        "ingreso": resultado.ingreso,
        "ingreso_hora": resultado.ingreso_hora,
        "ganancia": resultado.ganancia,
        "confianza": resultado.confianza,
        "puntuacion": resultado.puntuacion,
    }
