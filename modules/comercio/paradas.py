"""El detalle de una ruta organizado por parada (prefase 8, bloque 4).

Funciones puras sobre los diccionarios que ya devuelve `salida`: cada estación sale una
sola vez, con lo que se vende al llegar y lo que se compra al salir, y el trayecto va en
la parada a la que llega. El mismo modelo vale para un salto, un bucle o, en la fase 8,
una cadena de K tramos. Solo números, códigos y nombres propios: las frases son de la
interfaz.
"""

from __future__ import annotations

MODO_UN_SALTO = "un_salto"
MODO_BUCLE = "bucle"
MODO_VENTA = "venta"

_TOTALES_DE_COMERCIO = (
    "ganancia_hora",
    "ganancia_viaje",
    "ganancia_sesion",
    "segundos",
    "distancia_ly",
    "confianza",
)


def _estacion(lado: dict) -> dict:
    return {
        clave: lado[clave]
        for clave in (
            "market_id",
            "estacion",
            "sistema",
            "distancia_ls",
            "planetaria",
            "distancia_origen",
        )
    }


def _trayecto(datos: dict) -> dict:
    return {
        "distancia_ly": datos["distancia_ly"],
        "saltos": datos["saltos"],
        "segundos": datos["segundos"],
        "tiempo": datos["tiempo"],
    }


def _procedencia(lado: dict) -> dict:
    return {clave: lado[clave] for clave in ("precio", "origen", "observado", "horas")}


def _compra(tramo: dict) -> dict:
    lado = tramo["compra"]
    return {
        "mercancia": tramo["mercancia"],
        **_procedencia(lado),
        "stock": lado["cantidad"],
        "toneladas": tramo["toneladas"],
    }


def _venta(tramo: dict) -> dict:
    lado = tramo["venta"]
    return {
        "mercancia": tramo["mercancia"],
        **_procedencia(lado),
        "demanda": lado["cantidad"],
        "toneladas": tramo["toneladas"],
        "ingreso": tramo["toneladas"] * lado["precio"],
        "ganancia_tonelada": tramo["ganancia_tonelada"],
        "ganancia": tramo["ganancia_viaje"],
    }


def _parada(lado: dict) -> dict:
    return {"estacion": _estacion(lado), "llegada": None, "vender": [], "comprar": []}


def _comprobar_cadena(tramos: list[dict], cerrada: bool) -> None:
    if not tramos:
        raise ValueError("una ruta necesita al menos un tramo")
    for anterior, siguiente in zip(tramos, tramos[1:], strict=False):
        if anterior["venta"]["market_id"] != siguiente["compra"]["market_id"]:
            raise ValueError("los tramos no se encadenan")
    if cerrada and tramos[-1]["venta"]["market_id"] != tramos[0]["compra"]["market_id"]:
        raise ValueError("una ruta cerrada vuelve a su primera parada")


def de_tramos(tramos: list[dict], cerrada: bool, totales: dict) -> dict:
    """Tramos encadenados por `market_id` (formato de `salida.tramo`) a paradas.

    Abierta: una parada más que tramos. Cerrada: tantas como tramos, y el último vende
    donde el primero compra.
    """
    _comprobar_cadena(tramos, cerrada)
    paradas = [_parada(tramo["compra"]) for tramo in tramos]
    if not cerrada:
        paradas.append(_parada(tramos[-1]["venta"]))
    for i, tramo in enumerate(tramos):
        paradas[i]["comprar"].append(_compra(tramo))
        destino = paradas[(i + 1) % len(paradas)]
        destino["vender"].append(_venta(tramo))
        destino["llegada"] = _trayecto(tramo)
    return {"cerrada": cerrada, "desde_posicion": False, "totales": totales, "paradas": paradas}


def _de_venta(datos: dict) -> dict:
    """Vender la carga: una parada que se alcanza desde donde estás, sin compra."""
    lado, toneladas, ganancia = datos["venta"], datos["toneladas"], datos["ganancia"]
    por_tonelada = ganancia // toneladas if ganancia is not None and toneladas else None
    parada = _parada(lado)
    parada["llegada"] = _trayecto(datos)
    parada["vender"].append(
        {
            "mercancia": datos["mercancia"],
            **_procedencia(lado),
            "demanda": lado["cantidad"],
            "toneladas": toneladas,
            "ingreso": toneladas * lado["precio"],
            "ganancia_tonelada": por_tonelada,
            "ganancia": ganancia,
        }
    )
    totales = {
        "ingreso_hora": datos["ingreso_hora"],
        "ingreso_viaje": datos["ingreso"],
        "ganancia_viaje": ganancia,
        "segundos": datos["segundos"],
        "distancia_ly": datos["distancia_ly"],
        "confianza": datos["confianza"],
    }
    return {"cerrada": False, "desde_posicion": True, "totales": totales, "paradas": [parada]}


def detalle(modo: str, datos: dict) -> dict:
    """El detalle de un resultado de `salida`; `KeyError` o `ValueError` si no tiene la forma."""
    if modo == MODO_VENTA:
        return _de_venta(datos)
    if modo not in (MODO_UN_SALTO, MODO_BUCLE):
        raise ValueError(f"modo desconocido: {modo!r}")
    totales = {clave: datos[clave] for clave in _TOTALES_DE_COMERCIO}
    if modo == MODO_UN_SALTO:
        return de_tramos([datos], False, totales)
    return de_tramos([datos["ida"], datos["vuelta"]], True, totales)
