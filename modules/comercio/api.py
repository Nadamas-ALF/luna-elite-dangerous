"""Lo que la interfaz pide al módulo Comercio (sección 3: `modules/comercio/api.py`).

`core.api.Api` solo delega aquí. Todo lo que llega de la interfaz se valida
antes de usarlo y la respuesta son datos simples; un fallo es `{"error": <código>}`.

Cada pantalla tiene su búsqueda en curso: una nueva de Rutas cancela la anterior
de Rutas, y lo mismo en Ahora (E-16). Así el recálculo automático de Ahora no
corta una búsqueda de rutas que lanzó el usuario. La cancelada no devuelve nada.

El módulo no lee el journal: el estado del comandante le llega del núcleo y los
precios, de la base.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import MISSING, fields
from datetime import UTC, datetime
from pathlib import Path

from core import catalogo
from core.config import ajustes
from core.db import mercado
from core.db.escritor import Escritor, Trabajo, abrir_lectura
from core.state.estado import Estado, precio_de_compra, vendibles
from modules.comercio import perfiles, salida, timing
from modules.comercio.engine import ahora as modo_ahora
from modules.comercio.engine import candidatos, rutas
from modules.comercio.engine.calculo import Curva
from modules.comercio.engine.candidatos import BusquedaCancelada, Posicion
from modules.comercio.engine.perfil import Perfil, PerfilInvalido, desde_dict, rango_de_comercio
from modules.comercio.engine.perfil import nombre as validar_nombre

registro = logging.getLogger("luna.comercio")

ERROR_PARAMETRO = "parametro"
ERROR_PERFIL = "perfil"
ERROR_SIN_BASE = "sin_base"
ERROR_LEGACY = "legacy"
ERROR_ORIGEN = "origen_desconocido"
ERROR_SIN_POSICION = "sin_posicion"
ERROR_BASE = "base"
ERROR_NO_GUARDADO = "no_guardado"

# Lo que se espera al escritor antes de contestar «pendiente»: durante una importación
# de Spansh puede tardar minutos, y el perfil se guarda igual cuando quede libre.
ESPERA_DE_ESCRITURA = 5.0

MODOS = {"un_salto": (rutas.un_salto, salida.tramo), "bucle": (rutas.bucle, salida.bucle)}

Reloj = Callable[[], datetime]


class _Rechazo(Exception):  # noqa: N818 - no es un fallo: es la respuesta a la interfaz
    def __init__(self, respuesta: dict) -> None:
        super().__init__(respuesta)
        self.respuesta = respuesta


class Turno:
    """La búsqueda en curso de una pantalla: empezar otra cancela la anterior."""

    def __init__(self) -> None:
        self._candado = threading.Lock()
        self._actual: threading.Event | None = None

    @contextmanager
    def empezar(self) -> Iterator[threading.Event]:
        with self._candado:
            if self._actual is not None:
                self._actual.set()
            parar = self._actual = threading.Event()
        try:
            yield parar
        finally:
            with self._candado:
                if self._actual is parar:
                    self._actual = None


def _perfil_por_defecto() -> dict:
    return {c.name: c.default for c in fields(Perfil) if c.default is not MISSING}


class Comercio:
    def __init__(
        self,
        estado: Callable[[], Estado],
        config: Path,
        base: Path | None,
        escritor: Escritor | None,
        reloj: Reloj = lambda: datetime.now(UTC),
    ) -> None:
        self._estado = estado
        self._config = config
        self._base = base
        self._escritor = escritor
        self._reloj = reloj
        self._turno_rutas = Turno()
        self._turno_ahora = Turno()

    def perfil_inicial(self) -> dict:
        """El perfil autocompletado con la nave actual (7.1) y qué campos vienen de ella."""
        estado = self._estado()
        de_la_nave = _valores_de_la_nave(estado)
        tope = ajustes.tope_de_antiguedad_dias(self._config)
        perfil = {
            **_perfil_por_defecto(),
            "tipos": ajustes.tipos_de_estacion(self._config),
            **{campo: valor for campo, valor in de_la_nave.items() if valor is not None},
        }
        perfil["antiguedad_max_h"] = min(perfil["antiguedad_max_h"], tope * 24.0)
        return {
            "perfil": {campo: _a_json(perfil.get(campo)) for campo in Perfil.__dataclass_fields__},
            "automaticos": [campo for campo, valor in de_la_nave.items() if valor is not None],
            "limites": {"antiguedad_max_h": tope * 24.0},
        }

    def buscar_rutas(self, modo: object, datos: object) -> dict:
        if not isinstance(modo, str) or modo not in MODOS:
            return {"error": ERROR_PARAMETRO, "campo": "modo"}
        buscar, convertir = MODOS[modo]
        try:
            perfil, estado = self._entrada(datos)
            with self._turno_rutas.empezar() as parar, self._lectura() as conexion:
                centro = _centro(conexion, perfil, estado)
                cargados = candidatos.cargar(conexion, perfil, centro, self._reloj(), parar=parar)
                tiempos = _tiempos(conexion, estado)
                resultados = buscar(cargados, perfil, self._curva(), tiempos)
                nombres = salida.nombres_de_mercancias(conexion)
                _comprobar(parar)
        except _Rechazo as rechazo:
            return rechazo.respuesta
        except BusquedaCancelada:
            return {"cancelada": True}
        return {
            "modo": modo,
            "resultados": [convertir(r, nombres, perfil.horas_sesion, tiempos) for r in resultados],
        }

    def ahora(self, datos: object) -> dict:
        """Vender la carga y comprar desde aquí, alrededor de donde estás (7.3).

        El origen del perfil no cuenta: Ahora es siempre desde tu posición, así que
        un origen vacío o mal escrito en Rutas no lo estropea.
        """
        actual = self._estado()
        if actual.posicion is None and not actual.legacy:
            return {"error": ERROR_SIN_POSICION}
        if isinstance(datos, dict) and actual.sistema:
            datos = {**datos, "origen": actual.sistema}
        try:
            perfil, estado = self._entrada(datos)
            if estado.posicion is None:
                raise _Rechazo({"error": ERROR_SIN_POSICION})
            with self._turno_ahora.empezar() as parar, self._lectura() as conexion:
                respuesta = self._ahora(conexion, perfil, estado, parar)
                _comprobar(parar)
        except _Rechazo as rechazo:
            return rechazo.respuesta
        except BusquedaCancelada:
            return {"cancelada": True}
        return respuesta

    def _ahora(
        self,
        conexion: sqlite3.Connection,
        perfil: Perfil,
        estado: Estado,
        parar: threading.Event,
    ) -> dict:
        momento, curva = self._reloj(), self._curva()
        # Lo que ya llevas se vende aunque sea raro: está comprado.
        cargados = candidatos.cargar(
            conexion, perfil, estado.posicion, momento, raras=True, parar=parar
        )
        nombres = salida.nombres_de_mercancias(conexion)
        tiempos = _tiempos(conexion, estado)
        carga = _carga(estado)
        ventas = modo_ahora.vender_carga(cargados, carga, estado.posicion, perfil, curva, tiempos)
        market_id = estado.estacion.market_id if estado.estacion else None
        desde_aqui = None
        if market_id is not None:
            ofertas = candidatos.ofertas_de_la_estacion(conexion, market_id, perfil, momento)
            tramos = modo_ahora.desde_aqui(cargados, ofertas, perfil, curva, tiempos)
            desde_aqui = [salida.tramo(t, nombres, perfil.horas_sesion, tiempos) for t in tramos]
        return {
            "vender": [_vender(articulo, ventas, nombres, tiempos) for articulo in carga],
            "desde_aqui": desde_aqui,
        }

    def perfiles_guardados(self) -> dict:
        tope = ajustes.tope_de_antiguedad_dias(self._config)
        try:
            with self._lectura() as conexion:
                guardados = perfiles.listar(conexion, tope)
        except _Rechazo as rechazo:
            return rechazo.respuesta
        return {"perfiles": [{"nombre": g.nombre, "perfil": g.perfil.a_dict()} for g in guardados]}

    def guardar_perfil(self, nombre: object, datos: object) -> dict:
        try:
            limpio = validar_nombre(nombre, "nombre")
            perfil = desde_dict(datos, ajustes.tope_de_antiguedad_dias(self._config))
        except PerfilInvalido as error:
            return {"error": ERROR_PERFIL, "campo": error.campo}
        return self._escribir(lambda conexion: perfiles.guardar(conexion, limpio, perfil))

    def borrar_perfil(self, nombre: object) -> dict:
        try:
            limpio = validar_nombre(nombre, "nombre")
        except PerfilInvalido as error:
            return {"error": ERROR_PERFIL, "campo": error.campo}
        return self._escribir(lambda conexion: perfiles.borrar(conexion, limpio))

    def ajustes_de_busqueda(self) -> dict:
        """Lo que Configuración enseña de Comercio: el tope de antigüedad y los tipos."""
        return {
            "tope_antiguedad_dias": ajustes.tope_de_antiguedad_dias(self._config),
            "tope_maximo_dias": ajustes.TOPE_ANTIGUEDAD_DIAS_MAXIMO,
            "tipos": list(ajustes.tipos_de_estacion(self._config)),
        }

    def guardar_ajustes_de_busqueda(self, tope_dias: object, tipos: object) -> dict:
        if not _es_tope(tope_dias):
            return {"error": ERROR_PARAMETRO, "campo": "tope_antiguedad_dias"}
        if not _son_tipos(tipos):
            return {"error": ERROR_PARAMETRO, "campo": "tipos"}
        canonicos = tuple(t for t in ajustes.TIPOS_DE_ESTACION if t in tipos)
        if not ajustes.guardar_busqueda(self._config, tope_dias, canonicos):
            return {"error": ERROR_NO_GUARDADO}
        return {"ok": True, **self.ajustes_de_busqueda()}

    def _entrada(self, datos: object) -> tuple[Perfil, Estado]:
        try:
            perfil = desde_dict(datos, ajustes.tope_de_antiguedad_dias(self._config))
        except PerfilInvalido as error:
            raise _Rechazo({"error": ERROR_PERFIL, "campo": error.campo}) from None
        estado = self._estado()
        # 6.1: con un journal de Legacy no se enseñan rutas con datos de Live.
        if estado.legacy:
            raise _Rechazo({"error": ERROR_LEGACY})
        return perfil, estado

    @contextmanager
    def _lectura(self) -> Iterator[sqlite3.Connection]:
        """Conexión propia de solo lectura: cada llamada de la interfaz llega en su hilo."""
        if self._base is None:
            raise _Rechazo({"error": ERROR_SIN_BASE})
        try:
            with closing(abrir_lectura(self._base)) as conexion:
                yield conexion
        except sqlite3.Error:
            registro.exception("fallo al leer la base para comercio")
            raise _Rechazo({"error": ERROR_BASE}) from None

    def _curva(self) -> Curva:
        return Curva(*ajustes.curva_de_confianza(self._config))

    def _escribir(self, trabajo: Trabajo) -> dict:
        """Espera al escritor un rato; si sigue ocupado, el trabajo queda en su cola."""
        if self._escritor is None:
            return {"error": ERROR_SIN_BASE}
        hecho = threading.Event()
        respuesta: dict = {"pendiente": True}

        def al_terminar(_: object) -> None:
            respuesta.update(pendiente=False, ok=True)
            hecho.set()

        def al_fallar(_: Exception) -> None:
            respuesta.update(pendiente=False, error=ERROR_NO_GUARDADO)
            hecho.set()

        self._escritor.encolar(trabajo, al_terminar, al_fallar)
        hecho.wait(ESPERA_DE_ESCRITURA)
        return dict(respuesta)


def _es_tope(dias: object) -> bool:
    return (
        isinstance(dias, int)
        and not isinstance(dias, bool)
        and 1 <= dias <= ajustes.TOPE_ANTIGUEDAD_DIAS_MAXIMO
    )


def _son_tipos(tipos: object) -> bool:
    """Al menos uno, sin repetir y todos de la lista: sin tipos no hay búsqueda posible."""
    return (
        isinstance(tipos, list)
        and 0 < len(tipos) <= len(ajustes.TIPOS_DE_ESTACION)
        and all(isinstance(t, str) and t in ajustes.TIPOS_DE_ESTACION for t in tipos)
        and len(set(tipos)) == len(tipos)
    )


def _a_json(valor: object) -> object:
    return list(valor) if isinstance(valor, tuple) else valor


def _centesimas(rango: float) -> float:
    """Lo que enseña el campo; hacia abajo, que un rango de más promete saltos que no hay."""
    return math.floor(rango * 100) / 100


def _valores_de_la_nave(estado: Estado) -> dict:
    """None en lo que no se pudo detectar: la interfaz lo pide a mano."""
    nave = estado.nave
    ficha = catalogo.nave(nave.simbolo) if nave else None
    datos = nave.datos if nave else None
    return {
        "capacidad": (nave.capacidad_carga or None) if nave else None,
        "rango": _centesimas(rango_de_comercio(datos)) if datos and nave.capacidad_carga else None,
        "plataforma": ficha.plataforma if ficha else None,
        "creditos": estado.creditos,
        "origen": estado.sistema,
    }


def _centro(conexion: sqlite3.Connection, perfil: Perfil, estado: Estado) -> Posicion:
    """La posición del sistema de origen: la del journal si es donde estás, si no la de la base."""
    if (
        estado.posicion is not None
        and estado.sistema is not None
        and perfil.origen.casefold() == estado.sistema.casefold()
    ):
        return estado.posicion
    sistema = mercado.sistema_por_nombre(conexion, perfil.origen, sin_mayusculas=True)
    if sistema is None:
        raise _Rechazo({"error": ERROR_ORIGEN})
    return sistema.posicion


def _comprobar(parar: threading.Event) -> None:
    """La lectura mira la cancelación por el camino; esto cubre lo que llega después."""
    if parar.is_set():
        raise BusquedaCancelada


def _carga(estado: Estado) -> list[modo_ahora.Carga]:
    """Lo que se puede vender, una vez por mercancía: la de misión y la robada no cuentan."""
    simbolos = dict.fromkeys(m.simbolo for m in estado.carga or () if m.simbolo)
    return [
        modo_ahora.Carga(simbolo, cantidad, precio_de_compra(estado, simbolo))
        for simbolo in simbolos
        if (cantidad := vendibles(estado.carga, simbolo)) > 0
    ]


def _tiempos(conexion: sqlite3.Connection, estado: Estado) -> timing.Tiempos:
    """Los de la nave en la que vas: un perfil guardado de otra nave no cambia cómo juegas."""
    ship_id = estado.nave.ship_id if estado.nave else None
    return timing.cargar(conexion, estado.fid, ship_id)


def _vender(
    articulo: modo_ahora.Carga,
    ventas: dict[str, list[modo_ahora.Venta]],
    nombres: dict,
    tiempos: timing.Tiempos,
) -> dict:
    return {
        "mercancia": salida.mercancia(articulo.mercancia, nombres),
        "cantidad": articulo.cantidad,
        "precio_compra": articulo.precio_compra,
        "destinos": [salida.venta(v, tiempos) for v in ventas.get(articulo.mercancia, ())],
    }
