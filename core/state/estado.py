"""Estado del comandante, reconstruido a partir de los eventos del journal.

`Estado` es inmutable y `aplicar` devuelve uno nuevo, así que el hilo que lee
el journal puede publicarlo y los hilos de la interfaz leerlo sin candados.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from core import nave as modelo_nave

# El juego Legacy (3.8) y el Live (4.x) comparten carpeta de journal; la
# versión mayor es lo que los distingue (sección 4.1).
VERSION_MAYOR_LIVE = 4

ERROR_LOADOUT = "loadout_incompleto"
ERROR_PROPULSOR = "propulsor_desconocido"


@dataclass(frozen=True)
class Mercancia:
    nombre: str
    cantidad: int


@dataclass(frozen=True)
class Estacion:
    nombre: str
    market_id: int | None
    tipo: str | None


@dataclass(frozen=True)
class NaveActual:
    ship_id: int | None
    simbolo: str
    nombre: str
    ident: str
    capacidad_carga: int
    capacidad_combustible: float
    datos: modelo_nave.Nave | None
    error: str | None = None


@dataclass(frozen=True)
class Estado:
    legacy: bool | None = None
    version: str | None = None
    fid: str | None = None
    comandante: str | None = None
    creditos: int | None = None
    nave: NaveActual | None = None
    nave_localizada: tuple[int, str] | None = None
    combustible: float | None = None
    combustible_capacidad: float | None = None
    sistema: str | None = None
    system_address: int | None = None
    posicion: tuple[float, float, float] | None = None
    estacion: Estacion | None = None
    carga: tuple[Mercancia, ...] | None = None
    ultimo_evento: str | None = None


def es_legacy(version: object) -> bool | None:
    """None cuando la versión no se entiende: no se acusa de Legacy sin motivo."""
    try:
        return int(str(version).split(".")[0]) < VERSION_MAYOR_LIVE
    except ValueError:
        return None


def _numero(valor: object) -> float | None:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    return float(valor)


def _entero(valor: object) -> int | None:
    numero = _numero(valor)
    return None if numero is None else int(numero)


def _texto(valor: object) -> str | None:
    """Texto sin espacios sobrantes, o None si falta o está vacío."""
    if not isinstance(valor, str):
        return None
    return valor.strip() or None


def _posicion(valor: object) -> tuple[float, float, float] | None:
    if not isinstance(valor, list) or len(valor) != 3:
        return None
    x, y, z = (_numero(c) for c in valor)
    return None if None in (x, y, z) else (x, y, z)


def _al_abrir_journal(estado: Estado, evento: dict) -> Estado:
    version = _texto(evento.get("gameversion"))
    if es_legacy(version):
        # Los datos de Legacy no valen para Live: se descarta lo anterior.
        return Estado(legacy=True, version=version)
    return replace(estado, legacy=es_legacy(version), version=version)


def _al_cargar_partida(estado: Estado, evento: dict) -> Estado:
    ship_id = _entero(evento.get("ShipID"))
    localizada = _texto(evento.get("Ship_Localised"))
    return replace(
        estado,
        fid=_texto(evento.get("FID")) or estado.fid,
        comandante=_texto(evento.get("Commander")) or estado.comandante,
        creditos=_entero(evento.get("Credits")),
        combustible=_numero(evento.get("FuelLevel")),
        combustible_capacidad=_numero(evento.get("FuelCapacity")),
        nave_localizada=(ship_id, localizada) if ship_id is not None and localizada else None,
    )


def _comandante(estado: Estado, evento: dict) -> Estado:
    return replace(
        estado,
        fid=_texto(evento.get("FID")) or estado.fid,
        comandante=_texto(evento.get("Name")) or estado.comandante,
    )


def _nave_de_loadout(loadout: dict) -> NaveActual:
    deposito = loadout.get("FuelCapacity")
    principal = _numero(deposito.get("Main")) if isinstance(deposito, dict) else None
    datos, error = None, None
    try:
        datos = modelo_nave.desde_loadout(loadout)
    except modelo_nave.PropulsorDesconocido:
        error = ERROR_PROPULSOR
    except modelo_nave.LoadoutIncompleto:
        error = ERROR_LOADOUT
    return NaveActual(
        ship_id=_entero(loadout.get("ShipID")),
        simbolo=_texto(loadout.get("Ship")) or "",
        nombre=_texto(loadout.get("ShipName")) or "",
        ident=_texto(loadout.get("ShipIdent")) or "",
        capacidad_carga=_entero(loadout.get("CargoCapacity")) or 0,
        capacidad_combustible=principal or 0.0,
        datos=datos,
        error=error,
    )


def _al_equipar(estado: Estado, evento: dict) -> Estado:
    actual = _nave_de_loadout(evento)
    return replace(
        estado,
        nave=actual,
        combustible_capacidad=actual.capacidad_combustible or estado.combustible_capacidad,
    )


def _estacion(evento: dict) -> Estacion | None:
    nombre = _texto(evento.get("StationName"))
    if nombre is None:
        return None
    return Estacion(nombre, _entero(evento.get("MarketID")), _texto(evento.get("StationType")))


def _llegada(estado: Estado, evento: dict) -> Estado:
    """Location, FSDJump y CarrierJump dicen dónde estás; no siempre atracado."""
    atracado = evento.get("Docked") is True
    combustible = _numero(evento.get("FuelLevel"))
    return replace(
        estado,
        sistema=_texto(evento.get("StarSystem")) or estado.sistema,
        system_address=_entero(evento.get("SystemAddress")) or estado.system_address,
        posicion=_posicion(evento.get("StarPos")) or estado.posicion,
        estacion=_estacion(evento) if atracado else None,
        combustible=estado.combustible if combustible is None else combustible,
    )


def _al_atracar(estado: Estado, evento: dict) -> Estado:
    return replace(
        estado,
        sistema=_texto(evento.get("StarSystem")) or estado.sistema,
        system_address=_entero(evento.get("SystemAddress")) or estado.system_address,
        estacion=_estacion(evento),
    )


def _al_desatracar(estado: Estado, evento: dict) -> Estado:
    return replace(estado, estacion=None)


def _inventario(evento: dict) -> tuple[Mercancia, ...] | None:
    """None cuando el evento no trae el inventario: hay que leer Cargo.json."""
    if evento.get("Count") == 0:
        return ()
    articulos = evento.get("Inventory")
    if not isinstance(articulos, list):
        return None
    carga = []
    for articulo in articulos:
        if not isinstance(articulo, dict):
            continue
        nombre = _texto(articulo.get("Name_Localised")) or _texto(articulo.get("Name"))
        cantidad = _entero(articulo.get("Count"))
        if nombre and cantidad:
            carga.append(Mercancia(nombre, cantidad))
    return tuple(carga)


def _al_cambiar_carga(estado: Estado, evento: dict) -> Estado:
    if evento.get("Vessel", "Ship") != "Ship":
        return estado
    carga = _inventario(evento)
    return estado if carga is None else replace(estado, carga=carga)


def _al_cambiar_estado(estado: Estado, evento: dict) -> Estado:
    combustible = evento.get("Fuel")
    principal = _numero(combustible.get("FuelMain")) if isinstance(combustible, dict) else None
    return estado if principal is None else replace(estado, combustible=principal)


def _compra(estado: Estado, evento: dict) -> Estado:
    gasto = _entero(evento.get("TotalCost"))
    if estado.creditos is None or gasto is None:
        return estado
    return replace(estado, creditos=estado.creditos - gasto)


def _venta(estado: Estado, evento: dict) -> Estado:
    ingreso = _entero(evento.get("TotalSale"))
    if estado.creditos is None or ingreso is None:
        return estado
    return replace(estado, creditos=estado.creditos + ingreso)


MANEJADORES: dict[str, Callable[[Estado, dict], Estado]] = {
    "Fileheader": _al_abrir_journal,
    "Commander": _comandante,
    "LoadGame": _al_cargar_partida,
    "Loadout": _al_equipar,
    "Location": _llegada,
    "FSDJump": _llegada,
    "CarrierJump": _llegada,
    "Docked": _al_atracar,
    "Undocked": _al_desatracar,
    "Cargo": _al_cambiar_carga,
    "Status": _al_cambiar_estado,
    "MarketBuy": _compra,
    "MarketSell": _venta,
}


def aplicar(estado: Estado, evento: dict) -> Estado:
    """Estado tras el evento; los eventos que no interesan lo dejan igual."""
    nombre = evento.get("event")
    manejador = MANEJADORES.get(nombre)
    if manejador is None or (estado.legacy and nombre != "Fileheader"):
        return estado
    nuevo = manejador(estado, evento)
    marca = _texto(evento.get("timestamp"))
    # Status.json lleva la hora del archivo, no la de un evento del journal.
    return replace(nuevo, ultimo_evento=marca) if marca and nombre != "Status" else nuevo
