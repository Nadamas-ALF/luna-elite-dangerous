"""Perfil de búsqueda (sección 7.1): lo que la interfaz manda y el motor usa.

El perfil llega de la interfaz como un diccionario y se valida entero aquí:
tipos, rangos y largo. Un campo de más o de menos lo rechaza, para que un error
de la interfaz no se convierta en una búsqueda distinta de la que se ve.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from core.config import ajustes

PLATAFORMAS = ("S", "M", "L")

TIPO_ORBITAL = "orbital"
TIPO_PUESTO = "puesto_avanzado"
TIPO_PLANETARIO = "puerto_planetario"
TIPO_ASENTAMIENTO = "asentamiento"
TIPO_COLONIZACION = "colonizacion"
TIPOS = ajustes.TIPOS_DE_ESTACION

ORIGENES = ("propio", "eddn", "spansh")

ORDEN_GANANCIA_HORA = "ganancia_hora"
ORDENES = (ORDEN_GANANCIA_HORA, "ganancia_viaje", "ganancia_tonelada", "distancia")

LARGO_MAXIMO_NOMBRE = 100
CAPACIDAD_MAXIMA = 5_000
RANGO_MAXIMO = 500.0
CREDITOS_MAXIMOS = 2**53
DISTANCIA_LY_MAXIMA = 1_000.0
DISTANCIA_LS_MAXIMA = 1e7
STOCK_MAXIMO_PCT = 1_000.0
HORAS_MAXIMAS = 24.0


class PerfilInvalido(ValueError):
    """`campo` dice qué parámetro rechazar en la interfaz."""

    def __init__(self, campo: str) -> None:
        super().__init__(campo)
        self.campo = campo


@dataclass(frozen=True)
class Perfil:
    capacidad: int
    rango: float
    plataforma: str
    creditos: int | None
    origen: str
    distancia_max_ly: float = 50.0
    distancia_max_ls: float = 5_000.0
    antiguedad_max_h: float = 24.0
    stock_minimo_pct: float = 100.0
    tipos: tuple[str, ...] = TIPOS
    origenes: tuple[str, ...] = ORIGENES
    raras: bool = False
    horas_sesion: float = 1.0
    orden: str = ORDEN_GANANCIA_HORA

    @property
    def stock_minimo(self) -> int:
        return math.ceil(self.capacidad * self.stock_minimo_pct / 100)

    def a_dict(self) -> dict:
        return {**asdict(self), "tipos": list(self.tipos), "origenes": list(self.origenes)}


def _numero(datos: dict, campo: str, minimo: float, maximo: float, abierto: bool = False) -> float:
    valor = datos.get(campo)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise PerfilInvalido(campo)
    # Un int de JSON puede ser de cualquier tamaño y `math.isfinite` lo pasaría a float.
    if isinstance(valor, float) and not math.isfinite(valor):
        raise PerfilInvalido(campo)
    por_debajo = valor <= minimo if abierto else valor < minimo
    if por_debajo or valor > maximo:
        raise PerfilInvalido(campo)
    return float(valor)


def _entero(datos: dict, campo: str, minimo: int, maximo: int) -> int:
    valor = _numero(datos, campo, minimo, maximo)
    if not valor.is_integer():
        raise PerfilInvalido(campo)
    return int(valor)


def _creditos(datos: dict) -> int | None:
    return (
        None if datos.get("creditos") is None else _entero(datos, "creditos", 0, CREDITOS_MAXIMOS)
    )


def nombre(valor: object, campo: str) -> str:
    """Un nombre de sistema o de perfil: texto imprimible, sin vacío y con largo acotado."""
    if not isinstance(valor, str):
        raise PerfilInvalido(campo)
    limpio = valor.strip()
    if not limpio or len(limpio) > LARGO_MAXIMO_NOMBRE or not limpio.isprintable():
        raise PerfilInvalido(campo)
    return limpio


def _opcion(datos: dict, campo: str, permitidas: tuple[str, ...]) -> str:
    valor = datos.get(campo)
    if valor not in permitidas:
        raise PerfilInvalido(campo)
    return valor


def _seleccion(datos: dict, campo: str, permitidas: tuple[str, ...]) -> tuple[str, ...]:
    """Subconjunto no vacío, en el orden canónico y sin repetidos."""
    valor = datos.get(campo)
    if not isinstance(valor, list) or not valor or len(valor) > len(permitidas):
        raise PerfilInvalido(campo)
    if any(v not in permitidas for v in valor):
        raise PerfilInvalido(campo)
    return tuple(p for p in permitidas if p in valor)


def _booleano(datos: dict, campo: str) -> bool:
    valor = datos.get(campo)
    if not isinstance(valor, bool):
        raise PerfilInvalido(campo)
    return valor


CAMPOS = frozenset(Perfil.__dataclass_fields__)


def desde_dict(datos: object, tope_antiguedad_dias: int) -> Perfil:
    """`tope_antiguedad_dias` es el de la configuración (`ajustes.tope_de_antiguedad_dias`)."""
    if not isinstance(datos, dict):
        raise PerfilInvalido("perfil")
    sobrantes = set(datos) - CAMPOS
    faltantes = CAMPOS - set(datos)
    if sobrantes or faltantes:
        raise PerfilInvalido(sorted(sobrantes or faltantes)[0])
    return Perfil(
        capacidad=_entero(datos, "capacidad", 1, CAPACIDAD_MAXIMA),
        rango=_numero(datos, "rango", 0, RANGO_MAXIMO, abierto=True),
        plataforma=_opcion(datos, "plataforma", PLATAFORMAS),
        creditos=_creditos(datos),
        origen=nombre(datos.get("origen"), "origen"),
        distancia_max_ly=_numero(datos, "distancia_max_ly", 0, DISTANCIA_LY_MAXIMA, abierto=True),
        distancia_max_ls=_numero(datos, "distancia_max_ls", 0, DISTANCIA_LS_MAXIMA, abierto=True),
        antiguedad_max_h=_numero(
            datos, "antiguedad_max_h", 0, tope_antiguedad_dias * 24.0, abierto=True
        ),
        stock_minimo_pct=_numero(datos, "stock_minimo_pct", 0, STOCK_MAXIMO_PCT),
        tipos=_seleccion(datos, "tipos", TIPOS),
        origenes=_seleccion(datos, "origenes", ORIGENES),
        raras=_booleano(datos, "raras"),
        horas_sesion=_numero(datos, "horas_sesion", 0, HORAS_MAXIMAS, abierto=True),
        orden=_opcion(datos, "orden", ORDENES),
    )
