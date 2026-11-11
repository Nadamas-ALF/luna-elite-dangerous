import json
from pathlib import Path

import pytest

from core import nave

FIXTURE = Path(__file__).parent / "fixtures" / "journal" / "loadouts.jsonl"

# Tolerancia: el journal escribe el rango con 6 decimales.
TOLERANCIA = 0.001


def loadouts() -> list[dict]:
    lineas = FIXTURE.read_text(encoding="utf-8").splitlines()
    return [json.loads(linea) for linea in lineas if linea.strip()]


def identificar(loadout: dict) -> str:
    fsd = next(m for m in loadout["Modules"] if m["Slot"] == nave.RANURA_PROPULSOR)
    partes = [loadout["Ship"], str(loadout["CargoCapacity"]), fsd.get("Item", "sin-item")]
    if "Engineering" in fsd:
        partes.append("ingenieria")
    if any(nave.PREFIJO_POTENCIADOR in m.get("Item", "") for m in loadout["Modules"]):
        partes.append("potenciador")
    return "-".join(partes)


CASOS = loadouts()
CON_POTENCIADOR = [
    c
    for c in CASOS
    if any("guardianfsdbooster_size5" in m.get("Item", "") for m in c["Modules"])
]
MEDIDO_EN_EL_JUEGO = next(
    c for c in CASOS if c["Ship"] == "panthermkii" and c["CargoCapacity"] == 1120
)


def test_el_fixture_cubre_los_casos_interesantes():
    descripciones = [identificar(caso) for caso in CASOS]
    assert any("overcharge" in d for d in descripciones), "falta un propulsor SCO"
    assert any("ingenieria" in d for d in descripciones), "falta uno con ingenieria"
    assert CON_POTENCIADOR, "falta uno con potenciador"
    assert any("overchargebooster_mkii" in d for d in descripciones), "falta el MkII"


@pytest.mark.parametrize("loadout", CASOS, ids=identificar)
def test_el_rango_maximo_coincide_con_el_del_juego(loadout):
    """La ficha tecnica del juego cuenta solo el combustible de un salto."""
    barco = nave.desde_loadout(loadout)
    assert nave.rango_maximo(barco) == pytest.approx(loadout["MaxJumpRange"], abs=TOLERANCIA)


def test_el_rango_con_deposito_lleno_coincide_con_la_medicion_en_el_juego():
    """Medido en el juego el 2026-11-11 con la Panther Clipper MkII.

    Bodega de 1120 t llena y deposito lleno: el panel marcaba 32.03 AL,
    mientras el MaxJumpRange del journal para esa nave es 49.30.
    """
    barco = nave.desde_loadout(MEDIDO_EN_EL_JUEGO)

    calculado = nave.rango(
        barco, carga=barco.capacidad_carga, combustible=barco.capacidad_combustible
    )

    assert calculado == pytest.approx(32.03, abs=0.01)


def test_el_deposito_sale_del_loadout():
    """Sin esto, el motor de la fase 5 tendria que volver al diccionario."""
    barco = nave.desde_loadout(MEDIDO_EN_EL_JUEGO)
    deposito = MEDIDO_EN_EL_JUEGO["FuelCapacity"]
    assert barco.capacidad_combustible == deposito["Main"] + deposito["Reserve"]


def test_con_menos_combustible_que_un_salto_el_rango_baja():
    """No puedes gastar en un salto mas combustible del que llevas.

    Antes, con el deposito casi vacio el calculo devolvia el rango mas alto de
    todos, porque el combustible solo entraba en la masa.
    """
    barco = nave.desde_loadout(MEDIDO_EN_EL_JUEGO)
    un_salto = barco.propulsor.combustible_por_salto

    con_un_salto = nave.rango(barco, carga=0, combustible=un_salto)
    con_la_decima_parte = nave.rango(barco, carga=0, combustible=un_salto / 10)

    # El fallo devolvia un rango MAYOR al bajar el combustible, porque este
    # solo entraba en la masa.
    assert con_la_decima_parte < con_un_salto
    assert con_la_decima_parte == pytest.approx(27.43, abs=0.01)


def test_sin_combustible_solo_queda_el_potenciador():
    barco = nave.desde_loadout(MEDIDO_EN_EL_JUEGO)
    assert nave.rango(barco, carga=0, combustible=0) == barco.bono_ly


def test_repostar_de_mas_no_mejora_el_rango():
    """Pasado un salto, el combustible solo suma masa."""
    barco = nave.desde_loadout(MEDIDO_EN_EL_JUEGO)
    un_salto = barco.propulsor.combustible_por_salto

    assert nave.rango(barco, 0, un_salto * 4) < nave.rango(barco, 0, un_salto)


