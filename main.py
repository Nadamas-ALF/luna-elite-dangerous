r"""Arranque de LUNA: ubicación de los datos, ventana nativa e interfaz.

Todo fallo anterior a la ventana acaba en el registro y en un aviso nativo:
empaquetado con PyInstaller no hay consola donde ver una traza.
"""

from __future__ import annotations

import hashlib
import logging
import sys
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import webview

from core import events, plataforma, recursos, textos
from core.api import Api, metodos_expuestos
from core.config import ajustes, aspecto, rutas, ventana
from core.config.rutas import Ubicacion
from core.datos import Datos
from core.db.escritor import Escritor, NoSePudoAbrir
from core.eddn.ingesta import Ingesta
from core.eddn.servicio import Servicio
from core.eddn.sistemas import Conocidos
from core.eddn.suscriptor import Suscriptor
from core.esfera import EsferaViva
from core.mantenimiento import Mantenimiento
from core.nucleo import Nucleo
from core.spansh import descarga
from core.spansh.descarga import Abrir
from core.spansh.gestor import Gestor
from modules.comercio.alerts import Alertas
from modules.comercio.api import Comercio
from modules.comercio.sonido import Sonido

registro = logging.getLogger("luna")

MOTOR_ESPERADO = "edgechromium"

# Único texto fuera de es.json: es el mensaje para cuando es.json no se puede
# leer, que es justo cuando no hay de dónde sacarlo.
SIN_TEXTOS = "LUNA no pudo leer sus textos. La instalacion esta incompleta."


class FaltaWebView2(RuntimeError):
    """Sin el runtime, pywebview cae a MSHTML y la interfaz queda en blanco."""


def configurar_registro(carpeta: Path) -> None:
    """El registro no incluye contenido del journal (sección 10.3)."""
    carpeta.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=carpeta / "luna.log",
        encoding="utf-8",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def comprobar_motor() -> None:
    """Sin WebView2, pywebview no falla: usa MSHTML, que no ejecuta módulos ES.

    La ventana se abriría en blanco y el proceso terminaría con éxito, así que
    hay que detectarlo a mano (riesgo de la sección 12).
    """
    motor = webview.initialize()
    if getattr(motor, "renderer", None) != MOTOR_ESPERADO:
        raise FaltaWebView2(getattr(motor, "renderer", "desconocido"))


def guardar_al_cerrar(win: webview.Window, config: Path) -> None:
    def al_cerrar() -> None:
        try:
            ventana.guardar(config, plataforma.geometria_de_forma(win.native))
        except Exception:  # noqa: BLE001 - al cerrar ya no hay donde avisar
            registro.exception("no se pudo guardar la geometria de la ventana")

    win.events.closing += al_cerrar


def restaurar_al_abrir(win: webview.Window, geometria: ventana.Geometria) -> None:
    """La geometría se aplica con la ventana ya creada, en píxeles físicos.

    Pasarla a `create_window` la haría pasar por la escala de pywebview y por
    el autoescalado de WinForms, que no son simétricos al leerla de vuelta.
    """

    def al_mostrar() -> None:
        try:
            plataforma.en_el_hilo_de_la_interfaz(
                win.native, lambda: plataforma.aplicar_geometria(win.native, geometria)
            )
            if geometria.maximizada:
                win.maximize()
        except Exception:  # noqa: BLE001 - una ventana mal colocada no es fatal
            registro.exception("no se pudo restaurar la geometria")

    win.events.shown += al_mostrar


def crear_ventana(ubicacion: Ubicacion, titulo: str, api: Api | None = None) -> webview.Window:
    config = rutas.archivo_de_config(ubicacion)
    guardada = ventana.cargar(config, webview.screens)
    tema = aspecto.leer(config)
    # En el fragmento de la URL para que la página lo aplique antes de pintar, a la vez que la
    # barra de título. Una consulta (`?`) no sirve: con ella la página local no llega a cargar.
    consulta = urllib.parse.urlencode({"tema": tema.tema, "vidrio": tema.vidrio})
    win = webview.create_window(
        titulo,
        url=f"{recursos.url_de_la_interfaz()}#{consulta}",
        width=guardada.ancho,
        height=guardada.alto,
        min_size=ventana.TAMANO_MINIMO,
        resizable=True,
        frameless=False,
        on_top=ajustes.interfaz(config)[0],
    )
    if api is not None:
        win.expose(*metodos_expuestos(api))
    restaurar_al_abrir(win, guardada)
    win.events.shown += lambda: tenir_barra(win, tema.tema)
    guardar_al_cerrar(win, config)
    return win


