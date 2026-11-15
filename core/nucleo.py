"""El núcleo: sigue el journal, mantiene el estado y avisa a quien se suscriba.

Es lo único que lee el journal (sección 3). Un hilo propio hace todo el trabajo;
los demás hilos solo piden la última instantánea del estado, que es inmutable.
Lo que hay que guardar en la base de datos va al hilo escritor por su cola.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from core import catalogo, events
from core import estacion as clasificacion
from core import nave as modelo_nave
from core.config import ajustes
from core.db import comandante, mercado
from core.db.escritor import Escritor
from core.esfera import Esfera, EsferaViva
from core.journal import archivos, carpeta, comercio, lector, sesiones, tiempos
from core.journal import mercado as mercado_del_juego
from core.state import vista
from core.state.estado import Estado, NaveActual, aplicar

registro = logging.getLogger("luna.nucleo")

INTERVALO = 0.5
# Buscar la carpeta cuesta una consulta a Windows: no hace falta cada medio segundo.
PASOS_ENTRE_BUSQUEDAS = 10


@dataclass
class _Lote:
    """Lo que un lote de eventos deja para guardar, en un trabajo del escritor por tipo."""

    comandantes: dict[str, tuple[str, str]] = field(default_factory=dict)
    naves: dict[tuple[str, int], tuple[NaveActual, str]] = field(default_factory=dict)
    muestras: list[comandante.MuestraDeTiempo] = field(default_factory=list)
    operaciones: list[tuple[str, int | None, comercio.Operacion]] = field(default_factory=list)
    tramos: list[tuple[str, comercio.Tramo]] = field(default_factory=list)
    bloques: list[sesiones.Bloque] = field(default_factory=list)


@dataclass
class _Marcas:
    cargo: tuple[int, int] | None = None
    status: tuple[int, int] | None = None
    mercado: tuple[int, int] | None = None


class Nucleo:
    def __init__(
        self,
        config: Path,
        bus: events.Bus,
        escritor: Escritor | None,
        esfera: EsferaViva | None = None,
    ) -> None:
        self._config = config
        self._bus = bus
        self._escritor = escritor
        self._esfera = esfera or EsferaViva(ajustes.esfera(config))
        self._estado = Estado()
        self._candado = threading.Lock()
        self._parar = threading.Event()
        self._reiniciar = threading.Event()
        self._hilo = threading.Thread(target=self._bucle, name="nucleo", daemon=True)
        self._carpeta: Path | None = None
        self._seguidor: lector.Seguidor | None = None
        self._marcas = _Marcas()
        self._pasos_sin_carpeta = PASOS_ENTRE_BUSQUEDAS
        # Solo los toca el hilo del núcleo.
        self._cronometro = tiempos.Cronometro()
        self._libro = comercio.Libro()
        self._actividad = sesiones.Actividad()
        self._bloque_guardado: sesiones.Bloque | None = None

    def iniciar(self) -> None:
        if self._escritor is not None:
            self._escritor.encolar(lambda c: mercado.sembrar_mercancias(c, catalogo.mercancias()))
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
        if self._hilo.is_alive():
            self._hilo.join(5)

    def estado(self) -> Estado:
        with self._candado:
            return self._estado

    def estado_del_journal(self) -> str:
        if self._carpeta is None:
            return vista.JOURNAL_SIN_CARPETA
        if self.estado().ultimo_evento is None:
            return vista.JOURNAL_SIN_ARCHIVOS
        return vista.JOURNAL_LEYENDO

    def reiniciar_journal(self) -> None:
        """Vuelve a resolver la carpeta y reconstruir el estado desde cero."""
        self._reiniciar.set()

    def _bucle(self) -> None:
        while not self._parar.is_set():
            try:
                self._paso()
            except Exception:  # noqa: BLE001 - el núcleo no puede morir en silencio
                registro.exception("fallo un paso del nucleo")
            self._parar.wait(INTERVALO)

    def _paso(self) -> None:
        if self._reiniciar.is_set():
            self._reiniciar.clear()
            self._olvidar_journal()
        if self._seguidor is None:
            self._buscar_journal()
        else:
            self._seguir()

    def _olvidar_journal(self) -> None:
        """Con otra carpeta, lo que se sabía de la anterior ya no vale."""
        self._seguidor = None
        self._carpeta = None
        self._pasos_sin_carpeta = PASOS_ENTRE_BUSQUEDAS
        with self._candado:
            self._estado = Estado()

    def _buscar_journal(self) -> None:
        self._pasos_sin_carpeta += 1
        if self._pasos_sin_carpeta < PASOS_ENTRE_BUSQUEDAS:
            return
        self._pasos_sin_carpeta = 0
        encontrada = carpeta.resolver(ajustes.carpeta_journal(self._config))
        if encontrada is None:
            self._carpeta = None
            return
        self._carpeta = encontrada
        self._seguidor = lector.Seguidor(encontrada)
        self._reconstruir()

    def _reconstruir(self) -> None:
        lectura = self._seguidor.iniciar(ajustes.dias_journal(self._config))
        self._cronometro = tiempos.Cronometro()
        self._libro = comercio.Libro()
        self._actividad = sesiones.Actividad()
        self._bloque_guardado = None
        estado = self._plegar(Estado(), lectura.eventos)
        self._marcas = _Marcas()
        estado = self._con_archivos(estado)
        self._guardar_mercado_abierto(estado)
        self._publicar(estado, anterior=None)

    def _seguir(self) -> None:
        anterior = self.estado()
        estado = self._plegar(anterior, self._seguidor.nuevos().eventos)
        estado = self._con_archivos(estado)
        self._guardar_mercado_abierto(estado)
        if estado != anterior:
            self._publicar(estado, anterior)

    def _plegar(self, estado: Estado, eventos: list[dict]) -> Estado:
        """Aplica los eventos y guarda en la base lo que cambió, una vez por lote."""
        if not eventos:
            return estado
        lote = _Lote()
        for evento in eventos:
            estado = aplicar(estado, evento)
            if estado.fid and estado.comandante:
                lote.comandantes[estado.fid] = (estado.comandante, estado.ultimo_evento or "")
            if evento.get("event") == "Loadout" and _es_guardable(estado):
                clave = (estado.fid, estado.nave.ship_id)
                lote.naves[clave] = (estado.nave, estado.ultimo_evento or "")
            lote.muestras += self._medir(estado, evento)
            self._anotar_comercio(estado, evento, lote)
        if self._actividad.bloque not in (None, self._bloque_guardado):
            lote.bloques.append(self._actividad.bloque)
            self._bloque_guardado = self._actividad.bloque
        self._guardar(lote)
        return estado

    def _anotar_comercio(self, estado: Estado, evento: dict, lote: _Lote) -> None:
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
        if not nuevas or not _es_guardable(estado):
            return []
        return [
            comandante.MuestraDeTiempo(
                estado.fid, estado.nave.ship_id, m.tramo, m.fin, m.segundos, m.distancia_ls
            )
            for m in nuevas
        ]

    def _con_archivos(self, estado: Estado) -> Estado:
        """Cargo.json y Status.json: se releen solo cuando el juego los reescribe."""
        for nombre, atributo in ((archivos.CARGO, "cargo"), (archivos.STATUS, "status")):
            marca = archivos.marca(self._carpeta, nombre)
            if marca is None or marca == getattr(self._marcas, atributo):
                continue
            contenido = archivos.leer(self._carpeta, nombre)
            if contenido is None:
                continue  # a medio escribir: se reintenta en la siguiente pasada
            setattr(self._marcas, atributo, marca)
            estado = aplicar(estado, contenido)
        return estado

    def _guardar_mercado_abierto(self, estado: Estado) -> None:
        """Market.json solo vale si es el de la estación donde estás atracado."""
        if self._escritor is None:
            return
        marca = archivos.marca(self._carpeta, archivos.MERCADO)
        if marca is None or marca == self._marcas.mercado:
            return
        abierto = mercado_del_juego.leer(self._carpeta)
        if abierto is None:
            return  # a medio escribir: se reintenta en la siguiente pasada
        self._marcas.mercado = marca
        if estado.estacion is None or estado.estacion.market_id != abierto.market_id:
            return
        propio = _mercado_propio(estado, abierto, self._esfera)
        market_id = abierto.market_id
        self._escritor.encolar(
            lambda c: mercado.guardar_propio(c, propio),
            lambda guardado: guardado and self._bus.publicar(events.MERCADO_ACTUALIZADO, market_id),
        )

    def _guardar(self, lote: _Lote) -> None:
        """Cada comandante visto se da de alta antes que lo suyo (clave foránea)."""
        if self._escritor is None:
            return
        for fid, (nombre, visto) in lote.comandantes.items():
            self._escritor.encolar(
                lambda c, fid=fid, nombre=nombre, visto=visto: comandante.registrar_comandante(
                    c, fid, nombre, visto
                )
            )
        for (dueno, ship_id), (actual, fecha) in lote.naves.items():
            ficha = _ficha(dueno, ship_id, actual, fecha)
            self._escritor.encolar(lambda c, ficha=ficha: comandante.guardar_nave(c, ficha))
        if lote.muestras:
            self._escritor.encolar(lambda c: comandante.guardar_muestras(c, lote.muestras))
        if lote.operaciones:
            self._escritor.encolar(lambda c: comandante.guardar_operaciones(c, lote.operaciones))
        if lote.tramos:
            self._escritor.encolar(lambda c: comandante.guardar_tramos(c, lote.tramos))
        if lote.bloques:
            self._escritor.encolar(lambda c: comandante.guardar_bloques(c, lote.bloques))

    def _publicar(self, estado: Estado, anterior: Estado | None) -> None:
        with self._candado:
            self._estado = estado
        if anterior is not None:
            self._avisar_de_cambios(anterior, estado)
        self._bus.publicar(events.ESTADO_ACTUALIZADO, estado)

    def _avisar_de_cambios(self, antes: Estado, ahora: Estado) -> None:
        if _identidad(antes.nave) != _identidad(ahora.nave):
            self._bus.publicar(events.NAVE_CAMBIADA, ahora.nave)
        if antes.estacion != ahora.estacion:
            tipo = events.ATRACADO if ahora.estacion else events.DESATRACADO
            self._bus.publicar(tipo, ahora.estacion)
        if antes.carga != ahora.carga:
            self._bus.publicar(events.CARGA_CAMBIADA, ahora.carga)


def _mercado_propio(
    estado: Estado, abierto: mercado_del_juego.Mercado, esfera: Esfera | EsferaViva
) -> mercado.MercadoPropio:
    estacion = estado.estacion
    nombre = abierto.estacion or estacion.nombre
    sistema = None
    if estado.system_address is not None and estado.sistema:
        sistema = mercado.Sistema(
            estado.system_address,
            estado.sistema,
            estado.posicion,
            esfera.distancia(estado.posicion) if estado.posicion else None,
            mercado.FUENTE_PROPIO,
        )
    return mercado.MercadoPropio(
        sistema=sistema,
        estacion=mercado.Estacion(
            market_id=abierto.market_id,
            nombre=nombre,
            categoria=clasificacion.categoria(estacion.tipo, nombre),
            plataforma=estacion.plataforma,
            distancia_ls=estacion.distancia_ls,
            planetaria=clasificacion.es_planetaria(estacion.tipo),
        ),
        observado=abierto.observado,
        articulos=abierto.articulos,
        idioma=mercado_del_juego.codigo_de_idioma(estado.idioma),
    )


def _es_guardable(estado: Estado) -> bool:
    """La tabla `ships` se indexa por comandante e ID de nave; el ID 0 es válido."""
    return bool(estado.fid) and estado.nave is not None and estado.nave.ship_id is not None


def _identidad(actual: NaveActual | None) -> tuple[int | None, str] | None:
    return (actual.ship_id, actual.simbolo) if actual else None


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
