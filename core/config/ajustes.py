"""Ajustes del usuario que lee el núcleo, con valores por defecto validados.

config.json lo puede editar el usuario a mano, así que cada valor se comprueba:
uno con el tipo equivocado cae al valor por defecto en lugar de romper el
arranque.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.config import archivo
from core.esfera import Esfera

registro = logging.getLogger("luna.ajustes")

CLAVE_JOURNAL = "journal"

DIAS_POR_DEFECTO = 7
DIAS_MINIMOS = 1
DIAS_MAXIMOS = 90

CENTRO_POR_DEFECTO = (0.0, 0.0, 0.0)
CENTRO_NOMBRE_POR_DEFECTO = "Sol"

CLAVE_ESFERA = "esfera"
RADIO_POR_DEFECTO = 100.0
# La galaxia mide unos 100 000 ly de diámetro: más que esto no es una esfera, es todo.
RADIO_MAXIMO = 100_000.0
COORDENADA_MAXIMA = 200_000.0

CLAVE_EDDN = "eddn"
CLAVE_SPANSH = "spansh"

CLAVE_RETENCION = "retencion"
VISITADOS_DIAS_POR_DEFECTO = 3.0
ANTIGUEDAD_MAXIMA_DIAS_POR_DEFECTO = 30.0
DIAS_DE_RETENCION_MAXIMOS = 365.0

CLAVE_COMERCIO = "comercio"
# Tope de la antigüedad que un perfil de búsqueda puede pedir. Sin él, una búsqueda
# de un año carga toda la base en memoria (E-16). Más de 30 días no tiene sentido:
# la retención por defecto ya los borra.
TOPE_ANTIGUEDAD_DIAS_POR_DEFECTO = 7
TOPE_ANTIGUEDAD_DIAS_MAXIMO = 30
# Los del filtro de búsqueda, en su orden canónico (decisiones.md, «Fase 5»). Los
# Fleet Carriers no están: quedan fuera hasta después de la v1.
TIPOS_DE_ESTACION = (
    "orbital",
    "puesto_avanzado",
    "puerto_planetario",
    "asentamiento",
    "colonizacion",
)
# Confianza según la antigüedad (7.2, paso 7): plena hasta 1 h, mínima desde 24 h.
CONFIANZA_POR_DEFECTO = (1.0, 24.0, 0.5)
CONFIANZA_HORAS_MAXIMAS = TOPE_ANTIGUEDAD_DIAS_MAXIMO * 24.0


def _seccion_journal(config: Path) -> dict:
    seccion = archivo.leer_o_vacio(config).get(CLAVE_JOURNAL)
    return seccion if isinstance(seccion, dict) else {}


def carpeta_journal(config: Path) -> str | None:
    """Carpeta elegida a mano, o None para la detección automática."""
    carpeta = _seccion_journal(config).get("carpeta")
    return carpeta if isinstance(carpeta, str) and carpeta else None


def dias_journal(config: Path) -> int:
    dias = _seccion_journal(config).get("dias")
    if isinstance(dias, bool) or not isinstance(dias, int):
        return DIAS_POR_DEFECTO
    return min(max(dias, DIAS_MINIMOS), DIAS_MAXIMOS)


def guardar_carpeta_journal(config: Path, carpeta: str | None) -> bool:
    """None vuelve a la detección automática. False si no se pudo guardar."""
    seccion = dict(_seccion_journal(config))
    if carpeta is None:
        seccion.pop("carpeta", None)
    else:
        seccion["carpeta"] = carpeta
    try:
        return archivo.fusionar(config, CLAVE_JOURNAL, seccion)
    except OSError:
        registro.exception("no se pudo escribir %s", config)
        return False


def _numero(valor: object) -> float | None:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    try:
        numero = float(valor)
    except OverflowError:  # un entero de JSON puede ser de cualquier tamaño
        return None
    return numero if math.isfinite(numero) else None


def _centro(seccion: dict) -> tuple[str, tuple[float, float, float]]:
    """Nombre y coordenadas; cualquier dato malo deja el Sol entero, nunca medio centro."""
    bruto = seccion.get("centro")
    if not isinstance(bruto, dict):
        return CENTRO_NOMBRE_POR_DEFECTO, CENTRO_POR_DEFECTO
    coordenadas = tuple(_numero(bruto.get(eje)) for eje in ("x", "y", "z"))
    nombre = bruto.get("nombre")
    if None in coordenadas or not isinstance(nombre, str) or not nombre.strip():
        return CENTRO_NOMBRE_POR_DEFECTO, CENTRO_POR_DEFECTO
    if any(abs(c) > COORDENADA_MAXIMA for c in coordenadas):
        return CENTRO_NOMBRE_POR_DEFECTO, CENTRO_POR_DEFECTO
    return nombre.strip(), coordenadas


def configuracion_legible(config: Path) -> bool:
    """False si config.json existe y no se pudo leer (cerrado un instante por otro programa, roto).

    Entonces `esfera()` y los plazos devuelven los valores por defecto, que no son los del
    usuario: nadie debe borrar datos basándose en ellos.
    """
    try:
        archivo.leer(config)
    except (OSError, archivo.ConfigCorrupta):
        return False
    return True


def esfera(config: Path) -> Esfera:
    """Centro y radio de interés; el usuario los puede editar en config.json."""
    seccion = archivo.leer_o_vacio(config).get(CLAVE_ESFERA)
    seccion = seccion if isinstance(seccion, dict) else {}
    nombre, centro = _centro(seccion)
    radio = _numero(seccion.get("radio"))
    if radio is None or not 0 < radio <= RADIO_MAXIMO:
        radio = RADIO_POR_DEFECTO
    return Esfera(nombre, centro, radio)


def guardar_esfera(config: Path, esfera: Esfera) -> bool:
    """False si no se pudo escribir (el valor antiguo sigue vigente en el archivo)."""
    x, y, z = esfera.centro
    valor = {
        "centro": {"nombre": esfera.nombre, "x": x, "y": y, "z": z},
        "radio": esfera.radio,
    }
    try:
        return archivo.fusionar(config, CLAVE_ESFERA, valor)
    except OSError:
        registro.exception("no se pudo escribir %s", config)
        return False


def _dias(config: Path, clave: str, por_defecto: float) -> float:
    seccion = archivo.leer_o_vacio(config).get(CLAVE_RETENCION)
    dias = _numero(seccion.get(clave)) if isinstance(seccion, dict) else None
    return dias if dias is not None and 0 < dias <= DIAS_DE_RETENCION_MAXIMOS else por_defecto


def dias_de_mercados_visitados(config: Path) -> float:
    """Cuánto se guarda un mercado visitado fuera de la esfera (regla 3 de la 5.4)."""
    return _dias(config, "visitados_dias", VISITADOS_DIAS_POR_DEFECTO)


def antiguedad_maxima_de_precios(config: Path) -> float:
    """Días tras los cuales un precio se borra, esté donde esté (regla 4 de la 5.4)."""
    return _dias(config, "antiguedad_maxima_dias", ANTIGUEDAD_MAXIMA_DIAS_POR_DEFECTO)


def antiguedad_maxima_con_memoria(
    config: Path, segundos: float = 60.0, reloj: Callable[[], float] = time.monotonic
) -> Callable[[], float]:
    """Como `antiguedad_maxima_de_precios`, pero leyendo el archivo como mucho cada `segundos`.

    EDDN la consulta con cada mensaje (decenas por segundo).
    """
    guardado: list[float] = []

    def leer() -> float:
        ahora = reloj()
        if not guardado or ahora - guardado[1] >= segundos:
            guardado[:] = [antiguedad_maxima_de_precios(config), ahora]
        return guardado[0]

    return leer


def guardar_retencion(config: Path, visitados_dias: float, antiguedad_maxima_dias: float) -> bool:
    valor = {"visitados_dias": visitados_dias, "antiguedad_maxima_dias": antiguedad_maxima_dias}
    try:
        return archivo.fusionar(config, CLAVE_RETENCION, valor)
    except OSError:
        registro.exception("no se pudo escribir %s", config)
        return False


def _seccion_comercio(config: Path) -> dict:
    seccion = archivo.leer_o_vacio(config).get(CLAVE_COMERCIO)
    return seccion if isinstance(seccion, dict) else {}


def tope_de_antiguedad_dias(config: Path) -> int:
    """Días de antigüedad que como mucho admite un perfil de búsqueda."""
    dias = _seccion_comercio(config).get("tope_antiguedad_dias")
    if isinstance(dias, bool) or not isinstance(dias, int):
        return TOPE_ANTIGUEDAD_DIAS_POR_DEFECTO
    if not 1 <= dias <= TOPE_ANTIGUEDAD_DIAS_MAXIMO:
        return TOPE_ANTIGUEDAD_DIAS_POR_DEFECTO
    return dias


def tipos_de_estacion(config: Path) -> tuple[str, ...]:
    """Los tipos que un perfil nuevo trae marcados (6.3); todos si el valor no sirve."""
    tipos = _seccion_comercio(config).get("tipos_estacion")
    if not isinstance(tipos, list) or not tipos:
        return TIPOS_DE_ESTACION
    if any(not isinstance(t, str) or t not in TIPOS_DE_ESTACION for t in tipos):
        return TIPOS_DE_ESTACION
    return tuple(t for t in TIPOS_DE_ESTACION if t in tipos)


def curva_de_confianza(config: Path) -> tuple[float, float, float]:
    """(horas_plena, horas_minima, minimo) de `comercio.confianza`; sin interfaz (decisiones.md).

    Los tres van juntos: si uno no sirve, se usan los tres por defecto.
    """
    seccion = _seccion_comercio(config).get("confianza")
    if not isinstance(seccion, dict):
        return CONFIANZA_POR_DEFECTO
    plena, minima, minimo = (
        _numero(seccion.get(c)) for c in ("horas_plena", "horas_minima", "minimo")
    )
    if plena is None or minima is None or minimo is None:
        return CONFIANZA_POR_DEFECTO
    if not 0 <= plena < minima <= CONFIANZA_HORAS_MAXIMAS or not 0 < minimo <= 1:
        return CONFIANZA_POR_DEFECTO
    return plena, minima, minimo


def guardar_busqueda(config: Path, tope_dias: int, tipos: tuple[str, ...]) -> bool:
    """El tope de antigüedad y los tipos de estación, en una sola escritura."""
    seccion = {
        **_seccion_comercio(config),
        "tope_antiguedad_dias": tope_dias,
        "tipos_estacion": list(tipos),
    }
    try:
        return archivo.fusionar(config, CLAVE_COMERCIO, seccion)
    except OSError:
        registro.exception("no se pudo escribir %s", config)
        return False


def guardar_eddn_activado(config: Path, activado: bool) -> bool:
    try:
        return archivo.fusionar(config, CLAVE_EDDN, {"activado": activado})
    except OSError:
        registro.exception("no se pudo escribir %s", config)
        return False


@dataclass(frozen=True)
class UltimaDescarga:
    fecha: str
    # La esfera con la que se descargó.
    esfera: Esfera
    # Lo que de ella sigue guardado: se encoge si luego se reduce la esfera sin descargar.
    # None si ya no es una esfera (el centro se movió y solo queda la intersección).
    cobertura: Esfera | None


def _esfera_de(seccion: dict) -> Esfera | None:
    radio = _numero(seccion.get("radio"))
    nombre, centro = _centro(seccion)
    if radio is None or not 0 < radio <= RADIO_MAXIMO:
        return None
    return Esfera(nombre, centro, radio)


def _a_dict(esfera: Esfera) -> dict:
    x, y, z = esfera.centro
    return {"centro": {"nombre": esfera.nombre, "x": x, "y": y, "z": z}, "radio": esfera.radio}


def ultima_descarga(config: Path) -> UltimaDescarga | None:
    """La esfera con que se descargó Spansh, cuándo y cuánto de ella sigue guardado."""
    seccion = archivo.leer_o_vacio(config).get(CLAVE_SPANSH)
    if not isinstance(seccion, dict) or not isinstance(seccion.get("fecha"), str):
        return None
    esfera = _esfera_de(seccion)
    if esfera is None:
        return None
    # Sin la clave (una descarga anterior a este ajuste) se supone que sigue entera.
    if "cobertura" not in seccion:
        return UltimaDescarga(seccion["fecha"], esfera, esfera)
    cobertura = seccion["cobertura"]
    return UltimaDescarga(
        seccion["fecha"], esfera, _esfera_de(cobertura) if isinstance(cobertura, dict) else None
    )


def guardar_ultima_descarga(config: Path, fecha: str, esfera: Esfera) -> bool:
    """Una descarga nueva: su cobertura es entera."""
    try:
        return archivo.fusionar(config, CLAVE_SPANSH, {"fecha": fecha, **_a_dict(esfera)})
    except OSError:
        registro.exception("no se pudo escribir %s", config)
        return False


def guardar_cobertura(config: Path, cobertura: Esfera | None) -> bool:
    """Anota lo que sigue guardado de la última descarga. False si no hay o no se pudo escribir."""
    seccion = archivo.leer_o_vacio(config).get(CLAVE_SPANSH)
    if not isinstance(seccion, dict):
        return False
    nueva = {**seccion, "cobertura": _a_dict(cobertura) if cobertura else None}
    try:
        return archivo.fusionar(config, CLAVE_SPANSH, nueva)
    except OSError:
        registro.exception("no se pudo escribir %s", config)
        return False


def eddn_activado(config: Path) -> bool:
    seccion = archivo.leer_o_vacio(config).get(CLAVE_EDDN)
    activado = seccion.get("activado") if isinstance(seccion, dict) else None
    return activado if isinstance(activado, bool) else True