def tenir_barra(win: webview.Window, tema: str) -> None:
    try:
        plataforma.en_el_hilo_de_la_interfaz(
            win.native, lambda: plataforma.tenir_barra_de_titulo(win.native, tema)
        )
    except Exception:  # noqa: BLE001 - una barra sin teñir no es fatal
        registro.exception("no se pudo teñir la barra de titulo")


def aplicar_tema(tema: str) -> None:
    """La API llama desde su propio hilo; sin ventana o sin teñir, la barra cambia al reiniciar."""
    if webview.windows:
        tenir_barra(webview.windows[0], tema)


def aplicar_siempre_encima(activado: bool) -> None:
    """La API llama desde su propio hilo; `on_top` de pywebview no pasa al de la ventana."""
    win = webview.windows[0]

    def poner() -> None:
        win.on_top = activado

    plataforma.en_el_hilo_de_la_interfaz(win.native, poner)


def abrir_base(ubicacion: Ubicacion) -> Escritor | None:
    """Sin base de datos la app sigue mostrando el estado; Estado avisa de ello."""
    escritor = Escritor(rutas.archivo_de_base(ubicacion))
    try:
        escritor.iniciar()
    except NoSePudoAbrir:
        registro.exception("no se pudo abrir la base de datos")
        return None
    return escritor


def preparar_eddn(
    ubicacion: Ubicacion, escritor: Escritor | None, bus: events.Bus, esfera: EsferaViva
) -> Suscriptor | None:
    """Sin base de datos no hay dónde guardar lo que llegue, así que no se escucha."""
    config = rutas.archivo_de_config(ubicacion)
    if escritor is None or not ajustes.eddn_activado(config):
        return None
    conocidos = Conocidos(esfera, rutas.archivo_de_base(ubicacion))
    dias = ajustes.antiguedad_maxima_con_memoria(config)

    def antiguedad() -> timedelta:
        return timedelta(days=dias())

    return Suscriptor(Ingesta(escritor, bus, esfera, conocidos, antiguedad=antiguedad))


def elegir_carpeta() -> str | None:
    seleccion = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
    return seleccion[0] if seleccion else None


def arrancar(funcion=None, argumentos=None) -> None:
    """http_server=False y la URL file:// dejan el proceso sin puertos abiertos."""
    webview.start(funcion, argumentos, http_server=False, private_mode=True)


def preparar() -> tuple[Ubicacion, dict]:
    ubicacion = rutas.resolver()
    configurar_registro(ubicacion.carpeta)
    if ajustes.marcar_primer_arranque(rutas.archivo_de_config(ubicacion)):
        registro.info("primer arranque: se enseña la bienvenida")
    registro.info(
        "datos en %s (portable=%s, motivo=%s, avisos=%s)",
        ubicacion.carpeta,
        ubicacion.portable,
        ubicacion.motivo,
        ubicacion.avisos,
    )
    return ubicacion, textos.cargar()


@dataclass
class Partes:
    """Todo lo que corre detrás de la ventana; `verificar_interfaz.py` monta lo mismo (E-39)."""

    config: Path
    bus: events.Bus
    escritor: Escritor | None
    nucleo: Nucleo
    eddn: Servicio
    mantenimiento: Mantenimiento | None
    gestor: Gestor | None
    sonido: Sonido
    alertas: Alertas | None
    api: Api

    def iniciar(self) -> None:
        self.sonido.iniciar()
        if self.alertas:
            # Antes que el núcleo y EDDN, para no perder el primer aviso del bus.
            self.alertas.iniciar()
        self.nucleo.iniciar()
        self.eddn.iniciar()
        if self.mantenimiento:
            self.mantenimiento.iniciar()

    def detener(self) -> None:
        """Al revés que al arrancar, y el escritor el último: los demás le encolan trabajos."""
        en_orden = (
            self.mantenimiento,
            self.gestor,
            self.eddn,
            self.nucleo,
            self.alertas,
            self.sonido,
            self.escritor,
        )
        for parte in en_orden:
            if parte is None:
                continue
            try:
                parte.detener()
            except Exception:  # noqa: BLE001 - una parte rota no debe dejar a las demás en marcha
                registro.exception("no se pudo detener %s", type(parte).__name__)


