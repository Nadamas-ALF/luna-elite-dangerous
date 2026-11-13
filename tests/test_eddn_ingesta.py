import json
import threading
import zlib
from pathlib import Path

import pytest

from core import events
from core.db import mercado
from core.db.escritor import Escritor, abrir_lectura
from core.eddn import mensaje
from core.eddn.espera import Espera
from core.eddn.ingesta import Ingesta
from core.eddn.sistemas import Conocidos
from core.esfera import Esfera
from core.journal.mercado import Articulo

FIXTURES = Path(__file__).parent / "fixtures" / "eddn"
# Sistema del Docked real de Holland Hub (a unos 373 ly del Sol).
SISTEMA = "Col 359 Sector GA-W c3-11"
MARKET_ID = 4324967683
CENTRO = (-72.0625, 220.5625, 291.3125)


def real(nombre: str) -> dict:
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


def comprimir(datos: dict) -> bytes:
    return zlib.compress(json.dumps(datos).encode("utf-8"))


def visita_real(nombre="journal_1_docked_2.json") -> bytes:
    return comprimir(real(nombre))


def mercado_real(marca="2026-11-12T22:29:28Z", sistema=SISTEMA, market_id=MARKET_ID) -> bytes:
    datos = real("commodity_3_3.json")
    datos["message"].update(timestamp=marca, systemName=sistema, marketId=market_id)
    datos["header"]["gatewayTimestamp"] = "2026-11-12T22:30:00Z"
    return comprimir(datos)


class Montaje:
    def __init__(self, tmp_path, radio=50.0, centro=CENTRO, antiguedad=None):
        self.base = tmp_path / "luna.db"
        self.escritor = Escritor(self.base)
        self.escritor.iniciar()
        self.bus = events.Bus()
        self.avisados: list[int] = []
        self.bus.suscribir(events.MERCADO_ACTUALIZADO, self.avisados.append)
        self.esfera = Esfera("Holland", centro, radio)
        self.espera = Espera()
        extra = {} if antiguedad is None else {"antiguedad": antiguedad}
        self.ingesta = Ingesta(
            self.escritor,
            self.bus,
            self.esfera,
            Conocidos(self.esfera, self.base),
            self.espera,
            **extra,
        )

    def procesar(self, *crudos: bytes) -> None:
        for crudo in crudos:
            self.ingesta.procesar(crudo)
        self.vaciar()

    def vaciar(self) -> None:
        """Espera a que el escritor termine todo lo encolado hasta ahora."""
        listo = threading.Event()
        self.escritor.encolar(lambda c: None, lambda _: listo.set())
        assert listo.wait(5)

    def consultar(self, sql: str, *parametros) -> list[tuple]:
        conexion = abrir_lectura(self.base)
        try:
            return conexion.execute(sql, parametros).fetchall()
        finally:
            conexion.close()


@pytest.fixture
def montaje(tmp_path):
    montado = Montaje(tmp_path)
    yield montado
    montado.ingesta.cerrar()
    montado.escritor.detener()


def comerciadas(crudo: bytes) -> int:
    """Mercancías que la estación realmente mueve; el resto no se guarda."""
    return sum(a.se_comercia for a in mensaje.interpretar(crudo).articulos)


def precios(montaje) -> list[tuple]:
    return montaje.consultar(
        "SELECT commodity, origen, observado FROM market_prices WHERE market_id = ? "
        "ORDER BY commodity",
        MARKET_ID,
    )


def test_un_mercado_de_un_sistema_desconocido_espera_a_su_posicion(montaje):
    montaje.procesar(mercado_real())

    assert precios(montaje) == []
    assert montaje.ingesta.pendientes() == 1

    montaje.procesar(visita_real())

    assert {fila[1] for fila in precios(montaje)} == {"eddn"}
    assert len(precios(montaje)) == comerciadas(mercado_real())
    assert montaje.ingesta.pendientes() == 0
    assert montaje.avisados == [MARKET_ID]


def test_el_mercado_guardado_trae_el_sistema_y_la_estacion_del_docked(montaje):
    montaje.procesar(visita_real(), mercado_real())

    assert montaje.consultar("SELECT nombre, x, y, z FROM systems") == [(SISTEMA, *CENTRO)]
    assert montaje.consultar("SELECT nombre, categoria, plataforma, planetaria FROM stations") == [
        ("Holland Hub", "orbital", "L", 0)
    ]


