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
import time
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import MISSING, asdict, fields
from datetime import UTC, datetime
from pathlib import Path

from core import catalogo
from core import nave as modelo_nave
from core.config import ajustes
from core.db import mercado
from core.db.escritor import Escritor, Trabajo, abrir_lectura
from core.state.estado import Estado, precio_de_compra, vendibles
from modules.comercio import (
    alerts,
    en_curso,
    estaciones,
    estimar,
    fijadas,
    paradas,
    perfiles,
    rendimiento,
    salida,
    timing,
)
from modules.comercio.engine import ahora as modo_ahora
from modules.comercio.engine import cadenas, candidatos, descartes, rutas
from modules.comercio.engine.calculo import Curva
from modules.comercio.engine.candidatos import BusquedaCancelada, Posicion
from modules.comercio.engine.perfil import CAMPOS, Perfil, PerfilInvalido, desde_dict
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
ERROR_SIN_COMANDANTE = "sin_comandante"
ERROR_SESION = "sesion_desconocida"
ERROR_REGLA = "regla"
ERROR_SIN_NAVE = "sin_nave"
ERROR_ESTACION = "estacion_desconocida"
ERROR_LIMITE = "limite"

# Un inicio de sesión es una marca ISO del journal; más largo no es una sesión.
LARGO_MAXIMO_DE_SESION = 40

# Lo que se espera al escritor antes de contestar «pendiente»: durante una importación
# de Spansh puede tardar minutos, y el perfil se guarda igual cuando quede libre.
ESPERA_DE_ESCRITURA = 5.0

