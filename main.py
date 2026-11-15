r"""Arranque de LUNA: ubicación de los datos, ventana nativa e interfaz.

Todo fallo anterior a la ventana acaba en el registro y en un aviso nativo:
empaquetado con PyInstaller no hay consola donde ver una traza.
"""

from __future__ import annotations

import logging
import sys
from datetime import timedelta
from pathlib import Path

import webview

from core import events, plataforma, recursos, textos
from core.api import Api
from core.config import ajustes, rutas, ventana
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
            plataforma.aplicar_geometria(win.native, geometria)
            if geometria.maximizada:
                win.maximize()
        except Exception:  # noqa: BLE001 - una ventana mal colocada no es fatal
            registro.exception("no se pudo restaurar la geometria")

    win.events.shown += al_mostrar


def crear_ventana(ubicacion: Ubicacion, titulo: str, api: Api | None = None) -> webview.Window:
    config = rutas.archivo_de_config(ubicacion)
    guardada = ventana.cargar(config, webview.screens)
    win = webview.create_window(
        titulo,
        url=recursos.url_de_la_interfaz(),
        width=guardada.ancho,
        height=guardada.alto,
        min_size=ventana.TAMANO_MINIMO,
        resizable=True,
        frameless=False,
        js_api=api,
    )
    restaurar_al_abrir(win, guardada)
    guardar_al_cerrar(win, config)
    return win


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
    registro.info(
        "datos en %s (portable=%s, motivo=%s, avisos=%s)",
        ubicacion.carpeta,
        ubicacion.portable,
        ubicacion.motivo,
        ubicacion.avisos,
    )
    return ubicacion, textos.cargar()


def main() -> int:
    try:
        ubicacion, diccionario = preparar()
    except (OSError, ValueError):
        registro.exception("no se pudieron cargar los textos")
        plataforma.mostrar_error("LUNA", SIN_TEXTOS)
        return 1

    titulo = textos.texto(textos.CLAVE_TITULO, diccionario) or "LUNA"
    escritor = abrir_base(ubicacion)
    bus = events.Bus()
    config = rutas.archivo_de_config(ubicacion)
    esfera = EsferaViva(ajustes.esfera(config), fiable=ajustes.configuracion_legible(config))
    nucleo = Nucleo(config, bus, escritor, esfera)
    eddn = Servicio(lambda: preparar_eddn(ubicacion, escritor, bus, esfera))
    gestor: Gestor | None = None
    mantenimiento = (
        Mantenimiento(
            escritor, esfera, config, en_pausa=lambda: gestor is not None and gestor.ocupado()
        )
        if escritor
        else None
    )
    if escritor and mantenimiento:
        gestor = Gestor(
            ubicacion.carpeta / "descargas",
            config,
            escritor,
            esfera,
            al_terminar=mantenimiento.aplicar_esfera,
        )
    datos = Datos(
        config,
        rutas.archivo_de_base(ubicacion) if escritor else None,
        ubicacion.carpeta / "descargas",
        esfera,
        gestor,
        mantenimiento,
        eddn,
    )
    sonido = Sonido(config)
    comercio = Comercio(
        nucleo.estado,
        config,
        rutas.archivo_de_base(ubicacion) if escritor else None,
        escritor,
        probar_sonido=sonido.probar,
    )
    alertas = (
        Alertas(
            bus,
            nucleo.estado,
            lambda: comercio.perfil_inicial()["perfil"],
            config,
            rutas.archivo_de_base(ubicacion),
            escritor,
            sonido.alerta,
        )
        if escritor
        else None
    )
    api = Api(
        nucleo,
        ubicacion,
        config,
        base_disponible=escritor is not None,
        elegir_carpeta=elegir_carpeta,
        estado_eddn=eddn.estado,
        datos=datos,
        avisos_de_base=lambda: escritor.avisos if escritor else (),
        comercio=comercio,
    )
    try:
        comprobar_motor()
        crear_ventana(ubicacion, titulo, api)
        sonido.iniciar()
        if alertas:
            # Antes que el núcleo y EDDN, para no perder el primer aviso del bus.
            alertas.iniciar()
        nucleo.iniciar()
        eddn.iniciar()
        if mantenimiento:
            mantenimiento.iniciar()
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
        if mantenimiento:
            mantenimiento.detener()
        if gestor:
            gestor.detener()
        eddn.detener()
        nucleo.detener()
        if alertas:
            alertas.detener()
        sonido.detener()
        if escritor is not None:
            escritor.detener()
    return 0


if __name__ == "__main__":
    sys.exit(main())
