import json
import threading
import time
import zlib
from types import SimpleNamespace

import pytest
import zmq

from core.eddn import suscriptor
from core.eddn.suscriptor import Suscriptor


class IngestaFalsa:
    def __init__(self):
        self.recibidos: list[bytes] = []
        self.cerrada = False
        self.fallar_con: Exception | None = None

    def procesar(self, crudo: bytes) -> None:
        if self.fallar_con is not None:
            raise self.fallar_con
        self.recibidos.append(crudo)

    def resumen(self) -> dict:
        return {"recibido": len(self.recibidos)}

    def pendientes(self) -> int:
        return 0

    def cerrar(self) -> None:
        self.cerrada = True


def esperar(condicion, segundos: float = 5.0) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture(autouse=True)
def tiempos_cortos(monkeypatch):
    monkeypatch.setattr(suscriptor, "ESPERA_DE_LECTURA_MS", 20)
    monkeypatch.setattr(suscriptor, "ESPERA_BASE", 0.05)


@pytest.fixture
def relay():
    """Un relay falso: un PUB en un transporte en proceso, sin abrir ningún puerto."""
    contexto = zmq.Context.instance()
    publicador = contexto.socket(zmq.PUB)
    direccion = f"inproc://eddn-{time.monotonic_ns()}"
    publicador.bind(direccion)
    yield publicador, direccion
    publicador.close(linger=0)


def publicar_hasta_recibir(publicador, ingesta, crudo=b"x", esperado=1) -> bool:
    """Un SUB que acaba de conectar se pierde los primeros mensajes: se reenvía hasta que llegan."""
    limite = time.monotonic() + 5
    while time.monotonic() < limite and len(ingesta.recibidos) < esperado:
        publicador.send(crudo)
        time.sleep(0.02)
    return len(ingesta.recibidos) >= esperado


@pytest.fixture
def arrancado(relay):
    publicador, direccion = relay
    ingesta = IngestaFalsa()
    escucha = Suscriptor(ingesta, direccion, zmq.Context.instance())
    escucha.iniciar()
    yield escucha, ingesta, publicador
    escucha.detener()


def test_entrega_cada_mensaje_a_la_ingesta_y_queda_conectado(arrancado):
    escucha, ingesta, publicador = arrancado
    mensaje = zlib.compress(json.dumps({"a": 1}).encode())

    assert publicar_hasta_recibir(publicador, ingesta, mensaje)

    assert ingesta.recibidos[0] == mensaje
    assert escucha.estado() == suscriptor.CONECTADO


def test_un_mensaje_que_rompe_la_ingesta_no_mata_al_hilo(arrancado):
    escucha, ingesta, publicador = arrancado
    assert publicar_hasta_recibir(publicador, ingesta)
    ingesta.fallar_con = RuntimeError("roto")
    for _ in range(5):
        publicador.send(b"malo")
        time.sleep(0.02)
    ingesta.fallar_con = None

    assert publicar_hasta_recibir(publicador, ingesta, b"bueno", esperado=2)


def test_sin_mensajes_pasa_a_sin_datos_y_luego_reconecta(monkeypatch, relay):
    monkeypatch.setattr(suscriptor, "SIN_DATOS_TRAS", 0.1)
    monkeypatch.setattr(suscriptor, "SILENCIO_MAXIMO", 0.4)
    publicador, direccion = relay
    ingesta = IngestaFalsa()
    aperturas = []
    escucha = Suscriptor(ingesta, direccion, zmq.Context.instance())
    original = escucha._abrir
    escucha._abrir = lambda contexto: aperturas.append(1) or original(contexto)
    escucha.iniciar()
    try:
        assert esperar(lambda: escucha.estado() == suscriptor.SIN_DATOS)
        assert esperar(lambda: len(aperturas) >= 2)
        # Tras reconectar vuelve a recibir.
        assert publicar_hasta_recibir(publicador, ingesta)
        assert escucha.estado() == suscriptor.CONECTADO
    finally:
        escucha.detener()


def test_la_espera_entre_reintentos_crece_y_tiene_techo(monkeypatch):
    monkeypatch.setattr(suscriptor, "ESPERA_BASE", 5.0)
    esperas = []
    escucha = Suscriptor(IngestaFalsa(), "inproc://nada")
    escucha._parar = SimpleNamespace(wait=esperas.append, is_set=lambda: False)

    for _ in range(9):
        escucha._esperar_para_reintentar()

    assert esperas == [5, 10, 20, 40, 80, 160, 300, 300, 300]
    assert escucha.estado() == suscriptor.REINTENTANDO


def test_recibir_un_mensaje_reinicia_la_espera_progresiva(arrancado):
    escucha, ingesta, publicador = arrancado
    escucha._fallos = 4

    assert publicar_hasta_recibir(publicador, ingesta)

    assert escucha._fallos == 0


def test_una_direccion_imposible_no_mata_al_hilo(monkeypatch):
    escucha = Suscriptor(IngestaFalsa(), "esto no es una direccion")
    escucha.iniciar()
    try:
        assert esperar(lambda: escucha.estado() == suscriptor.REINTENTANDO)
    finally:
        escucha.detener()


def test_detener_para_el_hilo_y_cierra_la_ingesta(arrancado):
    escucha, ingesta, _ = arrancado

    escucha.detener()

    assert ingesta.cerrada
    assert not escucha._hilo.is_alive()


def test_el_hilo_es_demonio_y_se_llama_eddn():
    escucha = Suscriptor(IngestaFalsa(), "inproc://nada")

    assert escucha._hilo.daemon
    assert escucha._hilo.name == "eddn"
    assert isinstance(escucha._parar, threading.Event)
