"""Alertas (sección 7.4): umbrales, evaluación y avisos sin repetir.

Cuando entra un mercado nuevo (propio o de EDDN) o atracas, se buscan las rutas de un
salto y los bucles A↔B en los que esa estación es compra o venta, con el perfil de tu
nave y la distancia y antigüedad de las reglas, desde donde estás. Las que pasan los
umbrales avisan, salvo que la misma ruta haya avisado hace menos de `repetir_min`
minutos y no haya mejorado más de `mejora_pct` (`docs/decisiones.md`, «Fase 7»).

El aviso del bus llega en el hilo escritor o en el del núcleo, así que el manejador
solo encola el `MarketID` (E-06): el trabajo lo hace un hilo propio, que agrupa los
mercados que llegan seguidos en una sola evaluación.
"""

from __future__ import annotations

import json
import logging
import math
import queue
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core import events
from core.config import ajustes
from core.db.escritor import Escritor, abrir_lectura
from core.state.estado import Estacion, Estado
from modules.comercio import salida, timing
from modules.comercio.engine import candidatos, rutas
from modules.comercio.engine.calculo import Curva
from modules.comercio.engine.perfil import PerfilInvalido, desde_dict

registro = logging.getLogger("luna.alertas")

MODO_UN_SALTO = "un_salto"
MODO_BUCLE = "bucle"
# Los mercados que llegan en este rato se evalúan juntos: EDDN manda más de uno por segundo.
AGRUPAR_SEGUNDOS = 2.0
# Una evaluación avisa como mucho de estas rutas, las de más ganancia por hora.
AVISOS_POR_EVALUACION = 5
AVISOS_RECIENTES = 50


class ReglaInvalida(ValueError):
    """`campo` dice qué umbral rechazar en la interfaz."""

    def __init__(self, campo: str) -> None:
        super().__init__(campo)
        self.campo = campo


@dataclass(frozen=True, slots=True)
class Reglas:
    activadas: bool = False
    ganancia_tonelada_min: int = 10_000
    ganancia_hora_min: int = 50_000_000
    distancia_max_ly: float = 30.0
    antiguedad_max_h: float = 1.0
    repetir_min: float = 30.0
    mejora_pct: float = 10.0


# (mínimo, máximo) de cada umbral numérico; los enteros son los de créditos.
LIMITES = {
    "ganancia_tonelada_min": (0, 1_000_000),
    "ganancia_hora_min": (0, 100_000_000_000),
    "distancia_max_ly": (0.01, 1_000.0),
    "antiguedad_max_h": (0.01, ajustes.TOPE_ANTIGUEDAD_DIAS_MAXIMO * 24.0),
    "repetir_min": (1.0, 24 * 60.0),
    "mejora_pct": (0.0, 1_000.0),
}
ENTEROS = {"ganancia_tonelada_min", "ganancia_hora_min"}


def reglas_desde_dict(datos: object) -> Reglas:
    """Valida lo que manda la interfaz: un campo de más, de menos o fuera de rango la rechaza."""
    if not isinstance(datos, dict):
        raise ReglaInvalida("reglas")
    nombres = {campo.name for campo in fields(Reglas)}
    sobrantes, faltantes = set(datos) - nombres, nombres - set(datos)
    if sobrantes or faltantes:
        raise ReglaInvalida(sorted(sobrantes or faltantes)[0])
    if not isinstance(datos["activadas"], bool):
        raise ReglaInvalida("activadas")
    valores = {campo: _umbral(datos, campo) for campo in LIMITES}
    return Reglas(activadas=datos["activadas"], **valores)


def _umbral(datos: dict, campo: str) -> float | int:
    valor = datos[campo]
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ReglaInvalida(campo)
    if isinstance(valor, float) and not math.isfinite(valor):
        raise ReglaInvalida(campo)
    minimo, maximo = LIMITES[campo]
    if not minimo <= valor <= maximo:
        raise ReglaInvalida(campo)
    if campo in ENTEROS:
        if isinstance(valor, float) and not valor.is_integer():
            raise ReglaInvalida(campo)
        return int(valor)
    return float(valor)