MODOS = {
    "un_salto": (rutas.un_salto, salida.tramo),
    "bucle": (rutas.bucle, salida.bucle),
    "cadena": (cadenas.cadena, salida.cadena),
    "circuito": (cadenas.circuito, salida.cadena),
}
# Los que buscan con un límite de tiempo y un número de paradas.
MODOS_CON_PARADAS = frozenset({"cadena", "circuito"})
PARADAS_MINIMAS = 3
PARADAS_MAXIMAS = 6

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
        probar_sonido: Callable[[int], None] | None = None,
        cronometro: Callable[[], float] = time.monotonic,
    ) -> None:
        self._estado = estado
        self._cronometro = cronometro
        self._probar_sonido = probar_sonido
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
            "perfil": {campo: _a_json(perfil.get(campo)) for campo in CAMPOS},
            "automaticos": [campo for campo, valor in de_la_nave.items() if valor is not None],
            "limites": {"antiguedad_max_h": tope * 24.0},
            "saldo": estado.creditos,
        }

    def buscar_rutas(self, modo: object, datos: object, paradas: object = None) -> dict:
        if not isinstance(modo, str) or modo not in MODOS:
            return {"error": ERROR_PARAMETRO, "campo": "modo"}
        if not _son_paradas(modo, paradas):
            return {"error": ERROR_PARAMETRO, "campo": "paradas"}
        buscar, convertir = MODOS[modo]
        limite_s = ajustes.limite_de_busqueda(self._config)
        try:
            perfil, estado = self._entrada(datos)
            with self._turno_rutas.empezar() as parar, self._lectura() as conexion:
                centro = _centro(conexion, perfil, estado)
                cargados = candidatos.cargar(conexion, perfil, centro, self._reloj(), parar=parar)
                tiempos = _tiempos(conexion, estado)
                if modo in MODOS_CON_PARADAS:
                    # Cuenta tras la lectura: con mucha antigüedad, leer podría gastarlo todo.
                    limite = cadenas.Limite(self._cronometro() + limite_s, parar, self._cronometro)
                    resultados, cortada = buscar(
                        cargados, perfil, self._curva(), tiempos, paradas, limite
                    )
                else:
                    resultados = buscar(cargados, perfil, self._curva(), tiempos)
                    cortada = False
                nombres = salida.nombres_de_mercancias(conexion)
                _comprobar(parar)
        except _Rechazo as rechazo:
            return rechazo.respuesta
        except BusquedaCancelada:
            return {"cancelada": True}
        return {
            "modo": modo,
            "resultados": [
                _con_detalle(modo, convertir(r, nombres, perfil.horas_sesion, tiempos))
                for r in resultados
            ],
            "corta": len(resultados) < descartes.RESULTADOS_CORTOS,
            "cortada": cortada,
            "limite_s": limite_s,
        }

    def explicar_busqueda(self, datos: object) -> dict:
        """Cuánto quitó cada filtro a una búsqueda que salió corta (DESIGN.md §4.3).

        Va aparte de `buscar_rutas` y la interfaz la pide después: los recuentos releen los
        precios del radio, y dentro de la búsqueda llevaban la respuesta de 2 s a casi 5 s con
        100 ly. Comparte el turno de Rutas, así que una búsqueda nueva la cancela.
        """
        try:
            perfil, estado = self._entrada(datos)
            with self._turno_rutas.empezar() as parar, self._lectura() as conexion:
                centro = _centro(conexion, perfil, estado)
                momento = self._reloj()
                cargados = candidatos.cargar(conexion, perfil, centro, momento, parar=parar)
                explicacion = descartes.contar(conexion, perfil, centro, momento, cargados, parar)
                _comprobar(parar)
        except _Rechazo as rechazo:
            return rechazo.respuesta
        except BusquedaCancelada:
            return {"cancelada": True}
        return {"descartes": explicacion}

    def buscar_estaciones(self, texto: object) -> dict:
        """Dónde está una estación y qué antigüedad tiene su mercado (solo lo guardado)."""
        try:
            limpio = estaciones.validar(texto)
        except PerfilInvalido as error:
            return {"error": ERROR_PARAMETRO, "campo": error.campo}
        try:
            with self._lectura() as conexion:
                return estaciones.buscar(conexion, limpio, self._estado().posicion, self._reloj())
        except _Rechazo as rechazo:
            return rechazo.respuesta

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
            desde_aqui = [
                _con_detalle("un_salto", salida.tramo(t, nombres, perfil.horas_sesion, tiempos))
                for t in tramos
            ]
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
            "limite_busqueda_s": ajustes.limite_de_busqueda(self._config),
            "limite_minimo_s": ajustes.LIMITE_BUSQUEDA_S_MINIMO,
            "limite_maximo_s": ajustes.LIMITE_BUSQUEDA_S_MAXIMO,
        }

    def guardar_ajustes_de_busqueda(
        self, tope_dias: object, tipos: object, limite_s: object
    ) -> dict:
        if not _es_tope(tope_dias):
            return {"error": ERROR_PARAMETRO, "campo": "tope_antiguedad_dias"}
        if not _son_tipos(tipos):
            return {"error": ERROR_PARAMETRO, "campo": "tipos"}
        if not ajustes.es_limite_de_busqueda(limite_s):
            return {"error": ERROR_PARAMETRO, "campo": "limite_busqueda_s"}
        canonicos = tuple(t for t in ajustes.TIPOS_DE_ESTACION if t in tipos)
        if not ajustes.guardar_busqueda(self._config, tope_dias, canonicos, limite_s):
            return {"error": ERROR_NO_GUARDADO}
        return {"ok": True, **self.ajustes_de_busqueda()}

    def rendimiento(self, sesion: object) -> dict:
        """Sesiones y, de la elegida, ganancia real por ruta y mercancía (7.5).

        `sesion` es el inicio de una sesión, `"todo"` o None para la última.
        """
        if sesion is not None and (
            not isinstance(sesion, str) or len(sesion) > LARGO_MAXIMO_DE_SESION
        ):
            return {"error": ERROR_PARAMETRO, "campo": "sesion"}
        estado = self._estado()
        if estado.legacy:
            return {"error": ERROR_LEGACY}
        if not estado.fid:
            return {"error": ERROR_SIN_COMANDANTE}
        ajuste = ajustes.sesiones(self._config)
        try:
            with self._lectura() as conexion:
                return rendimiento.informe(
                    conexion,
                    estado.fid,
                    sesion,
                    ajuste,
                    self._reloj(),
                    ajustes.omitir_sesiones_vacias(self._config),
                    estado.creditos,
                )
        except _Rechazo as rechazo:
            return rechazo.respuesta
        except rendimiento.SesionDesconocida:
            return {"error": ERROR_SESION}

    def ajustes_de_sesiones(self) -> dict:
        horas, por_partida = ajustes.sesiones(self._config)
        return {
            "pausa_horas": horas,
            "por_partida": por_partida,
            "minimo": ajustes.PAUSA_HORAS_MINIMA,
            "maximo": ajustes.PAUSA_HORAS_MAXIMA,
        }

    def guardar_ajustes_de_sesiones(self, horas: object, por_partida: object) -> dict:
        if not ajustes.es_pausa_de_sesion(horas):
            return {"error": ERROR_PARAMETRO, "campo": "pausa_horas"}
        if not isinstance(por_partida, bool):
            return {"error": ERROR_PARAMETRO, "campo": "por_partida"}
        if not ajustes.guardar_sesiones(self._config, horas, por_partida):
            return {"error": ERROR_NO_GUARDADO}
        return {"ok": True, **self.ajustes_de_sesiones()}

    def guardar_omitir_sesiones_vacias(self, omitir: object) -> dict:
        if not isinstance(omitir, bool):
            return {"error": ERROR_PARAMETRO, "campo": "omitir_vacias"}
        if not ajustes.guardar_omitir_sesiones_vacias(self._config, omitir):
            return {"error": ERROR_NO_GUARDADO}
        return {"ok": True, "omitir_vacias": omitir}

    def reglas_de_alertas(self) -> dict:
        try:
            with self._lectura() as conexion:
                reglas = alerts.leer_reglas(conexion)
        except _Rechazo as rechazo:
            return rechazo.respuesta
        return {"reglas": asdict(reglas), "limites": alerts.LIMITES}

    def guardar_reglas_de_alertas(self, datos: object) -> dict:
        try:
            reglas = alerts.reglas_desde_dict(datos)
        except alerts.ReglaInvalida as error:
            return {"error": ERROR_REGLA, "campo": error.campo}
        respuesta = self._escribir(lambda conexion: alerts.guardar_reglas(conexion, reglas))
        return {**respuesta, "reglas": asdict(reglas)} if respuesta.get("ok") else respuesta

    def avisos(self, desde_id: object) -> dict:
        """Los avisos recientes; con `desde_id`, solo los que llegaron después (7.4)."""
        if desde_id is not None and (
            not isinstance(desde_id, int) or isinstance(desde_id, bool) or desde_id < 0
        ):
            return {"error": ERROR_PARAMETRO, "campo": "desde_id"}
        try:
            with self._lectura() as conexion:
                ultimo = alerts.ultimo_id(conexion)
                lista = alerts.avisos(conexion, desde_id, ultimo)
        except _Rechazo as rechazo:
            return rechazo.respuesta
        return {"avisos": lista, "ultimo": ultimo}

    def rutas_fijadas(self) -> dict:
        """Las rutas fijadas y la ruta en curso, recalculadas con lo de hoy (bloque 5)."""
        estado = self._estado()
        try:
            perfil = self._perfil_de_la_nave(estado)
            with self._lectura() as conexion:
                guardadas = fijadas.listar(conexion)
                pausa = ajustes.sesiones(self._config)[0]
                actual = (
                    en_curso.deducir(en_curso.leer(conexion, estado.fid), self._reloj(), pausa)
                    if estado.fid
                    else None
                )
                paradas_de = [p for r in guardadas for p in r["paradas"]]
                paradas_de += list(actual.paradas) if actual else []
                contexto = self._contexto_de_ruta(
                    conexion, {p["market_id"] for p in paradas_de}, perfil, estado
                )
        except _Rechazo as rechazo:
            return rechazo.respuesta
        claves = {r["clave"]: r["id"] for r in guardadas}
        return {
            "fijadas": [
                {
                    "id": r["id"],
                    "creada": r["creada"],
                    "cerrada": r["cerrada"],
                    **estimar.estimar(contexto, r),
                }
                for r in guardadas
            ],
            "en_curso": _en_curso_con_estimacion(actual, contexto, claves) if actual else None,
        }

    def estimar_ruta(self, datos: object) -> dict:
        """Recalcula una ruta de estaciones elegida a mano, sin guardarla (7.3)."""
        try:
            pedida = fijadas.validar(datos)
        except fijadas.RutaInvalida as error:
            return {"error": ERROR_PARAMETRO, "campo": error.campo}
        estado = self._estado()
        try:
            perfil = self._perfil_de_la_nave(estado)
            with self._lectura() as conexion:
                ruta = self._completar(conexion, pedida)
                contexto = self._contexto_de_ruta(
                    conexion, {p["market_id"] for p in ruta["paradas"]}, perfil, estado
                )
        except _Rechazo as rechazo:
            return rechazo.respuesta
        return {"cerrada": ruta["cerrada"], **estimar.estimar(contexto, ruta)}

    def fijar_ruta(self, datos: object) -> dict:
        try:
            pedida = fijadas.validar(datos)
        except fijadas.RutaInvalida as error:
            return {"error": ERROR_PARAMETRO, "campo": error.campo}
        try:
            with self._lectura() as conexion:
                ruta = self._completar(conexion, pedida)
        except _Rechazo as rechazo:
            return rechazo.respuesta
        creada = self._reloj().strftime("%Y-%m-%dT%H:%M:%SZ")
        return self._escribir(
            lambda conexion: fijadas.guardar(conexion, ruta, creada), _respuesta_de_fijar
        )

    def desfijar_ruta(self, id_: object) -> dict:
        if isinstance(id_, bool) or not isinstance(id_, int) or id_ <= 0:
            return {"error": ERROR_PARAMETRO, "campo": "id"}
        return self._escribir(lambda conexion: fijadas.borrar(conexion, id_))

    def ajustes_de_ruta_en_curso(self) -> dict:
        aviso, margen, portapapeles = ajustes.ruta_en_curso(self._config)
        return {
            "aviso_mejor": aviso,
            "margen_pct": margen,
            "portapapeles": portapapeles,
            "margen_minimo": ajustes.MARGEN_MEJOR_MINIMO,
            "margen_maximo": ajustes.MARGEN_MEJOR_MAXIMO,
        }

    def guardar_ajustes_de_ruta_en_curso(
        self, aviso: object, margen: object, portapapeles: object
    ) -> dict:
        if not isinstance(aviso, bool):
            return {"error": ERROR_PARAMETRO, "campo": "aviso_mejor"}
        if not ajustes.es_margen_de_ruta(margen):
            return {"error": ERROR_PARAMETRO, "campo": "margen_pct"}
        if not isinstance(portapapeles, bool):
            return {"error": ERROR_PARAMETRO, "campo": "portapapeles"}
        if not ajustes.guardar_ruta_en_curso(self._config, aviso, margen, portapapeles):
            return {"error": ERROR_NO_GUARDADO}
        return {"ok": True, **self.ajustes_de_ruta_en_curso()}

    def ajustes_de_sonido(self) -> dict:
        activado, volumen = ajustes.sonido(self._config)
        return {"activado": activado, "volumen": volumen}

    def guardar_ajustes_de_sonido(self, activado: object, volumen: object) -> dict:
        if not isinstance(activado, bool):
            return {"error": ERROR_PARAMETRO, "campo": "activado"}
        if not ajustes.es_volumen(volumen):
            return {"error": ERROR_PARAMETRO, "campo": "volumen"}
        if not ajustes.guardar_sonido(self._config, activado, volumen):
            return {"error": ERROR_NO_GUARDADO}
        return {"ok": True, **self.ajustes_de_sonido()}

    def probar_sonido(self, volumen: object) -> dict:
        if not ajustes.es_volumen(volumen):
            return {"error": ERROR_PARAMETRO, "campo": "volumen"}
        if self._probar_sonido is None:
            return {"error": "no_disponible"}
        self._probar_sonido(volumen)
        return {"ok": True}

    def _perfil_de_la_nave(self, estado: Estado) -> Perfil:
        """El de tu nave sin filtros (bloque 5); sin nave detectada, no hay con qué estimar."""
        if estado.legacy:
            raise _Rechazo({"error": ERROR_LEGACY})
        tope = ajustes.tope_de_antiguedad_dias(self._config)
        try:
            return estimar.perfil_de_la_nave(
                self.perfil_inicial()["perfil"], tope, estado.sistema, estado.creditos
            )
        except PerfilInvalido:
            raise _Rechazo({"error": ERROR_SIN_NAVE}) from None

    def _contexto_de_ruta(
        self,
        conexion: sqlite3.Connection,
        market_ids: set[int],
        perfil: Perfil,
        estado: Estado,
    ) -> estimar.Contexto:
        return estimar.leer_contexto(
            conexion,
            market_ids,
            self._reloj(),
            estado.posicion,
            perfil,
            self._curva(),
            _tiempos(conexion, estado),
        )

    @staticmethod
    def _completar(conexion: sqlite3.Connection, pedida: fijadas.RutaPedida) -> dict:
        try:
            return fijadas.completar(conexion, pedida)
        except fijadas.EstacionDesconocida as error:
            raise _Rechazo(
                {"error": ERROR_ESTACION, "campo": f"paradas.{error.posicion}"}
            ) from None

    def _entrada(self, datos: object) -> tuple[Perfil, Estado]:
        estado = self._estado()
        try:
            perfil = desde_dict(
                datos, ajustes.tope_de_antiguedad_dias(self._config), saldo=estado.creditos
            )
        except PerfilInvalido as error:
            raise _Rechazo({"error": ERROR_PERFIL, "campo": error.campo}) from None
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

    def _escribir(
        self, trabajo: Trabajo, interpretar: Callable[[object], dict] | None = None
    ) -> dict:
        """Espera al escritor un rato; si sigue ocupado, el trabajo queda en su cola.

        `interpretar` convierte lo que devolvió el trabajo en la respuesta a la interfaz.
        """
        if self._escritor is None:
            return {"error": ERROR_SIN_BASE}
        hecho = threading.Event()
        # Se sustituye el diccionario entero: lo que se lee tras la espera nunca está a medias.
        respuesta = {"valor": {"pendiente": True}}

        def al_terminar(resultado: object) -> None:
            contestacion = interpretar(resultado) if interpretar else {"ok": True}
            respuesta["valor"] = {"pendiente": False, **contestacion}
            hecho.set()

        def al_fallar(_: Exception) -> None:
            respuesta["valor"] = {"pendiente": False, "error": ERROR_NO_GUARDADO}
            hecho.set()

        self._escritor.encolar(trabajo, al_terminar, al_fallar)
        hecho.wait(ESPERA_DE_ESCRITURA)
        return dict(respuesta["valor"])