def test_un_mercado_no_pisa_la_categoria_que_dio_el_docked(montaje):
    montaje.procesar(visita_real(), mercado_real())

    assert montaje.consultar("SELECT categoria FROM stations") == [("orbital",)]


def test_un_mercado_de_una_estacion_sin_docked_queda_desconocida(montaje):
    montaje.procesar(visita_real(), mercado_real(market_id=99))

    assert montaje.consultar("SELECT categoria FROM stations WHERE market_id = 99") == [
        ("desconocida",)
    ]


def test_un_mercado_fuera_de_la_esfera_no_se_guarda(tmp_path):
    # Se mueve la esfera, no el mensaje: unas coordenadas que no caben en la dirección se rechazan.
    montaje = Montaje(tmp_path, radio=1.0, centro=(CENTRO[0] + 40, CENTRO[1], CENTRO[2]))
    try:
        montaje.procesar(visita_real(), mercado_real())

        assert montaje.consultar("SELECT COUNT(*) FROM market_prices") == [(0,)]
        assert montaje.consultar("SELECT COUNT(*) FROM systems") == [(0,)]
        assert montaje.consultar("SELECT COUNT(*) FROM stations") == [(0,)]
        assert montaje.avisados == []
        assert montaje.ingesta.resumen()["fuera_de_la_esfera"] == 1
    finally:
        montaje.ingesta.cerrar()
        montaje.escritor.detener()


def test_una_visita_fuera_de_la_esfera_no_toca_la_base(montaje):
    montaje.procesar(visita_real("journal_1_4.json"))

    assert montaje.consultar("SELECT COUNT(*) FROM systems") == [(0,)]


def test_un_sistema_ya_guardado_en_la_base_no_necesita_visita(montaje):
    sistema = mercado.Sistema(1234, SISTEMA, CENTRO, 0.0)
    montaje.escritor.encolar(lambda c: mercado.guardar_sistema(c, sistema, "2026-11-01T00:00:00Z"))
    montaje.vaciar()

    montaje.procesar(mercado_real())

    assert len(precios(montaje)) > 0
    assert montaje.ingesta.pendientes() == 0


def test_un_mercado_mas_viejo_no_pisa_a_uno_mas_reciente(montaje):
    montaje.procesar(visita_real(), mercado_real("2026-11-12T22:29:28Z"))
    antes = precios(montaje)

    montaje.procesar(mercado_real("2026-11-12T22:20:00Z"))

    assert precios(montaje) == antes
    assert montaje.ingesta.resumen()["repetido"] == 1


def test_un_mercado_mas_reciente_sustituye_al_anterior(montaje):
    montaje.procesar(visita_real(), mercado_real("2026-11-12T22:20:00Z"))

    montaje.procesar(mercado_real("2026-11-12T22:29:28Z"))

    assert {fila[2] for fila in precios(montaje)} == {"2026-11-12T22:29:28Z"}
    assert montaje.avisados == [MARKET_ID, MARKET_ID]


def test_un_dato_propio_mas_reciente_gana_a_eddn(montaje):
    montaje.procesar(visita_real())
    propio = (Articulo("gold", None, None, 1, 1, 5, 0, 1, 0, False),)
    montaje.escritor.encolar(
        lambda c: mercado.guardar_de_red(
            c,
            mercado.Sistema(3107375485706, SISTEMA, CENTRO, 0.0),
            mercado.Estacion(MARKET_ID, "Holland Hub", "orbital", "L", 1.0, False),
            propio,
            mercado.ORIGEN_PROPIO,
            "2026-11-12T23:00:00Z",
        )
    )
    montaje.vaciar()

    montaje.procesar(mercado_real("2026-11-12T22:29:28Z"))

    assert precios(montaje) == [("gold", "propio", "2026-11-12T23:00:00Z")]
    assert montaje.avisados == []


def test_el_mismo_docked_repetido_no_vuelve_a_escribir(montaje):
    montaje.procesar(visita_real())
    montaje.escritor.encolar(lambda c: c.execute("UPDATE stations SET nombre = 'tocada'"))
    montaje.vaciar()

    montaje.procesar(visita_real())

    assert montaje.consultar("SELECT nombre FROM stations") == [("tocada",)]