def leer_reglas(conexion: sqlite3.Connection) -> Reglas:
    fila = conexion.execute(
        "SELECT activadas, ganancia_tonelada_min, ganancia_hora_min, distancia_max_ly, "
        "antiguedad_max_h, repetir_min, mejora_pct FROM alert_rules WHERE id = 1"
    ).fetchone()
    if fila is None:
        return Reglas()
    return Reglas(bool(fila[0]), *fila[1:])


def guardar_reglas(conexion: sqlite3.Connection, reglas: Reglas) -> None:
    conexion.execute(
        "INSERT OR REPLACE INTO alert_rules (id, activadas, ganancia_tonelada_min, "
        "ganancia_hora_min, distancia_max_ly, antiguedad_max_h, repetir_min, mejora_pct) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
        tuple(asdict(reglas).values()),
    )


@dataclass(frozen=True, slots=True)
class Aviso:
    clave: str
    modo: str
    momento: str
    ganancia_hora: float
    # La ruta tal como la enseña Rutas (`salida.tramo` o `salida.bucle`).
    ruta: dict


def guardar_aviso(conexion: sqlite3.Connection, aviso: Aviso) -> int:
    cursor = conexion.execute(
        "INSERT INTO alert_log (clave, momento, modo, ganancia_hora, ruta) "
        "VALUES (?, ?, ?, ?, ?)",
        (aviso.clave, aviso.momento, aviso.modo, aviso.ganancia_hora, json.dumps(aviso.ruta)),
    )
    return cursor.lastrowid


def avisos(
    conexion: sqlite3.Connection, desde_id: int | None = None, hasta_id: int | None = None
) -> list[dict]:
    """Los últimos avisos, del más nuevo al más viejo, con id en (`desde_id`, `hasta_id`].

    `hasta_id` acota la lista a un `ultimo_id` leído antes: un aviso que llegue entre
    las dos lecturas queda para la siguiente pregunta en vez de perderse.
    """
    filas = conexion.execute(
        "SELECT id, momento, modo, ganancia_hora, ruta FROM alert_log "
        "WHERE id > ? AND id <= ? ORDER BY id DESC LIMIT ?",
        (desde_id or 0, hasta_id if hasta_id is not None else 2**63 - 1, AVISOS_RECIENTES),
    )
    return [
        {"id": i, "momento": m, "modo": modo, "ganancia_hora": g, "ruta": json.loads(r)}
        for i, m, modo, g, r in filas
    ]


def ultimo_id(conexion: sqlite3.Connection) -> int:
    return conexion.execute("SELECT COALESCE(MAX(id), 0) FROM alert_log").fetchone()[0]


def pasa(ruta: rutas.Tramo | rutas.Bucle, reglas: Reglas) -> bool:
    return (
        ruta.ganancia_tonelada >= reglas.ganancia_tonelada_min
        and ruta.ganancia_hora >= reglas.ganancia_hora_min
    )


def clave(modo: str, ruta: rutas.Tramo | rutas.Bucle) -> str:
    """La misma ruta da la misma clave aunque cambien precios o tiempos."""
    if modo == MODO_BUCLE:
        a, b = ruta.ida.compra.estacion.market_id, ruta.ida.venta.estacion.market_id
        return f"{MODO_BUCLE}:{min(a, b)}:{max(a, b)}"
    compra, venta = ruta.compra, ruta.venta
    puntas = f"{compra.estacion.market_id}:{venta.estacion.market_id}"
    return f"{MODO_UN_SALTO}:{puntas}:{compra.mercancia}"


