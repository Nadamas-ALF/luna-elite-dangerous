"""El núcleo: sigue el journal, mantiene el estado y avisa a quien se suscriba.

Es lo único que lee el journal (sección 3). Un hilo propio hace todo el trabajo;
los demás hilos solo piden la última instantánea del estado, que es inmutable.
Lo que hay que guardar en la base de datos va al hilo escritor por su cola.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from core import catalogo, events
from core import estacion as clasificacion
from core.config import ajustes
from core.db import mercado
from core.db.escritor import Escritor
from core.esfera import Esfera, EsferaViva
from core.journal import archivos, carpeta, historial, lector, plegado
from core.journal import mercado as mercado_del_juego
from core.state import vista
from core.state.estado import Estado, NaveActual, aplicar

registro = logging.getLogger("luna.nucleo")

INTERVALO = 0.5
# Buscar la carpeta cuesta una consulta a Windows: no hace falta cada medio segundo.
PASOS_ENTRE_BUSQUEDAS = 10


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
        # Solo lo toca el hilo del núcleo.
        self._plegador = plegado.Plegador()
        self._importador = historial.Importador(escritor)

    def iniciar(self) -> None:
        if self._escritor is not None:
            self._escritor.encolar(lambda c: mercado.sembrar_mercancias(c, catalogo.mercancias()))
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
        self._importador.detener()
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

    def importar_historial(self) -> dict:
        """Empieza a leer todos los journals de la carpeta; la importación corre en su hilo."""
        if self._escritor is None:
            return {"error": "sin_base"}
        # `glob` no avisa de una carpeta que desapareció desde que se resolvió: daría
        # una importación «terminada» con cero journals.
        if self._carpeta is None or not self._carpeta.is_dir():
            return {"error": "sin_carpeta"}
        if not self._importador.iniciar(self._carpeta):
            return {"error": "en_marcha"}
        return self._importador.estado()

    def estado_de_la_importacion(self) -> dict:
        return self._importador.estado()

    def cancelar_importacion(self) -> dict:
        self._importador.cancelar()
        return self._importador.estado()

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
        self._plegador = plegado.Plegador()
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
        estado, lote = self._plegador.plegar(estado, eventos)
        if self._escritor is not None:
            plegado.guardar(self._escritor, lote)
        return estado

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
            # Al despegar se publica la estación que dejas: quien arrancó con el comandante
            # ya atracado no vio ningún ATRACADO (E-30).
            if ahora.estacion:
                self._bus.publicar(events.ATRACADO, ahora.estacion)
            else:
                self._bus.publicar(events.DESATRACADO, antes.estacion)
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


def _identidad(actual: NaveActual | None) -> tuple[int | None, str] | None:
    return (actual.ship_id, actual.simbolo) if actual else None
