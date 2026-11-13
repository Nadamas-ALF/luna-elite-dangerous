import pytest

from core.db import mercado
from core.db.escritor import Escritor
from core.db.mercado import Estacion
from core.eddn.espera import Espera
from core.eddn.mensaje import MercadoDeRed, Visita
from core.eddn.sistemas import Conocidos
from core.esfera import Esfera, EsferaViva

ESFERA = Esfera("Sol", (0.0, 0.0, 0.0), 100.0)


def mercado_de(market_id: int, sistema="Sol", observado="2026-11-12T22:00:00Z") -> MercadoDeRed:
    estacion = Estacion(market_id, f"E{market_id}", "desconocida", None, None, False)
    return MercadoDeRed(sistema, estacion, observado, ())


def visita(nombre: str, direccion: int, posicion=(1.0, 2.0, 3.0)) -> Visita:
    return Visita(nombre, direccion, posicion, "2026-11-12T22:00:00Z", None)


class Reloj:
    def __init__(self):
        self.ahora = 0.0

    def __call__(self) -> float:
        return self.ahora


def test_la_espera_olvida_lo_que_pasa_de_su_vida():
    reloj = Reloj()
    espera = Espera(vida=60, reloj=reloj)
    espera.guardar(mercado_de(1))
    reloj.ahora = 61
    espera.guardar(mercado_de(2))

    assert len(espera) == 1
    assert [m.estacion.market_id for m in espera.liberar("Sol")] == [2]


def test_liberar_solo_saca_los_del_sistema_pedido():
    espera = Espera()
    espera.guardar(mercado_de(1, "A"))
    espera.guardar(mercado_de(2, "B"))

    assert [m.estacion.market_id for m in espera.liberar("A")] == [1]
    assert len(espera) == 1


def test_por_estacion_se_queda_el_mercado_mas_reciente():
    espera = Espera()
    espera.guardar(mercado_de(1, observado="2026-11-12T22:10:00Z"))
    espera.guardar(mercado_de(1, observado="2026-11-12T22:00:00Z"))
    espera.guardar(mercado_de(1, observado="2026-11-12T22:20:00Z"))

    (unico,) = espera.liberar("Sol")
    assert unico.observado == "2026-11-12T22:20:00Z"


def test_con_tope_se_pierde_lo_mas_antiguo():
    espera = Espera(capacidad=2)
    for n in (1, 2, 3):
        espera.guardar(mercado_de(n))

    assert sorted(m.estacion.market_id for m in espera.liberar("Sol")) == [2, 3]


def test_aprender_dice_si_el_sistema_es_nuevo(tmp_path):
    conocidos = Conocidos(ESFERA, tmp_path / "luna.db")

    primera = conocidos.aprender(visita("Sol", 10))
    repetida = conocidos.aprender(visita("Sol", 10))
    cambiada = conocidos.aprender(visita("Sol", 11))

    assert primera is not None
    assert primera.distancia_centro == pytest.approx((1 + 4 + 9) ** 0.5)
    assert repetida is None
    assert cambiada is not None


def test_la_cache_tiene_tope(tmp_path):
    conocidos = Conocidos(ESFERA, tmp_path / "luna.db", capacidad=2)
    for n in range(3):
        conocidos.aprender(visita(f"S{n}", n + 1))

    assert conocidos.buscar("S0") is None  # sin base de datos tampoco está ahí
    assert conocidos.buscar("S2") is not None


def test_sin_base_de_datos_buscar_no_rompe(tmp_path):
    conocidos = Conocidos(ESFERA, tmp_path / "no-existe" / "luna.db")

    assert conocidos.buscar("Sol") is None
    conocidos.cerrar()


def test_buscar_mide_desde_el_centro_actual_no_desde_el_guardado(tmp_path):
    base = tmp_path / "luna.db"
    escritor = Escritor(base)
    escritor.iniciar()
    escritor.encolar(
        lambda c: mercado.guardar_sistema(
            c, mercado.Sistema(7, "Lejos", (300.0, 0.0, 0.0), 5.0), "2026-11-12T22:00:00Z"
        )
    )
    escritor.detener()
    conocidos = Conocidos(ESFERA, base)
    try:
        encontrado = conocidos.buscar("Lejos")

        assert encontrado.distancia_centro == pytest.approx(300.0)
        assert not ESFERA.contiene(encontrado.posicion)
    finally:
        conocidos.cerrar()


def test_lo_guardado_en_la_base_manda_sobre_un_mensaje_que_lo_contradice(tmp_path):
    base = tmp_path / "luna.db"
    escritor = Escritor(base)
    escritor.iniciar()
    escritor.encolar(
        lambda c: mercado.guardar_sistema(
            c, mercado.Sistema(7, "Cerca", (1.0, 1.0, 1.0), 1.7), "2026-11-12T22:00:00Z"
        )
    )
    escritor.detener()
    conocidos = Conocidos(ESFERA, base)
    try:
        aprendido = conocidos.aprender(visita("Falso", 7, posicion=(5000.0, 0.0, 0.0)))

        assert aprendido.nombre == "Cerca"
        assert aprendido.posicion == (1.0, 1.0, 1.0)
        assert ESFERA.contiene(aprendido.posicion)
    finally:
        conocidos.cerrar()


def test_al_cambiar_la_esfera_se_olvidan_las_distancias_recordadas(tmp_path):
    viva = EsferaViva(Esfera("Sol", (0.0, 0.0, 0.0), 100.0))
    conocidos = Conocidos(viva, tmp_path / "luna.db")
    visita = Visita("Sol", 10477373803, (30.0, 0.0, 0.0), "2026-11-12T10:00:00Z", None)
    assert conocidos.aprender(visita).distancia_centro == 30.0

    viva.cambiar(Esfera("Otro", (30.0, 0.0, 10.0), 100.0))

    # Sin base ni caché, el sistema ya no se conoce: la distancia vieja no sobrevive.
    assert conocidos.buscar("Sol") is None
    assert conocidos.aprender(visita).distancia_centro == 10.0


def test_una_esfera_fija_no_vacia_el_cache(tmp_path):
    conocidos = Conocidos(ESFERA, tmp_path / "luna.db")
    visita = Visita("Sol", 10477373803, (0.0, 0.0, 0.0), "2026-11-12T10:00:00Z", None)
    conocidos.aprender(visita)
    assert conocidos.buscar("Sol") is not None