def test_la_carga_reduce_el_rango():
    barco = nave.desde_loadout(MEDIDO_EN_EL_JUEGO)
    lleno = barco.capacidad_combustible
    assert nave.rango(barco, barco.capacidad_carga, lleno) < nave.rango(barco, 0, lleno)


def test_desde_loadout_lee_el_modelo_y_la_bodega():
    barco = nave.desde_loadout(MEDIDO_EN_EL_JUEGO)
    assert barco.modelo == "panthermkii"
    assert barco.capacidad_carga == 1120


def test_el_potenciador_suma_ly_fijos():
    """El bono del potenciador Guardian no se multiplica por la masa."""
    con_potenciador = CON_POTENCIADOR[0]
    sin_potenciador = {
        **con_potenciador,
        "Modules": [
            m for m in con_potenciador["Modules"] if m["Slot"] == nave.RANURA_PROPULSOR
        ],
    }

    diferencia = nave.rango_maximo(nave.desde_loadout(con_potenciador)) - nave.rango_maximo(
        nave.desde_loadout(sin_potenciador)
    )

    assert diferencia == pytest.approx(10.5)


@pytest.mark.parametrize("cambio", [{"On": False}, {"Health": 0.0}])
def test_un_potenciador_apagado_o_destruido_no_suma(cambio):
    original = CON_POTENCIADOR[0]
    alterado = {
        **original,
        "Modules": [
            {**m, **cambio} if nave.PREFIJO_POTENCIADOR in m.get("Item", "") else m
            for m in original["Modules"]
        ],
    }

    assert nave.desde_loadout(alterado).bono_ly == 0


@pytest.mark.parametrize("cambio", [{"On": False}, {"Health": 0.0}])
def test_un_propulsor_apagado_o_destruido_no_calcula_rango(cambio):
    """Antes el propulsor apagado daba rango completo, al contrario que el
    potenciador: la misma regla para los dos."""
    original = CASOS[0]
    alterado = {
        **original,
        "Modules": [
            {**m, **cambio} if m["Slot"] == nave.RANURA_PROPULSOR else m
            for m in original["Modules"]
        ],
    }

    with pytest.raises(nave.LoadoutIncompleto):
        nave.desde_loadout(alterado)


def test_la_ingenieria_de_masa_optima_se_aplica():
    con_ingenieria = next(
        c
        for c in CASOS
        if "Engineering" in next(m for m in c["Modules"] if m["Slot"] == nave.RANURA_PROPULSOR)
    )
    modulo = next(m for m in con_ingenieria["Modules"] if m["Slot"] == nave.RANURA_PROPULSOR)

    modificada = nave._propulsor_de_modulo(modulo)
    base = nave._propulsor_de_modulo({"Item": modulo["Item"]})

    assert modificada.masa_optima > base.masa_optima


def test_propulsor_desconocido():
    with pytest.raises(nave.PropulsorDesconocido):
        nave._propulsor_de_modulo({"Item": "int_hyperdrive_size9_class9"})


def test_un_modificador_absurdo_no_devuelve_un_numero_complejo():
    """Una potencia fraccionaria de una base negativa da un complejo en Python."""
    with pytest.raises(ValueError):
        nave.Propulsor(
            masa_optima=-1,
            combustible_por_salto=5.0,
            multiplicador=0.012,
            exponente=2.45,
        )


def test_un_loadout_sin_propulsor_avisa_en_vez_de_romper():
    """Sin default, next() lanzaria StopIteration y mataria el hilo lector."""
    with pytest.raises(nave.LoadoutIncompleto):
        nave.desde_loadout({"Ship": "python", "UnladenMass": 400.0, "Modules": []})


@pytest.mark.parametrize("campo", ["UnladenMass", "CargoCapacity", "FuelCapacity"])
def test_un_loadout_truncado_avisa(campo):
    incompleto = {k: v for k, v in MEDIDO_EN_EL_JUEGO.items() if k != campo}
    with pytest.raises(nave.LoadoutIncompleto):
        nave.desde_loadout(incompleto)


def test_un_campo_con_texto_en_vez_de_numero_avisa():
    raro = {**MEDIDO_EN_EL_JUEGO, "CargoCapacity": "mucho"}
    with pytest.raises(nave.LoadoutIncompleto):
        nave.desde_loadout(raro)


def test_una_nave_imposible_no_se_puede_construir():
    with pytest.raises(ValueError):
        nave.Nave(
            modelo="prueba",
            masa_vacia=-10.0,
            capacidad_carga=0,
            capacidad_combustible=8.0,
            propulsor=nave.Propulsor(1050, 5.0, 0.012, 2.45),
        )


@pytest.mark.parametrize(
    "argumentos", [{"carga": -1, "combustible": 8}, {"carga": 0, "combustible": -1}]
)
def test_valores_negativos(argumentos):
    with pytest.raises(ValueError):
        nave.rango(nave.desde_loadout(CASOS[0]), **argumentos)