class Repeticiones:
    """El último aviso de cada ruta, para no repetirlo (7.4). Solo lo usa el hilo de alertas."""

    def __init__(self) -> None:
        self._ultimos: dict[str, tuple[datetime, float]] = {}

    def anotar(self, clave_: str, momento: datetime, ganancia_hora: float) -> None:
        self._ultimos[clave_] = (momento, ganancia_hora)

    def avisa(self, clave_: str, ganancia_hora: float, ahora: datetime, reglas: Reglas) -> bool:
        anterior = self._ultimos.get(clave_)
        if anterior is None:
            return True
        momento, ganancia = anterior
        if ahora - momento >= timedelta(minutes=reglas.repetir_min):
            return True
        return ganancia_hora > ganancia * (1 + reglas.mejora_pct / 100)

    def cargar(self, conexion: sqlite3.Connection, desde: datetime) -> None:
        """Al arrancar: lo avisado en la ventana de repetición sigue contando."""
        filas = conexion.execute(
            "SELECT clave, momento, ganancia_hora FROM alert_log WHERE momento >= ? ORDER BY id",
            (_marca(desde),),
        )
        for clave_, momento, ganancia in filas:
            self.anotar(clave_, datetime.fromisoformat(momento), ganancia)


def rutas_con(
    cargados: candidatos.Candidatos,
    market_ids: set[int],
    perfil,
    curva: Curva,
    tiempos: timing.Tiempos,
    reglas: Reglas,
) -> dict[str, tuple[str, rutas.Tramo | rutas.Bucle]]:
    """Las rutas con alguno de los mercados que pasan los umbrales, una por clave."""
    encontradas: dict[str, tuple[str, rutas.Tramo | rutas.Bucle]] = {}
    for market_id in market_ids:
        if market_id not in cargados.estaciones:
            continue  # fuera de la distancia de las reglas, o sin precios recientes
        tramos = rutas.tramos_con(cargados, market_id, perfil, curva, tiempos)
        bucles = rutas.bucles_con(cargados, market_id, perfil, curva, tiempos)
        halladas = [*((MODO_UN_SALTO, t) for t in tramos), *((MODO_BUCLE, b) for b in bucles)]
        for modo, ruta in halladas:
            if not pasa(ruta, reglas):
                continue
            clave_ = clave(modo, ruta)
            anterior = encontradas.get(clave_)
            if anterior is None or ruta.ganancia_hora > anterior[1].ganancia_hora:
                encontradas[clave_] = (modo, ruta)
    return encontradas


def _marca(momento: datetime) -> str:
    return momento.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


Reloj = Callable[[], datetime]


