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
    # El juego aún llama así a algunos Ocellus.
    "bernal": ORBITAL,
    "dodec": ORBITAL,
    "asteroidbase": ORBITAL,
    "megaship": ORBITAL,
    "craterport": ORBITAL,
    "surfacestation": ORBITAL,
    "outpost": PUESTO_AVANZADO,
    "crateroutpost": PUESTO_AVANZADO,
    "onfootsettlement": ASENTAMIENTO,
    "fleetcarrier": FLEET_CARRIER,
    "spaceconstructiondepot": COLONIZACION,
    "planetaryconstructiondepot": COLONIZACION,
}

_PLANETARIAS = frozenset(
    {
        "craterport",
        "crateroutpost",
        "surfacestation",
        "onfootsettlement",
        "planetaryconstructiondepot",
    }
)


_NOMBRES_DE_COLONIZACION = (
    "$ext_panel_colonisationship;",
    "orbital construction site:",
    "planetary construction site:",
    "system colonisation ship",
)


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


# Spansh nombra los tipos de otra forma que el journal.
_CATEGORIA_DE_SPANSH = {
    "coriolis starport": ORBITAL,
    "orbis starport": ORBITAL,
    "ocellus starport": ORBITAL,
    "dodec starport": ORBITAL,
    "asteroid base": ORBITAL,
    "mega ship": ORBITAL,
    "planetary port": ORBITAL,
    "outpost": PUESTO_AVANZADO,
    "planetary outpost": PUESTO_AVANZADO,
    "settlement": ASENTAMIENTO,
    "space construction depot": COLONIZACION,
    "planetary construction depot": COLONIZACION,
}

_PLANETARIAS_DE_SPANSH = frozenset(
    {"planetary port", "planetary outpost", "settlement", "planetary construction depot"}
)


def categoria_de_spansh(tipo: str | None, nombre: str | None, en_cuerpo: bool) -> str:
    """`en_cuerpo`: un asentamiento de Odyssey llega sin `type`, solo dentro de un cuerpo."""
    clave = (tipo or "").lower()
    if es_de_colonizacion(nombre) or clave.endswith("construction depot"):
        return COLONIZACION
    if clave.endswith("carrier"):
        return FLEET_CARRIER
    if not clave and en_cuerpo:
        return ASENTAMIENTO
    return _CATEGORIA_DE_SPANSH.get(clave, DESCONOCIDA)


def es_planetaria_de_spansh(tipo: str | None, en_cuerpo: bool) -> bool:
    clave = (tipo or "").lower()
    return clave in _PLANETARIAS_DE_SPANSH or (not clave and en_cuerpo)