def test_un_docked_en_un_sistema_ya_conocido_actualiza_la_estacion(montaje):
    pequena = real("journal_1_docked_2.json")
    pequena["message"]["LandingPads"] = {"Small": 3, "Medium": 0, "Large": 0}
    montaje.procesar(comprimir(pequena))
    assert montaje.consultar("SELECT plataforma FROM stations") == [("S",)]

    montaje.procesar(visita_real())

    assert montaje.consultar("SELECT plataforma FROM stations") == [("L",)]


def test_los_descartes_se_cuentan_por_motivo(montaje):
    prueba = real("commodity_3_3.json")
    prueba["$schemaRef"] += "/test"

    montaje.procesar(comprimir(prueba), b"basura", visita_real("journal_1_4.json"))

    assert montaje.ingesta.resumen() == {
        "recibido": 3,
        "prueba": 1,
        "mal_formado": 1,
    }


def test_un_evento_sin_coordenadas_se_ignora(montaje):
    datos = real("journal_1_4.json")
    del datos["message"]["StarPos"]

    montaje.procesar(comprimir(datos))

    assert montaje.ingesta.resumen()["ignorado"] == 1


def test_la_espera_tiene_tope_y_olvida_lo_mas_antiguo(tmp_path):
    montaje = Montaje(tmp_path)
    montaje.espera = Espera(capacidad=2)
    conocidos = Conocidos(montaje.esfera, montaje.base)
    montaje.ingesta = Ingesta(
        montaje.escritor, montaje.bus, montaje.esfera, conocidos, montaje.espera
    )
    try:
        montaje.procesar(*(mercado_real(market_id=n) for n in (1, 2, 3)))

        assert montaje.ingesta.pendientes() == 2
        montaje.procesar(visita_real())
        assert {f[0] for f in montaje.consultar("SELECT market_id FROM stations")} == {
            2,
            3,
            MARKET_ID,
        }
    finally:
        montaje.ingesta.cerrar()
        montaje.escritor.detener()


def sistema_falso(**cambios) -> bytes:
    """El mismo sistema, con otra dirección coherente con sus coordenadas."""
    datos = real("journal_1_docked_2.json")
    datos["message"].update(cambios)
    return comprimir(datos)


def test_un_duplicado_del_nombre_de_un_sistema_ya_guardado_se_descarta(montaje):
    montaje.procesar(visita_real())
    real_antes = montaje.consultar("SELECT system_address, x FROM systems")
    # Misma caja (coherente con las coordenadas) y otro número de secuencia: otra dirección.
    falsa = real("journal_1_docked_2.json")["message"]["SystemAddress"] + (1 << 40)
    montaje.procesar(sistema_falso(SystemAddress=falsa))

    assert montaje.consultar("SELECT system_address, x FROM systems") == real_antes
    assert montaje.ingesta.resumen()["conflicto"] == 1


def test_el_duplicado_no_desvia_los_mercados_que_llegan_despues(montaje):
    montaje.procesar(visita_real())
    falsa = real("journal_1_docked_2.json")["message"]["SystemAddress"] + (1 << 40)
    montaje.procesar(sistema_falso(SystemAddress=falsa), mercado_real())

    direcciones = montaje.consultar("SELECT DISTINCT system_address FROM stations")
    assert direcciones == [(real("journal_1_docked_2.json")["message"]["SystemAddress"],)]
    assert len(precios(montaje)) > 0


def test_el_mismo_sistema_repetido_no_es_un_conflicto(montaje):
    montaje.procesar(visita_real(), visita_real())
    assert "conflicto" not in montaje.ingesta.resumen()


def mercado_de_hace_10_dias() -> bytes:
    return mercado_real(marca="2026-11-02T22:00:00Z")


def test_por_defecto_eddn_acepta_un_mercado_de_hace_10_dias(montaje):
    montaje.procesar(visita_real(), mercado_de_hace_10_dias())
    assert montaje.ingesta.resumen().get("guardado") == 1


def test_eddn_respeta_la_antiguedad_maxima_que_eligio_el_usuario(tmp_path):
    from datetime import timedelta

    montado = Montaje(tmp_path, antiguedad=lambda: timedelta(days=7))
    try:
        montado.procesar(visita_real(), mercado_de_hace_10_dias())
        resumen = montado.ingesta.resumen()
        assert resumen.get("fecha") == 1
        assert "guardado" not in resumen
        assert montado.consultar("SELECT COUNT(*) FROM market_prices") == [(0,)]
    finally:
        montado.ingesta.cerrar()
        montado.escritor.detener()