class Alertas:
    def __init__(
        self,
        bus: events.Bus,
        estado: Callable[[], Estado],
        perfil: Callable[[], dict],
        config: Path,
        base: Path,
        escritor: Escritor,
        sonar: Callable[[], None],
        reloj: Reloj = lambda: datetime.now(UTC),
    ) -> None:
        self._bus = bus
        self._estado = estado
        self._perfil = perfil
        self._config = config
        self._base = base
        self._escritor = escritor
        self._sonar = sonar
        self._reloj = reloj
        self._cola: queue.Queue[int | None] = queue.Queue()
        self._repeticiones = Repeticiones()
        self._motivo_sin_perfil: str | None = None
        self._hilo = threading.Thread(target=self._bucle, name="alertas", daemon=True)

    def iniciar(self) -> None:
        self._bus.suscribir(events.MERCADO_ACTUALIZADO, self._al_mercado)
        self._bus.suscribir(events.ATRACADO, self._al_atracar)
        self._hilo.start()

    def detener(self) -> None:
        if not self._hilo.is_alive():
            return
        self._cola.put(None)
        self._hilo.join(5)

    def _al_mercado(self, market_id: object) -> None:
        if isinstance(market_id, int):
            self._cola.put(market_id)

    def _al_atracar(self, estacion: object) -> None:
        # Al atracar cambia desde dónde se mide la distancia: se mira esa estación.
        if isinstance(estacion, Estacion) and isinstance(estacion.market_id, int):
            self._cola.put(estacion.market_id)

    def _bucle(self) -> None:
        try:
            with closing(abrir_lectura(self._base)) as conexion:
                ventana = timedelta(minutes=leer_reglas(conexion).repetir_min)
                self._repeticiones.cargar(conexion, self._reloj() - ventana)
        except sqlite3.Error:
            registro.exception("no se pudieron leer los avisos anteriores")
        while True:
            pendientes = self._esperar_mercados()
            if pendientes is None:
                return
            try:
                self.evaluar(pendientes)
            except Exception:  # noqa: BLE001 - una evaluación rota no debe parar las alertas
                registro.exception("fallo al evaluar alertas")

    def _esperar_mercados(self) -> set[int] | None:
        """Los mercados que llegan seguidos, juntos; None al detener."""
        primero = self._cola.get()
        if primero is None:
            return None
        pendientes = {primero}
        limite = time.monotonic() + AGRUPAR_SEGUNDOS
        while (falta := limite - time.monotonic()) > 0:
            try:
                siguiente = self._cola.get(timeout=falta)
            except queue.Empty:
                break
            if siguiente is None:
                self._cola.put(None)
                break
            pendientes.add(siguiente)
        return pendientes

    def evaluar(self, market_ids: set[int]) -> list[Aviso]:
        """Evalúa ahora, en el hilo que llama; lo usa el hilo propio y las pruebas."""
        estado = self._estado()
        if estado.legacy or estado.posicion is None or not estado.fid:
            return []
        with closing(abrir_lectura(self._base)) as conexion:
            reglas = leer_reglas(conexion)
            if not reglas.activadas:
                return []
            perfil = self._perfil_de_las_reglas(estado, reglas)
            if perfil is None:
                return []
            ahora = self._reloj()
            cargados = candidatos.cargar(conexion, perfil, estado.posicion, ahora)
            ship_id = estado.nave.ship_id if estado.nave else None
            tiempos = timing.cargar(conexion, estado.fid, ship_id)
            curva = Curva(*ajustes.curva_de_confianza(self._config))
            encontradas = rutas_con(cargados, market_ids, perfil, curva, tiempos, reglas)
            nombres = salida.nombres_de_mercancias(conexion)
        nuevos = self._nuevos(encontradas, ahora, reglas, nombres, perfil.horas_sesion, tiempos)
        for aviso in nuevos:
            self._escritor.encolar(lambda c, aviso=aviso: guardar_aviso(c, aviso))
        if nuevos:
            self._sonar()
        return nuevos

    def _perfil_de_las_reglas(self, estado: Estado, reglas: Reglas):
        """El de tu nave, desde donde estás, con la distancia y la antigüedad de las reglas."""
        tope = ajustes.tope_de_antiguedad_dias(self._config)
        datos = {
            **self._perfil(),
            "origen": estado.sistema,
            "distancia_max_ly": reglas.distancia_max_ly,
            "antiguedad_max_h": min(reglas.antiguedad_max_h, tope * 24.0),
        }
        try:
            perfil = desde_dict(datos, tope)
        except PerfilInvalido as error:
            # Con EDDN llega una tanda cada 2 s: se anota cuando cambia el motivo, no cada vez.
            if error.campo != self._motivo_sin_perfil:
                registro.info("sin alertas: el perfil de la nave no sirve (%s)", error.campo)
                self._motivo_sin_perfil = error.campo
            return None
        self._motivo_sin_perfil = None
        return perfil

    def _nuevos(self, encontradas, ahora, reglas, nombres, horas_sesion, tiempos) -> list[Aviso]:
        candidatas = sorted(encontradas.items(), key=lambda e: e[1][1].ganancia_hora, reverse=True)
        nuevos = []
        for clave_, (modo, ruta) in candidatas:
            if len(nuevos) == AVISOS_POR_EVALUACION:
                break
            if not self._repeticiones.avisa(clave_, ruta.ganancia_hora, ahora, reglas):
                continue
            self._repeticiones.anotar(clave_, ahora, ruta.ganancia_hora)
            convertir = salida.bucle if modo == MODO_BUCLE else salida.tramo
            datos = convertir(ruta, nombres, horas_sesion, tiempos)
            nuevos.append(Aviso(clave_, modo, _marca(ahora), ruta.ganancia_hora, datos))
        return nuevos

