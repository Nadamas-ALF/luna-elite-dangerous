"""Clasificación de las estaciones a partir de lo que dice el journal (sección 5.1).

La colonización se reconoce por el nombre, no por `StationType` (una nave de
colonización es una `SurfaceStation`) ni por la economía `Colony`, que también
llevan puestos corrientes (docs/decisiones.md). Solo se distinguen las naves y
los sitios de construcción; una estación de colonización ya terminada es una
estación corriente.
"""

from __future__ import annotations

ORBITAL = "orbital"
PUESTO_AVANZADO = "puesto_avanzado"
ASENTAMIENTO = "asentamiento"
FLEET_CARRIER = "fleet_carrier"
COLONIZACION = "colonizacion"
DESCONOCIDA = "desconocida"

_CATEGORIA = {
    "coriolis": ORBITAL,
    "orbis": ORBITAL,
    "ocellus": ORBITAL,
    "dodec": ORBITAL,
    "asteroidbase": ORBITAL,
    "megaship": ORBITAL,
    "craterport": ORBITAL,
    "surfacestation": ORBITAL,
    "outpost": PUESTO_AVANZADO,
    "crateroutpost": PUESTO_AVANZADO,
    "onfootsettlement": ASENTAMIENTO,
    "fleetcarrier": FLEET_CARRIER,
}

_PLANETARIAS = frozenset({"craterport", "crateroutpost", "surfacestation", "onfootsettlement"})


_NOMBRES_DE_COLONIZACION = ("$ext_panel_colonisationship;", "orbital construction site:")


def es_de_colonizacion(nombre: str | None) -> bool:
    return (nombre or "").strip().lower().startswith(_NOMBRES_DE_COLONIZACION)


def categoria(tipo: str | None, nombre: str | None = None) -> str:
    if es_de_colonizacion(nombre):
        return COLONIZACION
    return _CATEGORIA.get((tipo or "").lower(), DESCONOCIDA)


def es_planetaria(tipo: str | None) -> bool:
    return (tipo or "").lower() in _PLANETARIAS


def plataforma_maxima(plataformas: object) -> str | None:
    """S, M o L según la plataforma más grande con huecos; None si no se sabe."""
    if not isinstance(plataformas, dict):
        return None
    for tamano, letra in (("Large", "L"), ("Medium", "M"), ("Small", "S")):
        cantidad = plataformas.get(tamano)
        if isinstance(cantidad, int) and not isinstance(cantidad, bool) and cantidad > 0:
            return letra
    return None
