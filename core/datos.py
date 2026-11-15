"""Los datos que LUNA guarda y de dónde salen, tal como los ve la pantalla Configuración.

Junta la esfera, la retención, EDDN y el trabajo de Spansh. Cada operación valida
sus parámetros (vienen de la interfaz) y responde con datos simples; un fallo es
`{"error": <código>}` y el texto lo pone la interfaz con `ui/i18n/es.json`.
"""

from __future__ import annotations

import logging
import math
import shutil
import threading
from pathlib import Path

from core.config import ajustes
from core.eddn.servicio import Servicio
from core.esfera import Esfera, EsferaViva
from core.mantenimiento import Mantenimiento
from core.spansh import cambio, descarga
from core.spansh.cambio import ErrorDeCambio
from core.spansh.descarga import Abrir, ErrorDeDescarga
from core.spansh.gestor import INACTIVA, Gestor

registro = logging.getLogger("luna.datos")

ERROR_OCUPADO = "ocupado"
ERROR_SIN_BASE = "sin_base"
ERROR_NO_GUARDADO = "no_guardado"
ERROR_DIAS = "dias"
ERROR_PARAMETRO = "parametro"

DIAS_MAXIMOS = ajustes.DIAS_DE_RETENCION_MAXIMOS


def _esfera_a_dict(esfera: Esfera) -> dict:
    return {"nombre": esfera.nombre, "centro": list(esfera.centro), "radio": esfera.radio}


def _dias(valor: object) -> float:
    numero = isinstance(valor, (int, float)) and not isinstance(valor, bool)
    if not numero or not math.isfinite(valor) or not 0 < valor <= DIAS_MAXIMOS:
        raise ErrorDeCambio(ERROR_DIAS)
    return float(valor)


class Datos:
    def __init__(
        self,
        config: Path,
        base: Path | None,
        carpeta_de_descargas: Path,
        esfera: EsferaViva,
        gestor: Gestor | None = None,
        mantenimiento: Mantenimiento | None = None,
        eddn: Servicio | None = None,
        abrir: Abrir = descarga.abrir_https,
    ) -> None:
        self._config = config
        self._base = base
        self._carpeta = carpeta_de_descargas
        self._esfera = esfera
        self._gestor = gestor
        self._mantenimiento = mantenimiento
        self._eddn = eddn
        self._abrir = abrir
        # Entre comprobar «ocupado» y arrancar o limpiar no puede colarse otro cambio.
        self._candado = threading.Lock()

    def configuracion(self) -> dict:
        return {
            "esfera": _esfera_a_dict(self._esfera.actual),
            "retencion": {
                "visitados_dias": ajustes.dias_de_mercados_visitados(self._config),
                "antiguedad_maxima_dias": ajustes.antiguedad_maxima_de_precios(self._config),
            },
            "eddn": {
                "activado": ajustes.eddn_activado(self._config),
                "disponible": self._base is not None,
            },
            "spansh_disponible": self._gestor is not None,
        }

    def esfera_actual(self) -> Esfera:
        return self._esfera.actual

    def spansh(self) -> dict:
        if self._gestor is None:
            return {"fase": INACTIVA, "error": None, "ultima": None}
        return self._gestor.estado()

    def proponer_esfera(self, nombre: object, radio: object) -> dict:
        """Lo que hay que mostrar antes de pedir confirmación; no cambia nada."""
        try:
            nueva = self._resolver(nombre, radio)
        except ErrorDeCambio as error:
            return {"error": error.motivo}
        cubierta = self._gestor.cubierta if self._gestor else None
        necesaria = cambio.descarga_necesaria(cubierta, nueva)
        return {
            "esfera": _esfera_a_dict(nueva),
            "descarga_necesaria": necesaria,
            # Lo guardado que quede fuera de la esfera nueva se borra: se avisa antes de confirmar.
            "borra_lo_de_fuera": cubierta is not None and not cambio.esfera_dentro(cubierta, nueva),
            "descargable": self._gestor is not None,
            "ocupado": self._gestor.ocupado() if self._gestor else False,
            **self._tamano(),
        }

    def _tamano(self) -> dict:
        try:
            tamano = cambio.tamano_del_volcado(self._abrir)
        except ErrorDeDescarga as error:
            return {"tamano": None, "libre": self._libre(), "error_tamano": error.motivo}
        return {"tamano": tamano, "libre": self._libre(), "error_tamano": None}

    def _libre(self) -> int | None:
        try:
            carpeta = self._carpeta if self._carpeta.exists() else self._carpeta.parent
            return shutil.disk_usage(carpeta).free
        except OSError:
            return None

    def _resolver(self, nombre: object, radio: object) -> Esfera:
        centro = cambio.resolver_centro(self._base, nombre)
        return Esfera(centro.nombre, centro.centro, cambio.validar_radio(radio))

    def aplicar_esfera(self, nombre: object, radio: object, descargar: object) -> dict:
        """Confirmado por el usuario: guarda la esfera nueva y, si pidió descargar, empieza."""
        if not isinstance(descargar, bool):
            return {"error": ERROR_PARAMETRO}
        try:
            nueva = self._resolver(nombre, radio)
        except ErrorDeCambio as error:
            return {"error": error.motivo}
        if descargar and self._gestor is None:
            return {"error": ERROR_SIN_BASE}
        with self._candado:
            return self._cambiar_esfera(nueva, descargar)

    def _cambiar_esfera(self, nueva: Esfera, descargar: bool) -> dict:
        if self._gestor is not None and self._gestor.ocupado():
            return {"error": ERROR_OCUPADO}
        if not ajustes.guardar_esfera(self._config, nueva):
            return {"error": ERROR_NO_GUARDADO}
        self._esfera.cambiar(nueva)
        if descargar:
            if not self._gestor.iniciar():
                return {"error": ERROR_OCUPADO}
        else:
            # Con descarga, la limpieza espera a que termine (regla 6 de la 5.4).
            if self._gestor is not None:
                self._gestor.reducir_cobertura(nueva)
            if self._mantenimiento is not None:
                self._mantenimiento.aplicar_esfera()
        return {"ok": True, "descargando": descargar}

    def guardar_retencion(self, visitados_dias: object, antiguedad_maxima_dias: object) -> dict:
        try:
            visitados, antiguedad = _dias(visitados_dias), _dias(antiguedad_maxima_dias)
        except ErrorDeCambio as error:
            return {"error": error.motivo}
        if not ajustes.guardar_retencion(self._config, visitados, antiguedad):
            return {"error": ERROR_NO_GUARDADO}
        if self._mantenimiento is not None:
            self._mantenimiento.limpiar()
        return {"ok": True}

    def establecer_eddn(self, activado: object) -> dict:
        if not isinstance(activado, bool):
            return {"error": ERROR_PARAMETRO}
        if not ajustes.guardar_eddn_activado(self._config, activado):
            return {"error": ERROR_NO_GUARDADO}
        if self._eddn is not None:
            if activado:
                self._eddn.iniciar()
            else:
                self._eddn.detener()
        return {"ok": True}

    def reanudar(self) -> dict:
        if self._gestor is None:
            return {"error": ERROR_SIN_BASE}
        with self._candado:
            iniciado = self._gestor.iniciar()
        return {"ok": True} if iniciado else {"error": ERROR_OCUPADO}

    def pausar(self) -> dict:
        if self._gestor is not None:
            self._gestor.pausar()
        return {"ok": True}

    def cancelar(self) -> dict:
        if self._gestor is not None:
            self._gestor.cancelar()
        return {"ok": True}
