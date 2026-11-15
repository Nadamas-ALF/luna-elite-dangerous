"""El trabajo de Spansh de principio a fin: descargar, importar y recordar cuándo.

Hay un solo trabajo a la vez, en su propio hilo. La interfaz lo consulta con
`estado()` y lo controla con `iniciar`, `pausar` y `cancelar`:

- **Pausar** conserva lo descargado (o el archivo completo si ya se estaba
  importando) y `iniciar` continúa donde quedó.
- **Cancelar** borra el archivo.
- Un fallo deja el trabajo en `error`; si quedó algo descargado, `iniciar` lo
  reanuda.

Este hilo no escribe en la base: la importación lo hace por la cola del escritor.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from core.config import ajustes
from core.db.escritor import Escritor
from core.esfera import Esfera, EsferaViva
from core.spansh import cambio, descarga, importacion
from core.spansh.descarga import Abrir, Descarga, ErrorDeDescarga
from core.spansh.importacion import ErrorDeImportacion

registro = logging.getLogger("luna.spansh")

INACTIVA = "inactiva"
DESCARGANDO = "descargando"
PAUSADA = "pausada"
IMPORTANDO = "importando"
ERROR = "error"

ESPERA_DE_CIERRE = 10.0


class Gestor:
    def __init__(
        self,
        carpeta: Path,
        config: Path,
        escritor: Escritor | None,
        esfera: EsferaViva,
        al_terminar: Callable[[], None] = lambda: None,
        abrir: Abrir = descarga.abrir_https,
        trozo: int = descarga.TROZO,
    ) -> None:
        self._descarga = Descarga(carpeta, abrir=abrir, trozo=trozo)
        self._config = config
        self._escritor = escritor
        self._esfera = esfera
        self._al_terminar = al_terminar
        self._candado = threading.Lock()
        self._hilo: threading.Thread | None = None
        self._parar = threading.Event()
        self._descartar = False
        self._error: str | None = None
        self._ultima = ajustes.ultima_descarga(config)
        self._descargado = 0
        self._total: int | None = None
        self._leidas = self._encontrados = self._guardados = 0
        self._etapa = importacion.LEYENDO
        self._leido = self._tamano_archivo = 0
        self._fase = INACTIVA
        self._recuperar_lo_pendiente()
        if esfera.fiable:
            # La esfera pudo cambiarse a mano en config.json con LUNA cerrada.
            self.reducir_cobertura(esfera.actual)

    def _recuperar_lo_pendiente(self) -> None:
        """Tras reiniciar LUNA, una descarga a medias sigue siendo reanudable."""
        if self._descarga.final.exists():
            self._fase = PAUSADA
            self._descargado = self._total = self._descarga.final.stat().st_size
        elif (pendiente := self._descarga.pendiente()) is not None:
            self._fase = PAUSADA
            self._descargado, self._total = pendiente.descargado, pendiente.total

    def estado(self) -> dict:
        with self._candado:
            ultima = self._ultima
            return {
                "fase": self._fase,
                "descargado": self._descargado,
                "total": self._total,
                "leidas": self._leidas,
                "encontrados": self._encontrados,
                "guardados": self._guardados,
                "etapa": self._etapa,
                "leido": self._leido,
                "tamano_archivo": self._tamano_archivo,
                "error": self._error,
                "ultima": {
                    "fecha": ultima.fecha,
                    "centro": ultima.esfera.nombre,
                    "radio": ultima.esfera.radio,
                }
                if ultima
                else None,
            }

    @property
    def cubierta(self) -> Esfera | None:
        """La esfera que cubre lo descargado y sigue guardado; None si no hay garantía."""
        with self._candado:
            return self._ultima.cobertura if self._ultima else None

    def reducir_cobertura(self, nueva: Esfera) -> None:
        """La esfera cambió sin descargar: la limpieza borró lo de fuera, y esto lo recuerda."""
        with self._candado:
            ultima = self._ultima
            if ultima is None or ultima.cobertura is None:
                return
            cobertura = cambio.cobertura_tras_cambiar(ultima.cobertura, nueva)
            if cobertura == ultima.cobertura:
                return
            self._ultima = replace(ultima, cobertura=cobertura)
        if not ajustes.guardar_cobertura(self._config, cobertura):
            registro.warning("no se pudo anotar lo que queda de la descarga de Spansh")

    def ocupado(self) -> bool:
        with self._candado:
            return self._fase in (DESCARGANDO, IMPORTANDO)

    def iniciar(self) -> bool:
        """False si ya hay un trabajo en marcha o no hay base donde guardar."""
        with self._candado:
            if self._escritor is None or self._fase in (DESCARGANDO, IMPORTANDO):
                return False
            self._parar.clear()
            self._descartar = False
            self._error = None
            self._fase = IMPORTANDO if self._descarga.final.exists() else DESCARGANDO
            self._hilo = threading.Thread(target=self._correr, name="spansh", daemon=True)
            self._hilo.start()
        return True

    def pausar(self) -> None:
        self._parar.set()

    def cancelar(self) -> None:
        """Detiene el trabajo si lo hay y borra lo descargado."""
        with self._candado:
            en_marcha = self._fase in (DESCARGANDO, IMPORTANDO)
            self._descartar = True
            if not en_marcha:
                self._borrar_descargado()
                self._fase, self._error = INACTIVA, None
                self._descargado, self._total = 0, None
        self._parar.set()

    def detener(self) -> None:
        """Al cerrar LUNA: se pausa, no se pierde lo descargado."""
        self._parar.set()
        hilo = self._hilo
        if hilo is not None and hilo.is_alive():
            hilo.join(ESPERA_DE_CIERRE)

    def _borrar_descargado(self) -> None:
        self._descarga.descartar()
        self._descarga.final.unlink(missing_ok=True)

    def _poner(self, **campos: object) -> None:
        with self._candado:
            for nombre, valor in campos.items():
                setattr(self, f"_{nombre}", valor)

    def _correr(self) -> None:
        try:
            archivo = self._bajar()
            if archivo is not None:
                self._volcar(archivo)
        except ErrorDeDescarga as error:
            self._fallar(f"descarga_{error.motivo}")
        except ErrorDeImportacion as error:
            self._fallar(f"importacion_{error.motivo}")
        except Exception:  # noqa: BLE001 - el hilo no debe morir sin dejar rastro
            registro.exception("fallo inesperado en el trabajo de Spansh")
            self._fallar("interno")

    def _bajar(self) -> Path | None:
        if self._descarga.final.exists():
            return self._descarga.final
        self._poner(fase=DESCARGANDO)
        archivo = self._descarga.ejecutar(self._parar, self._al_descargar)
        if archivo is None:
            self._interrumpida()
        return archivo

    def _al_descargar(self, progreso: descarga.Progreso) -> None:
        self._poner(descargado=progreso.descargado, total=progreso.total)

    def _volcar(self, archivo: Path) -> None:
        self._poner(
            fase=IMPORTANDO,
            etapa=importacion.LEYENDO,
            leidas=0,
            encontrados=0,
            guardados=0,
            leido=0,
            tamano_archivo=0,
        )
        esfera = self._esfera.actual
        try:
            resumen = importacion.importar(
                archivo,
                esfera,
                self._escritor,
                self._parar,
                self._al_importar,
                dias_maximos=ajustes.antiguedad_maxima_de_precios(self._config),
            )
        except ErrorDeImportacion as error:
            if error.motivo == importacion.MOTIVO_ARCHIVO:
                # Un archivo dañado no se arregla repitiendo: hay que bajarlo otra vez. Uno
                # sano que LUNA no entiende (formato) se conserva: bajarlo de nuevo no ayudaría.
                self._borrar_descargado()
            raise
        if resumen is None:
            self._interrumpida()
            return
        fecha = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not ajustes.guardar_ultima_descarga(self._config, fecha, esfera):
            registro.warning("no se pudo anotar la descarga de Spansh en config.json")
        with self._candado:
            self._ultima = ajustes.UltimaDescarga(fecha, esfera, esfera)
            self._fase, self._descargado, self._total = INACTIVA, 0, None
        registro.info(
            "Spansh importado: %d sistemas, %d mercados (%d más viejos no se guardaron), "
            "%d precios, %d descartados",
            resumen.sistemas,
            resumen.mercados,
            resumen.mercados_viejos,
            resumen.precios,
            resumen.descartados,
        )
        self._al_terminar()

    def _al_importar(self, progreso: importacion.Progreso) -> None:
        self._poner(
            etapa=progreso.fase,
            leidas=progreso.leidas,
            encontrados=progreso.encontrados,
            guardados=progreso.guardados,
            leido=progreso.posicion,
            tamano_archivo=progreso.total,
        )

    def _interrumpida(self) -> None:
        """Pausa (se conserva lo descargado) o cancelación (se borra)."""
        with self._candado:
            if self._descartar:
                self._borrar_descargado()
                self._fase, self._descargado, self._total = INACTIVA, 0, None
            else:
                self._fase = PAUSADA

    def _fallar(self, codigo: str) -> None:
        with self._candado:
            self._fase, self._error = ERROR, codigo
        registro.error("el trabajo de Spansh falló: %s", codigo)
