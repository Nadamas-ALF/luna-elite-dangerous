r"""Rango de salto de una nave.

`Nave` es el objeto de dominio: lo que la fase 1 guarda en la tabla `ships` y lo
que el motor de la fase 5 recibe para recalcular el rango con cada carga.
`desde_loadout` es el único punto público que entiende el dialecto del journal.

Fórmula y las dos lecturas del combustible, en docs/verificaciones.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from core import recursos

ETIQUETA_MASA_OPTIMA = "FSDOptimalMass"
ETIQUETA_COMBUSTIBLE = "MaxFuelPerJump"

RANURA_PROPULSOR = "FrameShiftDrive"
PREFIJO_POTENCIADOR = "int_guardianfsdbooster"


class LoadoutIncompleto(ValueError):
    """Al Loadout le falta algo imprescindible para calcular el rango."""


class PropulsorDesconocido(LookupError):
    """El Loadout trae un propulsor que no está en data/fsd.json."""


@dataclass(frozen=True)
class Propulsor:
    masa_optima: float
    combustible_por_salto: float
    multiplicador: float
    exponente: float

    def __post_init__(self) -> None:
        # Un valor negativo haría que la potencia fraccionaria devuelva un
        # complejo en lugar de fallar.
        for nombre in ("masa_optima", "combustible_por_salto", "multiplicador", "exponente"):
            if getattr(self, nombre) <= 0:
                raise ValueError(f"{nombre} tiene que ser positivo")


@dataclass(frozen=True)
class Nave:
    modelo: str
    masa_vacia: float
    capacidad_carga: int
    capacidad_combustible: float
    propulsor: Propulsor
    bono_ly: float = 0.0

    def __post_init__(self) -> None:
        if self.masa_vacia <= 0:
            raise ValueError("la masa en vacio tiene que ser positiva")
        if self.capacidad_carga < 0 or self.capacidad_combustible < 0:
            raise ValueError("las capacidades no pueden ser negativas")


@lru_cache(maxsize=1)
def _tabla() -> dict:
    return json.loads(recursos.ruta("data", "fsd.json").read_text(encoding="utf-8"))


def _esta_activo(modulo: dict) -> bool:
    """`On` falta en los journals antiguos; `Health` 0 es un módulo destruido."""
    return modulo.get("On", True) and modulo.get("Health", 1.0) > 0


def _propulsor_de_modulo(modulo: dict) -> Propulsor:
    base = _tabla()["propulsores"].get(modulo.get("Item", "").lower())
    if base is None:
        raise PropulsorDesconocido(modulo.get("Item"))

    masa_optima = base["masa_optima"]
    combustible = base["combustible_por_salto"]
    for modificador in modulo.get("Engineering", {}).get("Modifiers", []):
        if modificador.get("Label") == ETIQUETA_MASA_OPTIMA:
            masa_optima = modificador["Value"]
        elif modificador.get("Label") == ETIQUETA_COMBUSTIBLE:
            combustible = modificador["Value"]

    return Propulsor(
        masa_optima=masa_optima,
        combustible_por_salto=combustible,
        multiplicador=base["multiplicador"],
        exponente=base["exponente"],
    )


def _bono_de_potenciadores(modulos: list[dict]) -> float:
    """Los potenciadores Guardian suman ly fijos, no multiplican."""
    potenciadores = _tabla()["potenciadores"]
    return sum(
        potenciadores[clave]["bono_ly"]
        for modulo in modulos
        if (clave := modulo.get("Item", "").lower()) in potenciadores and _esta_activo(modulo)
    )


def _numero(loadout: dict, campo: str) -> float:
    valor = loadout.get(campo)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise LoadoutIncompleto(f"{campo} no es un numero ({valor!r})")
    return float(valor)


def desde_loadout(loadout: dict) -> Nave:
    """Único adaptador del evento Loadout del journal."""
    modulos = loadout.get("Modules")
    if not isinstance(modulos, list):
        raise LoadoutIncompleto("el Loadout no trae lista de modulos")

    modulo = next((m for m in modulos if m.get("Slot") == RANURA_PROPULSOR), None)
    if modulo is None:
        raise LoadoutIncompleto("el Loadout no trae propulsor")
    if not _esta_activo(modulo):
        raise LoadoutIncompleto("el propulsor esta apagado o destruido")

    deposito = loadout.get("FuelCapacity")
    if not isinstance(deposito, dict):
        raise LoadoutIncompleto("el Loadout no trae FuelCapacity")

    return Nave(
        modelo=loadout.get("Ship", ""),
        masa_vacia=_numero(loadout, "UnladenMass"),
        capacidad_carga=int(_numero(loadout, "CargoCapacity")),
        capacidad_combustible=_numero(deposito, "Main") + _numero(deposito, "Reserve"),
        propulsor=_propulsor_de_modulo(modulo),
        bono_ly=_bono_de_potenciadores(modulos),
    )


def rango(nave: Nave, carga: float, combustible: float) -> float:
    """Rango de un salto con `carga` toneladas y `combustible` en el depósito.

    `combustible` es obligatorio porque el rango que muestra el juego mientras
    vuelas depende de él, y es el que necesita el motor de rutas. Para la ficha
    técnica de la nave está `rango_maximo`.
    """
    if carga < 0 or combustible < 0:
        raise ValueError("la carga y el combustible no pueden ser negativos")

    propulsor = nave.propulsor
    # No puedes gastar en un salto más combustible del que llevas: con el
    # depósito por debajo de un salto, el rango baja.
    usable = min(combustible, propulsor.combustible_por_salto)
    if usable == 0:
        return nave.bono_ly

    masa_total = nave.masa_vacia + combustible + carga
    maximo = (usable / propulsor.multiplicador) ** (1 / propulsor.exponente)
    return maximo * propulsor.masa_optima / masa_total + nave.bono_ly


def rango_maximo(nave: Nave, carga: float = 0.0) -> float:
    """Ficha técnica: el rango que el juego escribe como MaxJumpRange.

    Cuenta solo el combustible de un salto, así que no cambia al repostar.
    """
    return rango(nave, carga=carga, combustible=nave.propulsor.combustible_por_salto)


def rango_de_comercio(nave: Nave) -> float:
    """Bodega y depósito llenos: el caso pesimista, y el que se midió en el juego.

    Al comerciar se reposta en cada estación, así que se sale con el depósito
    lleno (docs/decisiones.md, «Fase 5»).
    """
    return rango(nave, nave.capacidad_carga, nave.capacidad_combustible)
