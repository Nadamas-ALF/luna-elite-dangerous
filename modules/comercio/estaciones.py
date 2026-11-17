"""Buscador de estaciones: dónde está una estación y cuánta vida tiene su mercado.

Solo lee lo guardado (nunca consulta internet) y devuelve una lista corta, no la
tabla entera. El texto lo valida Python: largo, imprimible, y los comodines de
`LIKE` se tratan como letras.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime

from modules.comercio.engine.candidatos import Edades, Posicion
from modules.comercio.engine.perfil import PerfilInvalido, nombre

LARGO_MINIMO = 2
RESULTADOS = 10
# Lo que se lee antes de ordenar por cercanía: más que esto es una búsqueda demasiado vaga.
LECTURA_MAXIMA = 500

_CONSULTA = (
    "SELECT s.market_id, s.nombre, y.nombre, s.categoria, s.planetaria, s.plataforma, "
    "s.distancia_ls, y.x, y.y, y.z, "
    "(SELECT MAX(p.observado) FROM market_prices p WHERE p.market_id = s.market_id), "
    "(s.nombre LIKE ? ESCAPE '\\' OR y.nombre LIKE ? ESCAPE '\\') "
    "FROM stations s JOIN systems y ON y.system_address = s.system_address "
    "WHERE s.nombre LIKE ? ESCAPE '\\' OR y.nombre LIKE ? ESCAPE '\\' LIMIT ?"
)


def validar(texto: object) -> str:
    """El texto a buscar, o `PerfilInvalido('texto')`."""
    try:
        limpio = nombre(texto, "texto")
    except PerfilInvalido:
        raise PerfilInvalido("texto") from None
    if len(limpio) < LARGO_MINIMO:
        raise PerfilInvalido("texto")
    return limpio


def _literal(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def tipo(categoria: str | None, planetaria: bool) -> str:
    """El tipo de estación como lo llama el filtro del perfil."""
    if categoria in ("orbital", "puesto_avanzado") and planetaria:
        return "puerto_planetario"
    return categoria or "desconocida"


def buscar(
    conexion: sqlite3.Connection, texto: str, posicion: Posicion | None, ahora: datetime
) -> dict:
    """Hasta `RESULTADOS` estaciones cuyo nombre o el de su sistema contiene `texto`.

    Primero las que empiezan por el texto y, dentro de cada grupo, las más cercanas.
    """
    contiene = f"%{_literal(texto)}%"
    empieza = f"{_literal(texto)}%"
    filas = conexion.execute(
        _CONSULTA, (empieza, empieza, contiene, contiene, LECTURA_MAXIMA + 1)
    ).fetchall()
    edades = Edades(ahora)
    encontradas = [_estacion(fila, posicion, edades) for fila in filas[:LECTURA_MAXIMA]]
    encontradas.sort(key=_orden)
    return {
        "estaciones": [e[1] for e in encontradas[:RESULTADOS]],
        "hay_mas": len(filas) > RESULTADOS,
    }


def _estacion(fila: tuple, posicion: Posicion | None, edades: Edades) -> tuple[bool, dict]:
    (
        market_id,
        estacion,
        sistema,
        categoria,
        planetaria,
        plataforma,
        ls,
        x,
        y,
        z,
        ultimo,
        empieza,
    ) = fila
    lejos = None if posicion is None or x is None else math.dist(posicion, (x, y, z))
    return bool(empieza), {
        "market_id": market_id,
        "estacion": estacion,
        "sistema": sistema,
        "tipo": tipo(categoria, bool(planetaria)),
        "plataforma": plataforma,
        "distancia_ly": lejos,
        "distancia_ls": ls,
        "observado": ultimo,
        "horas": None if ultimo is None else edades.horas(ultimo),
    }


def _orden(par: tuple[bool, dict]) -> tuple:
    empieza, datos = par
    lejos = datos["distancia_ly"]
    return (not empieza, lejos is None, lejos or 0.0, datos["estacion"].casefold())