def _respuesta_de_fijar(resultado: object) -> dict:
    estado, id_ = resultado
    if estado == fijadas.ESTADO_NUEVA:
        return {"ok": True, "id": id_}
    if estado == fijadas.ESTADO_YA_FIJADA:
        return {"ya_fijada": True, "id": id_}
    return {"error": ERROR_LIMITE}


def _en_curso_con_estimacion(
    actual: en_curso.RutaEnCurso, contexto: estimar.Contexto, claves: dict[str, int]
) -> dict:
    """La ruta en curso con lo que se estima hoy y, si ya está fijada, su id."""
    ruta = {"cerrada": actual.cerrada, "paradas": list(actual.paradas)}
    return {
        **actual.a_dict(),
        "estimacion": estimar.estimar(contexto, ruta),
        "id": claves.get(actual.clave),
    }


def _son_paradas(modo: str, paradas: object) -> bool:
    """Los modos con paradas piden de 3 a 6; los demás, ninguna."""
    if modo not in MODOS_CON_PARADAS:
        return paradas is None
    if isinstance(paradas, bool) or not isinstance(paradas, int):
        return False
    return PARADAS_MINIMAS <= paradas <= PARADAS_MAXIMAS


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
        "rango": (
            _centesimas(modelo_nave.rango_de_comercio(datos))
            if datos and nave.capacidad_carga
            else None
        ),
        "plataforma": ficha.plataforma if ficha else None,
        "stock_minimo": (nave.capacidad_carga or None) if nave else None,
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


def _con_detalle(modo: str, resultado: dict) -> dict:
    return {**resultado, "detalle": paradas.detalle(modo, resultado)}


def _vender(
    articulo: modo_ahora.Carga,
    ventas: dict[str, list[modo_ahora.Venta]],
    nombres: dict,
    tiempos: timing.Tiempos,
) -> dict:
    mercancia = salida.mercancia(articulo.mercancia, nombres)
    return {
        "mercancia": mercancia,
        "cantidad": articulo.cantidad,
        "precio_compra": articulo.precio_compra,
        "destinos": [
            _con_detalle("venta", {**salida.venta(v, tiempos), "mercancia": mercancia})
            for v in ventas.get(articulo.mercancia, ())
        ],
    }
