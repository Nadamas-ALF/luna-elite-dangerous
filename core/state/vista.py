"""Lo que la pantalla Estado recibe: el estado del núcleo como datos simples.

Aquí no hay frases. Cuando falta un valor se devuelve un código de motivo y la
interfaz lo traduce con `ui/i18n/es.json`: ningún valor llega como un guion
mudo (docs/decisiones.md, «Distribución de Estado»).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core import catalogo
from core import nave as modelo_nave
from core.config import ajustes
from core.state.estado import Estado, NaveActual

MOTIVO_SIN_JOURNAL = "sin_journal"
MOTIVO_SIN_COMANDANTE = "sin_comandante"
MOTIVO_SIN_SALDO = "sin_saldo"
MOTIVO_SIN_LOADOUT = "sin_loadout"
MOTIVO_SIN_UBICACION = "sin_ubicacion"
MOTIVO_SIN_COMBUSTIBLE = "sin_combustible"
MOTIVO_SIN_LECTURA = "sin_lectura"
MOTIVO_NAVE_NO_CONOCIDA = "nave_no_conocida"

JOURNAL_LEYENDO = "leyendo"
JOURNAL_SIN_CARPETA = "sin_carpeta"
JOURNAL_SIN_ARCHIVOS = "sin_archivos"

AVISO_SIN_BASE = "base_no_disponible"


@dataclass(frozen=True)
class Contexto:
    """Lo que Estado muestra y no sale del journal."""

    journal: str
    motivo_datos: str | None
    avisos_datos: tuple[str, ...]
    base_disponible: bool
    eddn: str = "desactivado"


def _causa(sin_journal: bool, motivo: str) -> str:
    """Sin journal, la causa de cualquier dato ausente es esa, no el evento concreto."""
    return MOTIVO_SIN_JOURNAL if sin_journal else motivo


def _nombre_de_nave(actual: NaveActual, estado: Estado) -> str:
    """El que escribe el juego (en su idioma), el de la tabla o el símbolo."""
    if estado.nave_localizada and estado.nave_localizada[0] == actual.ship_id:
        return estado.nave_localizada[1]
    ficha = catalogo.nave(actual.simbolo)
    return ficha.nombre if ficha else actual.simbolo


def _reserva(actual: NaveActual, estado: Estado) -> float:
    """Depósito de reserva, que siempre va lleno y que el juego suma al rango."""
    if actual.datos is None or estado.combustible_capacidad is None:
        return 0.0
    return max(actual.datos.capacidad_combustible - estado.combustible_capacidad, 0.0)


def _rangos(actual: NaveActual, estado: Estado) -> tuple[float | None, float | None, str | None]:
    """Sin carga, con la bodega llena y el motivo si no se pueden calcular."""
    if actual.datos is None:
        return None, None, actual.error
    vacio = modelo_nave.rango_maximo(actual.datos)
    if estado.combustible is None:
        return vacio, modelo_nave.rango_maximo(actual.datos, actual.capacidad_carga), None
    combustible = estado.combustible + _reserva(actual, estado)
    cargado = modelo_nave.rango(actual.datos, actual.capacidad_carga, combustible)
    return vacio, cargado, None


def _nave(estado: Estado, sin_journal: bool) -> dict:
    actual = estado.nave
    if actual is None:
        return {"presente": False, "motivo": _causa(sin_journal, MOTIVO_SIN_LOADOUT)}
    ficha = catalogo.nave(actual.simbolo)
    vacio, cargado, motivo_rango = _rangos(actual, estado)
    return {
        "presente": True,
        "modelo": _nombre_de_nave(actual, estado),
        "nombre": actual.nombre,
        "ident": actual.ident,
        "capacidad_carga": actual.capacidad_carga,
        "plataforma": ficha.plataforma if ficha else None,
        "motivo_plataforma": None if ficha else MOTIVO_NAVE_NO_CONOCIDA,
        "rango_vacio": vacio,
        "rango_cargado": cargado,
        "motivo_rango": motivo_rango,
        "combustible": estado.combustible,
        "combustible_capacidad": estado.combustible_capacidad,
        "motivo_combustible": None if estado.combustible is not None else MOTIVO_SIN_COMBUSTIBLE,
    }


def _distancia(posicion: tuple[float, float, float] | None) -> float | None:
    if posicion is None:
        return None
    return math.dist(posicion, ajustes.CENTRO_POR_DEFECTO)


def _ubicacion(estado: Estado, sin_journal: bool) -> dict:
    if estado.sistema is None:
        return {"presente": False, "motivo": _causa(sin_journal, MOTIVO_SIN_UBICACION)}
    estacion = estado.estacion
    return {
        "presente": True,
        "sistema": estado.sistema,
        "posicion": list(estado.posicion) if estado.posicion else None,
        "estacion": {"nombre": estacion.nombre, "tipo": estacion.tipo} if estacion else None,
        "distancia_al_centro": _distancia(estado.posicion),
        "centro": ajustes.CENTRO_NOMBRE_POR_DEFECTO,
    }


def _carga(estado: Estado, sin_journal: bool) -> dict:
    if estado.carga is None:
        return {"presente": False, "motivo": _causa(sin_journal, MOTIVO_SIN_LECTURA)}
    capacidad = estado.nave.capacidad_carga if estado.nave else None
    return {
        "presente": True,
        "mercancias": [{"nombre": m.nombre, "cantidad": m.cantidad} for m in estado.carga],
        "total": sum(m.cantidad for m in estado.carga),
        "capacidad": capacidad,
    }


def _comandante(estado: Estado, sin_journal: bool) -> dict:
    return {
        "nombre": estado.comandante,
        "motivo_nombre": _causa(sin_journal, MOTIVO_SIN_COMANDANTE),
        "legacy": estado.legacy is True,
        "version": estado.version,
        "saldo": estado.creditos,
        "motivo_saldo": _causa(sin_journal, MOTIVO_SIN_SALDO),
    }


def _fuentes(estado: Estado, contexto: Contexto) -> dict:
    return {
        "journal": {"estado": contexto.journal, "ultimo_evento": estado.ultimo_evento},
        "eddn": {"estado": contexto.eddn},
        "spansh": {"estado": "sin_descarga"},
    }


def _datos(contexto: Contexto) -> dict:
    avisos = list(contexto.avisos_datos)
    if not contexto.base_disponible:
        avisos.append(AVISO_SIN_BASE)
    return {"motivo": contexto.motivo_datos, "avisos": avisos}


def a_diccionario(estado: Estado, contexto: Contexto) -> dict:
    sin_journal = contexto.journal != JOURNAL_LEYENDO
    return {
        "sin_journal": sin_journal,
        "comandante": _comandante(estado, sin_journal),
        "nave": _nave(estado, sin_journal),
        "ubicacion": _ubicacion(estado, sin_journal),
        "carga": _carga(estado, sin_journal),
        "fuentes": _fuentes(estado, contexto),
        "datos": _datos(contexto),
    }
