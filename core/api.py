"""La única clase que la interfaz puede llamar (sección 10.2).

pywebview recibe solo los métodos de `metodos_expuestos`, no el objeto: con
`js_api` despacha cada llamada con `getattr` sin filtrar el guion bajo, y un
script de la página podría llegar a `_nucleo.detener` (E-01). Ningún
método recibe rutas ni datos de la interfaz; la carpeta del journal se elige
con el diálogo nativo de Windows. Los datos de Spansh, la esfera y la retención
llegan como texto y números simples y `Datos` los valida antes de usarlos; los
perfiles de búsqueda los valida `Comercio`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from core.config import ajustes, aspecto
from core.config.rutas import Ubicacion
from core.datos import Datos
from core.journal import carpeta
from core.nucleo import Nucleo
from core.state import vista
from core.version import VERSION

if TYPE_CHECKING:
    from modules.comercio.api import Comercio

registro = logging.getLogger("luna.api")

Selector = Callable[[], str | None]

_NO_DISPONIBLE = {"error": "no_disponible"}
_PARAMETRO = {"error": "parametro"}


class Api:
    def __init__(
        self,
        nucleo: Nucleo,
        ubicacion: Ubicacion,
        config: Path,
        base_disponible: bool,
        elegir_carpeta: Selector,
        estado_eddn: Callable[[], str] = lambda: "desactivado",
        datos: Datos | None = None,
        avisos_de_base: Callable[[], tuple[str, ...]] = tuple,
        comercio: Comercio | None = None,
        aplicar_siempre_encima: Callable[[bool], None] | None = None,
        aplicar_tema: Callable[[str], None] | None = None,
    ) -> None:
        self._nucleo = nucleo
        self._ubicacion = ubicacion
        self._config = config
        self._base_disponible = base_disponible
        self._elegir_carpeta = elegir_carpeta
        self._estado_eddn = estado_eddn
        self._datos = datos
        self._avisos_de_base = avisos_de_base
        self._comercio = comercio
        self._aplicar_siempre_encima = aplicar_siempre_encima
        self._aplicar_tema = aplicar_tema

    def estado(self) -> dict:
        contexto = vista.Contexto(
            journal=self._nucleo.estado_del_journal(),
            motivo_datos=self._ubicacion.motivo,
            avisos_datos=(*self._ubicacion.avisos, *self._avisos_de_base()),
            base_disponible=self._base_disponible,
            eddn=self._estado_eddn(),
            **self._contexto_de_datos(),
        )
        return vista.a_diccionario(self._nucleo.estado(), contexto)

    def _contexto_de_datos(self) -> dict:
        if self._datos is None:
            return {}
        return {"esfera": self._datos.esfera_actual(), "spansh": self._datos.spansh()}

    def configuracion(self) -> dict:
        elegida = ajustes.carpeta_journal(self._config)
        usada = carpeta.resolver(elegida)
        return {
            **(self._datos.configuracion() if self._datos else {}),
            "journal": {
                "carpeta": str(usada) if usada else None,
                "automatica": elegida is None,
                "elegida_no_existe": elegida is not None and not Path(elegida).is_dir(),
            },
            "datos": {"carpeta": str(self._ubicacion.carpeta), "version": VERSION},
        }

    def elegir_carpeta_journal(self) -> dict:
        """Abre el diálogo nativo; si el usuario cancela, no cambia nada."""
        try:
            seleccion = self._elegir_carpeta()
        except Exception:  # noqa: BLE001 - un diálogo roto no debe tumbar la interfaz
            registro.exception("no se pudo abrir el dialogo de carpeta")
            seleccion = None
        if not seleccion:
            return self.configuracion()
        return self._con_resultado(self._guardar_carpeta(seleccion))

    def usar_carpeta_automatica(self) -> dict:
        return self._con_resultado(self._guardar_carpeta(None))

    def importar_historial(self) -> dict:
        return self._nucleo.importar_historial()

    def estado_de_la_importacion(self) -> dict:
        return self._nucleo.estado_de_la_importacion()

    def cancelar_importacion(self) -> dict:
        return self._nucleo.cancelar_importacion()

    def spansh(self) -> dict:
        return self._datos.spansh() if self._datos else _NO_DISPONIBLE

    def proponer_esfera(self, nombre: str, radio: float) -> dict:
        """Lo que hay que enseñar antes de confirmar un cambio de centro o de radio."""
        return self._datos.proponer_esfera(nombre, radio) if self._datos else _NO_DISPONIBLE

    def aplicar_esfera(self, nombre: str, radio: float, descargar: bool) -> dict:
        if self._datos is None:
            return _NO_DISPONIBLE
        return self._datos.aplicar_esfera(nombre, radio, descargar)

    def borrar_datos_de_mercado(self) -> dict:
        return self._datos.borrar_mercados() if self._datos else _NO_DISPONIBLE

    def espacio_en_disco(self) -> dict:
        return self._datos.espacio() if self._datos else _NO_DISPONIBLE

    def guardar_retencion(self, visitados_dias: float, antiguedad_maxima_dias: float) -> dict:
        if self._datos is None:
            return _NO_DISPONIBLE
        return self._datos.guardar_retencion(visitados_dias, antiguedad_maxima_dias)

    def establecer_eddn(self, activado: bool) -> dict:
        return self._datos.establecer_eddn(activado) if self._datos else _NO_DISPONIBLE

    def reanudar_descarga(self) -> dict:
        return self._datos.reanudar() if self._datos else _NO_DISPONIBLE

    def pausar_descarga(self) -> dict:
        return self._datos.pausar() if self._datos else _NO_DISPONIBLE

    def cancelar_descarga(self) -> dict:
        return self._datos.cancelar() if self._datos else _NO_DISPONIBLE

    def perfil_inicial(self) -> dict:
        return self._comercio.perfil_inicial() if self._comercio else _NO_DISPONIBLE

    def buscar_rutas(self, modo: str, perfil: dict, paradas: int | None = None) -> dict:
        if self._comercio is None:
            return _NO_DISPONIBLE
        return self._comercio.buscar_rutas(modo, perfil, paradas)

    def ahora(self, perfil: dict) -> dict:
        return self._comercio.ahora(perfil) if self._comercio else _NO_DISPONIBLE

    def explicar_busqueda(self, perfil: dict) -> dict:
        return self._comercio.explicar_busqueda(perfil) if self._comercio else _NO_DISPONIBLE

    def buscar_estaciones(self, texto: str) -> dict:
        return self._comercio.buscar_estaciones(texto) if self._comercio else _NO_DISPONIBLE

    def perfiles_guardados(self) -> dict:
        return self._comercio.perfiles_guardados() if self._comercio else _NO_DISPONIBLE

    def guardar_perfil(self, nombre: str, perfil: dict) -> dict:
        return self._comercio.guardar_perfil(nombre, perfil) if self._comercio else _NO_DISPONIBLE

    def borrar_perfil(self, nombre: str) -> dict:
        return self._comercio.borrar_perfil(nombre) if self._comercio else _NO_DISPONIBLE

    def ajustes_de_busqueda(self) -> dict:
        return self._comercio.ajustes_de_busqueda() if self._comercio else _NO_DISPONIBLE

    def guardar_ajustes_de_busqueda(self, tope_dias: int, tipos: list, limite_s: int) -> dict:
        if self._comercio is None:
            return _NO_DISPONIBLE
        return self._comercio.guardar_ajustes_de_busqueda(tope_dias, tipos, limite_s)

    def rendimiento(self, sesion: str | None) -> dict:
        return self._comercio.rendimiento(sesion) if self._comercio else _NO_DISPONIBLE

    def ajustes_de_sesiones(self) -> dict:
        return self._comercio.ajustes_de_sesiones() if self._comercio else _NO_DISPONIBLE

    def guardar_ajustes_de_sesiones(self, horas: int, por_partida: bool) -> dict:
        if self._comercio is None:
            return _NO_DISPONIBLE
        return self._comercio.guardar_ajustes_de_sesiones(horas, por_partida)

    def guardar_omitir_sesiones_vacias(self, omitir: bool) -> dict:
        if self._comercio is None:
            return _NO_DISPONIBLE
        return self._comercio.guardar_omitir_sesiones_vacias(omitir)

    def reglas_de_alertas(self) -> dict:
        return self._comercio.reglas_de_alertas() if self._comercio else _NO_DISPONIBLE

    def guardar_reglas_de_alertas(self, reglas: dict) -> dict:
        if self._comercio is None:
            return _NO_DISPONIBLE
        return self._comercio.guardar_reglas_de_alertas(reglas)

    def avisos(self, desde_id: int | None) -> dict:
        return self._comercio.avisos(desde_id) if self._comercio else _NO_DISPONIBLE

    def ajustes_de_sonido(self) -> dict:
        return self._comercio.ajustes_de_sonido() if self._comercio else _NO_DISPONIBLE

    def guardar_ajustes_de_sonido(self, activado: bool, volumen: int) -> dict:
        if self._comercio is None:
            return _NO_DISPONIBLE
        return self._comercio.guardar_ajustes_de_sonido(activado, volumen)

    def probar_sonido(self, volumen: int) -> dict:
        return self._comercio.probar_sonido(volumen) if self._comercio else _NO_DISPONIBLE

    def rutas_fijadas(self) -> dict:
        return self._comercio.rutas_fijadas() if self._comercio else _NO_DISPONIBLE

    def estimar_ruta(self, ruta: dict) -> dict:
        return self._comercio.estimar_ruta(ruta) if self._comercio else _NO_DISPONIBLE

    def fijar_ruta(self, ruta: dict) -> dict:
        return self._comercio.fijar_ruta(ruta) if self._comercio else _NO_DISPONIBLE

    def desfijar_ruta(self, id_: int) -> dict:
        return self._comercio.desfijar_ruta(id_) if self._comercio else _NO_DISPONIBLE

    def ajustes_de_ruta_en_curso(self) -> dict:
        return self._comercio.ajustes_de_ruta_en_curso() if self._comercio else _NO_DISPONIBLE

    def guardar_ajustes_de_ruta_en_curso(
        self, aviso: bool, margen: float, portapapeles: bool
    ) -> dict:
        if self._comercio is None:
            return _NO_DISPONIBLE
        return self._comercio.guardar_ajustes_de_ruta_en_curso(aviso, margen, portapapeles)

    def ajustes_de_ventana(self) -> dict:
        encima, plegado = ajustes.interfaz(self._config)
        return {
            "siempre_encima": encima,
            "lateral_plegado": plegado,
            "secciones_abiertas": list(ajustes.secciones_abiertas(self._config)),
        }

    def guardar_secciones_abiertas(self, secciones: list) -> dict:
        if not ajustes.son_secciones_validas(secciones):
            return _PARAMETRO
        if not ajustes.guardar_secciones_abiertas(self._config, secciones):
            return {"error": "no_guardado"}
        return {"secciones_abiertas": secciones}

    def guardar_siempre_encima(self, activado: bool) -> dict:
        """Guarda el ajuste y lo aplica ya; `aplicado` dice si no hizo falta reiniciar."""
        if not isinstance(activado, bool):
            return _PARAMETRO
        if not ajustes.guardar_siempre_encima(self._config, activado):
            return {"error": "no_guardado"}
        return {"siempre_encima": activado, "aplicado": self._aplicar_encima(activado)}

    def guardar_lateral_plegado(self, plegado: bool) -> dict:
        if not isinstance(plegado, bool):
            return _PARAMETRO
        if not ajustes.guardar_lateral_plegado(self._config, plegado):
            return {"error": "no_guardado"}
        return {"lateral_plegado": plegado}

    def bienvenida(self) -> dict:
        return {"pendiente": ajustes.bienvenida_pendiente(self._config)}

    def terminar_bienvenida(self) -> dict:
        return {"guardado": ajustes.terminar_bienvenida(self._config)}

    def ajustes_de_aspecto(self) -> dict:
        """Lo que la interfaz aplica al arrancar y lo que Configuración deja elegir."""
        actual = aspecto.leer(self._config)
        return {
            "tamano_letra": actual.tamano_letra,
            "densidad": actual.densidad,
            "tema": actual.tema,
            "vidrio": actual.vidrio,
            "filas_por_pagina": actual.filas_por_pagina,
            "opciones": {
                "tamanos": list(aspecto.TAMANOS_DE_LETRA),
                "densidades": list(aspecto.DENSIDADES),
                "temas": list(aspecto.TEMAS),
                "vidrios": list(aspecto.VIDRIOS),
                "filas": list(aspecto.FILAS_POR_PAGINA),
            },
            "columnas": {
                modo: {
                    "disponibles": list(disponibles),
                    "elegidas": list(actual.columnas[modo]),
                }
                for modo, disponibles in aspecto.COLUMNAS_DISPONIBLES.items()
            },
        }

    def guardar_tamano_de_letra(self, tamano: str) -> dict:
        if not aspecto.es_tamano_de_letra(tamano):
            return _PARAMETRO
        if not aspecto.guardar_tamano_de_letra(self._config, tamano):
            return {"error": "no_guardado"}
        return {"tamano_letra": tamano}

    def guardar_densidad(self, densidad: str) -> dict:
        if not aspecto.es_densidad(densidad):
            return _PARAMETRO
        if not aspecto.guardar_densidad(self._config, densidad):
            return {"error": "no_guardado"}
        return {"densidad": densidad}

    def guardar_tema(self, tema: str) -> dict:
        """Guarda el tema y tiñe la barra de título con él.

        El orden de dos cambios seguidos lo garantiza la interfaz, que espera a uno para mandar
        el siguiente (`lectura.js`): un candado aquí no ordenaría y retendría hilos en `Invoke`.
        """
        if not aspecto.es_tema(tema):
            return _PARAMETRO
        if not aspecto.guardar_tema(self._config, tema):
            return {"error": "no_guardado"}
        if self._aplicar_tema is not None:
            self._aplicar_tema(tema)
        return {"tema": tema}

    def guardar_vidrio(self, vidrio: str) -> dict:
        if not aspecto.es_vidrio(vidrio):
            return _PARAMETRO
        if not aspecto.guardar_vidrio(self._config, vidrio):
            return {"error": "no_guardado"}
        return {"vidrio": vidrio}

    def guardar_filas_por_pagina(self, filas: int) -> dict:
        if not aspecto.es_filas_por_pagina(filas):
            return _PARAMETRO
        if not aspecto.guardar_filas_por_pagina(self._config, filas):
            return {"error": "no_guardado"}
        return {"filas_por_pagina": filas}

    def guardar_columnas(self, modo: str, columnas: list) -> dict:
        elegidas = aspecto.columnas_validas(modo, columnas)
        if elegidas is None:
            return _PARAMETRO
        if not aspecto.guardar_columnas(self._config, modo, elegidas):
            return {"error": "no_guardado"}
        return {"modo": modo, "elegidas": list(elegidas)}

    def _aplicar_encima(self, activado: bool) -> bool:
        if self._aplicar_siempre_encima is None:
            return False
        try:
            self._aplicar_siempre_encima(activado)
        except Exception:  # noqa: BLE001 - sin aplicar en vivo, el ajuste rige al reiniciar
            registro.exception("no se pudo aplicar «siempre encima» sin reiniciar")
            return False
        return True

    def _con_resultado(self, guardado: bool) -> dict:
        return {**self.configuracion(), "no_guardado": not guardado}

    def _guardar_carpeta(self, elegida: str | None) -> bool:
        """Solo reconstruye el núcleo si el cambio quedó escrito."""
        guardado = ajustes.guardar_carpeta_journal(self._config, elegida)
        if guardado:
            self._nucleo.reiniciar_journal()
        return guardado


def metodos_expuestos(api: Api) -> list[Callable]:
    """Los métodos públicos de `api`, para `Window.expose`."""
    return [
        getattr(api, nombre)
        for nombre, valor in vars(Api).items()
        if not nombre.startswith("_") and callable(valor)
    ]