def montar(
    ubicacion: Ubicacion,
    escritor: Escritor | None,
    sonido: Sonido | None = None,
    abrir: Abrir = descarga.abrir_https,
    elegir: Callable[[], str | None] = elegir_carpeta,
) -> Partes:
    """Construye las partes sin arrancar ningún hilo."""
    bus = events.Bus()
    config = rutas.archivo_de_config(ubicacion)
    base = rutas.archivo_de_base(ubicacion) if escritor else None
    esfera = EsferaViva(ajustes.esfera(config), fiable=ajustes.configuracion_legible(config))
    nucleo = Nucleo(config, bus, escritor, esfera)
    eddn = Servicio(lambda: preparar_eddn(ubicacion, escritor, bus, esfera))
    mantenimiento, gestor = _mantenimiento_y_gestor(ubicacion, escritor, esfera, abrir)
    descargas = ubicacion.carpeta / "descargas"
    datos = Datos(config, base, descargas, esfera, gestor, mantenimiento, eddn, abrir=abrir)
    sonido = sonido or Sonido(config)
    comercio = Comercio(nucleo.estado, config, base, escritor, probar_sonido=sonido.probar)
    alertas = (
        Alertas(
            bus,
            nucleo.estado,
            lambda: comercio.perfil_inicial()["perfil"],
            config,
            base,
            escritor,
            sonido.alerta,
        )
        if escritor and base
        else None
    )
    api = Api(
        nucleo,
        ubicacion,
        config,
        base_disponible=escritor is not None,
        elegir_carpeta=elegir,
        estado_eddn=eddn.estado,
        datos=datos,
        avisos_de_base=lambda: escritor.avisos if escritor else (),
        comercio=comercio,
        aplicar_siempre_encima=aplicar_siempre_encima,
        aplicar_tema=aplicar_tema,
    )
    return Partes(config, bus, escritor, nucleo, eddn, mantenimiento, gestor, sonido, alertas, api)


def _mantenimiento_y_gestor(
    ubicacion: Ubicacion, escritor: Escritor | None, esfera: EsferaViva, abrir: Abrir
) -> tuple[Mantenimiento | None, Gestor | None]:
    """Se necesitan el uno al otro: el gestor pausa la limpieza y la limpieza le avisa."""
    if escritor is None:
        return None, None
    config = rutas.archivo_de_config(ubicacion)
    gestor: Gestor | None = None
    mantenimiento = Mantenimiento(
        escritor,
        esfera,
        config,
        en_pausa=lambda: gestor is not None and gestor.ocupado(),
        al_corregir_esfera=lambda corregida: gestor and gestor.reducir_cobertura(corregida),
    )
    gestor = Gestor(
        ubicacion.carpeta / "descargas",
        config,
        escritor,
        esfera,
        al_terminar=mantenimiento.aplicar_esfera,
        abrir=abrir,
    )
    return mantenimiento, gestor


def nombre_de_instancia(ubicacion: Ubicacion) -> str:
    """Uno por carpeta de datos: dos LUNA con datos distintos (como `verificar_interfaz.py` con
    los suyos) no se estorban; dos sobre la misma base, sí."""
    carpeta = str(ubicacion.carpeta.resolve()).casefold()
    return "Local\\LUNA-" + hashlib.sha256(carpeta.encode("utf-8")).hexdigest()[:32]


def main() -> int:
    try:
        ubicacion, diccionario = preparar()
    except (OSError, ValueError):
        registro.exception("no se pudieron cargar los textos")
        plataforma.mostrar_error("LUNA", SIN_TEXTOS)
        return 1

    titulo = textos.texto(textos.CLAVE_TITULO, diccionario) or "LUNA"
    if plataforma.hay_otra_instancia(nombre_de_instancia(ubicacion)):
        registro.info("ya hay un LUNA abierto con estos datos; esta copia se cierra")
        aviso = textos.texto(textos.CLAVE_YA_ABIERTA, diccionario) or titulo
        plataforma.mostrar_error(titulo, aviso, plataforma.MB_ICONINFORMATION)
        return 0
    partes = montar(ubicacion, abrir_base(ubicacion))
    try:
        comprobar_motor()
        crear_ventana(ubicacion, titulo, partes.api)
        partes.iniciar()
        arrancar()
    except FaltaWebView2 as error:
        registro.error("motor de la interfaz inesperado: %s", error)
        plataforma.mostrar_error(
            titulo, textos.con_detalle(textos.CLAVE_SIN_WEBVIEW2, diccionario, error)
        )
        return 1
    except Exception as error:  # noqa: BLE001 - cualquier fallo debe verse
        registro.exception("fallo al abrir la ventana")
        plataforma.mostrar_error(
            titulo, textos.con_detalle(textos.CLAVE_ERROR_ARRANQUE, diccionario, error)
        )
        return 1
    finally:
        partes.detener()
    return 0


if __name__ == "__main__":
    sys.exit(main())
