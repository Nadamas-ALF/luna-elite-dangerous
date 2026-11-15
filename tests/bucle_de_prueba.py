"""El bucle real de `fixtures/journal/bucle_comercio.log` guardado como lo guarda el núcleo."""

import json
import sqlite3
from pathlib import Path

from core.db import comandante
from core.journal import comercio
from core.state.estado import Estado, aplicar

BUCLE = Path(__file__).parent / "fixtures" / "journal" / "bucle_comercio.log"


def guardar_el_bucle(conexion: sqlite3.Connection) -> None:
    eventos = [
        json.loads(linea)
        for linea in BUCLE.read_text(encoding="utf-8").splitlines()
    ]
    estado, libro, operaciones, tramos = Estado(), comercio.Libro(), [], []
    for evento in eventos:
        estado = aplicar(estado, evento)
        hecha = comercio.operacion(estado, evento)
        if hecha:
            operaciones.append(("F0000001", 14, hecha))
        libro, tramo = comercio.anotar(libro, estado, evento)
        if tramo:
            tramos.append(("F0000001", tramo))
    comandante.registrar_comandante(conexion, "F0000001", "CMDR Prueba", "2026-11-10")
    comandante.guardar_operaciones(conexion, operaciones)
    comandante.guardar_tramos(conexion, tramos)
