"""La `SystemAddress` de un sistema codifica dónde está.

El juego divide la galaxia en sectores de 1280 ly y estos en cajas cuyo lado
depende del «código de masa» (10 ly × 2^código). La dirección guarda sector y
caja en bits fijos, así que unas coordenadas que no caben en la caja de su
propia dirección son falsas o están corruptas.

No identifica un sistema falso con coordenadas coherentes; eso lo cubre la
jerarquía de fuentes (`core/db/mercado.py`).
"""

from __future__ import annotations

# El Sol cae en el sector (39, 32, 18) y el origen de la cuadrícula está en este punto.
_ORIGEN = (-65.0, -25.0, -1065.0)
_SECTOR_DEL_SOL = (39, 32, 18)
_LADO_DE_SECTOR = 1280.0
_TOLERANCIA = 0.01


def caja(system_address: int) -> tuple[tuple[float, float, float], float]:
    """Esquina mínima y lado de la caja que codifica la dirección."""
    codigo = system_address & 7
    resto = system_address >> 3

    def tomar(bits: int) -> int:
        nonlocal resto
        valor = resto & ((1 << bits) - 1)
        resto >>= bits
        return valor

    caja_z, sector_z = tomar(7 - codigo), tomar(7)
    caja_y, sector_y = tomar(7 - codigo), tomar(6)
    caja_x, sector_x = tomar(7 - codigo), tomar(7)
    lado = 10.0 * (1 << codigo)
    sectores = (sector_x, sector_y, sector_z)
    cajas = (caja_x, caja_y, caja_z)
    esquina = tuple(
        _ORIGEN[i] + (sectores[i] - _SECTOR_DEL_SOL[i]) * _LADO_DE_SECTOR + cajas[i] * lado
        for i in range(3)
    )
    return esquina, lado  # type: ignore[return-value]


def es_coherente(system_address: int, posicion: tuple[float, float, float]) -> bool:
    esquina, lado = caja(system_address)
    return all(
        esquina[i] - _TOLERANCIA <= posicion[i] <= esquina[i] + lado + _TOLERANCIA
        for i in range(3)
    )
