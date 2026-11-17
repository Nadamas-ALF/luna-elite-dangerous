"""Del journal a lo que se guarda: lo comparten el seguimiento en vivo y la importación.

Un `Plegador` aplica eventos a un `Estado` y, con la misma lógica que el seguimiento,
anota compras, ventas, tramos, bloques y muestras de tiempo en un `Lote`. Guardar el
lote es cosa de `guardar`, que solo encola trabajos al escritor.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from core import catalogo
from core import nave as modelo_nave
from core.db import comandante
from core.db.escritor import Escritor
from core.journal import comercio, sesiones, tiempos
from core.state.estado import Estado, NaveActual, aplicar


@dataclass
class Lote:
    """Lo que un lote de eventos deja para guardar, en un trabajo del escritor por tipo."""

    comandantes: dict[str, tuple[str, str]] = field(default_factory=dict)
    naves: dict[tuple[str, int], tuple[NaveActual, str]] = field(default_factory=dict)
    muestras: list[comandante.MuestraDeTiempo] = field(default_factory=list)
    operaciones: list[tuple[str, int | None, comercio.Operacion]] = field(default_factory=list)
    tramos: list[tuple[str, comercio.Tramo]] = field(default_factory=list)
    bloques: list[sesiones.Bloque] = field(default_factory=list)


class Plegador:
    """Lleva lo que hay entre un evento y el siguiente: cronómetro, libro y actividad."""

    def __init__(self) -> None:
        self._cronometro = tiempos.Cronometro()
        self._libro = comercio.Libro()
        self._actividad = sesiones.Actividad()
        self._bloque_guardado: sesiones.Bloque | None = None

    def plegar(self, estado: Estado, eventos: list[dict]) -> tuple[Estado, Lote]:
        """Aplica los eventos y devuelve el estado y lo que cambió, para guardar una vez."""
        lote = Lote()
        if not eventos:
            return estado, lote
        for evento in eventos:
            estado = aplicar(estado, evento)
            if estado.fid and estado.comandante:
                lote.comandantes[estado.fid] = (estado.comandante, estado.ultimo_evento or "")
            if evento.get("event") == "Loadout" and es_guardable(estado):
                clave = (estado.fid, estado.nave.ship_id)
                lote.naves[clave] = (estado.nave, estado.ultimo_evento or "")
            lote.muestras += self._medir(estado, evento)
            self._anotar_comercio(estado, evento, lote)
        if self._actividad.bloque not in (None, self._bloque_guardado):
            lote.bloques.append(self._actividad.bloque)
            self._bloque_guardado = self._actividad.bloque
        return estado, lote

    def _anotar_comercio(self, estado: Estado, evento: dict, lote: Lote) -> None:
        """Compras, ventas, tramos y bloques de actividad (7.5); de Legacy, nada."""
        if estado.legacy:
            self._libro = comercio.Libro()
            return
        hecha = comercio.operacion(estado, evento)
        self._libro, tramo = comercio.anotar(self._libro, estado, evento)
        self._actividad, cerrado = sesiones.anotar(self._actividad, estado, evento, hecha)
        if not estado.fid:
            return
        ship_id = estado.nave.ship_id if estado.nave else None
        if hecha is not None:
            lote.operaciones.append((estado.fid, ship_id, hecha))
        if tramo is not None:
            lote.tramos.append((estado.fid, tramo))
        if cerrado is not None:
            lote.bloques.append(cerrado)

    def _medir(self, estado: Estado, evento: dict) -> list[comandante.MuestraDeTiempo]:
        """Muestras de tiempo de la nave en la que se cerraron (8.1); de Legacy, ninguna."""
        if estado.legacy:
            self._cronometro = tiempos.Cronometro()
            return []
        self._cronometro, nuevas = tiempos.medir(self._cronometro, evento)
        if not nuevas or not es_guardable(estado):
            return []
        return [
            comandante.MuestraDeTiempo(
                estado.fid, estado.nave.ship_id, m.tramo, m.fin, m.segundos, m.distancia_ls
            )
            for m in nuevas
        ]


def guardar(
    escritor: Escritor, lote: Lote, fallo: Callable[[Exception], None] | None = None
) -> None:
    """Cada comandante visto se da de alta antes que lo suyo (clave foránea).

    `fallo` se avisa de cada trabajo que el escritor tuvo que deshacer.
    """
    for fid, (nombre, visto) in lote.comandantes.items():
        escritor.encolar(
            lambda c, fid=fid, nombre=nombre, visto=visto: comandante.registrar_comandante(
                c, fid, nombre, visto
            ),
            fallo=fallo,
        )
    for (dueno, ship_id), (actual, fecha) in lote.naves.items():
        ficha = _ficha(dueno, ship_id, actual, fecha)
        escritor.encolar(lambda c, ficha=ficha: comandante.guardar_nave(c, ficha), fallo=fallo)
    if lote.muestras:
        escritor.encolar(lambda c: comandante.guardar_muestras(c, lote.muestras), fallo=fallo)
    if lote.operaciones:
        escritor.encolar(lambda c: comandante.guardar_operaciones(c, lote.operaciones), fallo=fallo)
    if lote.tramos:
        escritor.encolar(lambda c: comandante.guardar_tramos(c, lote.tramos), fallo=fallo)
    if lote.bloques:
        escritor.encolar(lambda c: comandante.guardar_bloques(c, lote.bloques), fallo=fallo)


def es_guardable(estado: Estado) -> bool:
    """La tabla `ships` se indexa por comandante e ID de nave; el ID 0 es válido."""
    return bool(estado.fid) and estado.nave is not None and estado.nave.ship_id is not None


def _ficha(fid: str, ship_id: int, actual: NaveActual, fecha: str) -> comandante.FichaDeNave:
    """Rangos de ficha técnica: con un salto de combustible, vacía y con la bodega llena."""
    vacio = cargado = None
    if actual.datos is not None:
        vacio = modelo_nave.rango_maximo(actual.datos)
        cargado = modelo_nave.rango_maximo(actual.datos, actual.capacidad_carga)
    en_catalogo = catalogo.nave(actual.simbolo)
    return comandante.FichaDeNave(
        fid=fid,
        ship_id=ship_id,
        modelo=actual.simbolo,
        nombre=actual.nombre,
        capacidad_carga=actual.capacidad_carga,
        rango_vacio=vacio,
        rango_cargado=cargado,
        plataforma=en_catalogo.plataforma if en_catalogo else None,
        actualizado=fecha,
    )
