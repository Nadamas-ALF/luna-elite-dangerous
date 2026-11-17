"""Resultados del motor como datos simples para la interfaz (columnas de la 7.2).

Solo números, códigos y nombres propios; las frases las pone la interfaz con
`ui/i18n/es.json`. El nombre de la mercancía sale de `commodities`: el español si
se conoce, si no el inglés, y como último recurso el símbolo.
"""

from __future__ import annotations

import sqlite3

from modules.comercio.engine.ahora import Venta
from modules.comercio.engine.cadenas import Cadena
from modules.comercio.engine.candidatos import Precio
from modules.comercio.engine.rutas import Bucle
from modules.comercio.engine.tramo import Tramo
from modules.comercio.timing import Tiempos


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


def _tiempo(saltos: int, destino: Precio, tiempos: Tiempos) -> list[dict]:
    """Cada parte con sus segundos y de dónde sale (8.4): por defecto, comandante o nave."""
    estacion = destino.estacion
    return [
        {"parte": parte, "segundos": segundos, "fuente": valor.fuente, "muestras": valor.muestras}
        for parte, (segundos, valor) in tiempos.partes(
            saltos, estacion.distancia_ls, estacion.planetaria
        ).items()
    ]


def tramo(resultado: Tramo, nombres: dict[str, str], horas_sesion: float, tiempos: Tiempos) -> dict:
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
        "tiempo": _tiempo(resultado.saltos, resultado.venta, tiempos),
        "ganancia_hora": resultado.ganancia_hora,
        "ganancia_sesion": resultado.ganancia_hora * horas_sesion,
        "confianza": resultado.confianza,
        "puntuacion": resultado.puntuacion,
    }


def bucle(resultado: Bucle, nombres: dict[str, str], horas_sesion: float, tiempos: Tiempos) -> dict:
    return {
        "ida": tramo(resultado.ida, nombres, horas_sesion, tiempos),
        "vuelta": tramo(resultado.vuelta, nombres, horas_sesion, tiempos),
        "ganancia_tonelada": resultado.ganancia_tonelada,
        "ganancia_viaje": resultado.ganancia_viaje,
        "distancia_ly": resultado.distancia_ly,
        "segundos": resultado.segundos,
        "ganancia_hora": resultado.ganancia_hora,
        "ganancia_sesion": resultado.ganancia_hora * horas_sesion,
        "confianza": resultado.confianza,
        "puntuacion": resultado.puntuacion,
    }


def cadena(
    resultado: Cadena, nombres: dict[str, str], horas_sesion: float, tiempos: Tiempos
) -> dict:
    return {
        "cerrada": resultado.cerrada,
        "tramos": [tramo(t, nombres, horas_sesion, tiempos) for t in resultado.tramos],
        "paradas": len(resultado.estaciones),
        "ganancia_tonelada": resultado.ganancia_tonelada,
        "ganancia_viaje": resultado.ganancia_viaje,
        "distancia_ly": resultado.distancia_ly,
        "saltos": resultado.saltos,
        "segundos": resultado.segundos,
        "ganancia_hora": resultado.ganancia_hora,
        "ganancia_sesion": resultado.ganancia_hora * horas_sesion,
        "confianza": resultado.confianza,
        "puntuacion": resultado.puntuacion,
    }


def venta(resultado: Venta, tiempos: Tiempos) -> dict:
    return {
        "venta": lado(resultado.venta),
        "toneladas": resultado.toneladas,
        "distancia_ly": resultado.distancia_ly,
        "saltos": resultado.saltos,
        "segundos": resultado.segundos,
        "tiempo": _tiempo(resultado.saltos, resultado.venta, tiempos),
        "ingreso": resultado.ingreso,
        "ingreso_hora": resultado.ingreso_hora,
        "ganancia": resultado.ganancia,
        "confianza": resultado.confianza,
        "puntuacion": resultado.puntuacion,
    }
