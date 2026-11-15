import threading
import time

import pytest

from core.config import ajustes
from core.datos import Datos
from core.db.escritor import Escritor, abrir_lectura
from core.eddn.servicio import Servicio
from core.eddn.suscriptor import DESACTIVADO
from core.esfera import Esfera, EsferaViva
from core.mantenimiento import Mantenimiento
from core.spansh import descarga
from core.spansh.gestor import Gestor
from tests.test_spansh_descarga import Servidor
from tests.test_spansh_gestor import CONTENIDO, Frenado, esperar

SOL = Esfera("Sol", (0.0, 0.0, 0.0), 100.0)
TAMANO = 4_633_476_292


@pytest.fixture(autouse=True)
def disco_libre(monkeypatch):
    monkeypatch.setattr(descarga.shutil, "disk_usage", lambda _: type("U", (), {"free": 10**12})())


class Suscriptor:
    def __init__(self):
        self.iniciado = self.detenido = False

    def iniciar(self):
        self.iniciado = True

    def detener(self):
        self.detenido = True

    def estado(self):
        return "conectado"


class Montaje:
    def __init__(self, tmp_path, servidor=None, con_gestor=True, con_base=True):
        self.config = tmp_path / "config.json"
        self.base = tmp_path / "luna.db"
        self.escritor = Escritor(self.base)
        self.escritor.iniciar()
        self.esfera = EsferaViva(SOL)
        self.servidor = servidor or Servidor(CONTENIDO)
        self.suscriptores: list[Suscriptor] = []
        self.eddn = Servicio(self._fabrica)
        self.terminadas = 0
        self.mantenimiento = Mantenimiento(self.escritor, self.esfera, self.config)
        self.gestor = (
            Gestor(
                tmp_path / "descargas",
                self.config,
                self.escritor,
                self.esfera,
                al_terminar=self._al_terminar,
                abrir=self.servidor,
                trozo=1_000,
            )
            if con_gestor
            else None
        )
        self.datos = Datos(
            self.config,
            self.base if con_base else None,
            tmp_path / "descargas",
            self.esfera,
            self.gestor,
            self.mantenimiento,
            self.eddn,
            abrir=self._abrir_tamano,
        )

    def _fabrica(self):
        suscriptor = Suscriptor()
        self.suscriptores.append(suscriptor)
        return suscriptor

    def _al_terminar(self):
        self.terminadas += 1
        self.mantenimiento.aplicar_esfera()

    def _abrir_tamano(self, url, cabeceras):
        from tests.test_spansh_descarga import Respuesta

        return Respuesta(206, {"Content-Range": f"bytes 0-0/{TAMANO}"}, b"\x1f")

    def consultar(self, sql):
        self.escritor.detener()
        conexion = abrir_lectura(self.base)
        try:
            return conexion.execute(sql).fetchall()
        finally:
            conexion.close()


@pytest.fixture
def m(tmp_path):
    montaje = Montaje(tmp_path)
    yield montaje
    if montaje.gestor:
        montaje.gestor.cancelar()
        montaje.gestor.detener()
    montaje.escritor.detener()


def sembrar_lejano(m):
    def trabajo(c):
        c.execute(
            "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, actualizado, "
            "fuente) VALUES (1, 'Lejos', 5000, 0, 0, 5000, '2026-11-13T00:00:00Z', 'eddn')"
        )
        c.execute(
            "INSERT INTO stations (market_id, system_address, nombre, categoria, planetaria, "
            "actualizado) VALUES (9, 1, 'E', 'orbital', 0, '2026-11-13T00:00:00Z')"
        )
        c.execute(
            "INSERT INTO market_prices VALUES (9, 'gold', 0, 9, 0, 5, 0, 3, 'eddn', "
            "'2026-11-13T00:00:00Z')"
        )

    m.escritor.encolar(trabajo)


def esperar_hilo(m):
    m.gestor._hilo.join(15)


def test_la_configuracion_trae_los_valores_por_defecto(m):
    c = m.datos.configuracion()
    assert c["esfera"] == {"nombre": "Sol", "centro": [0.0, 0.0, 0.0], "radio": 100.0}
    assert c["retencion"] == {"visitados_dias": 3.0, "antiguedad_maxima_dias": 30.0}
    assert c["eddn"] == {"activado": True, "disponible": True}
    assert c["spansh_disponible"] is True


def test_sin_base_eddn_y_spansh_no_estan_disponibles(tmp_path):
    montaje = Montaje(tmp_path, con_gestor=False, con_base=False)
    try:
        c = montaje.datos.configuracion()
        assert c["eddn"]["disponible"] is False
        assert c["spansh_disponible"] is False
        assert montaje.datos.spansh()["fase"] == "inactiva"
        assert montaje.datos.reanudar() == {"error": "sin_base"}
    finally:
        montaje.escritor.detener()


def test_proponer_no_cambia_nada_y_da_tamano_y_espacio(m):
    p = m.datos.proponer_esfera("Sol", 250)
    assert p["esfera"]["radio"] == 250.0
    assert p["descarga_necesaria"] is True
    assert p["tamano"] == TAMANO
    assert p["libre"] == 10**12
    assert p["error_tamano"] is None
    assert m.esfera.actual == SOL
    assert not m.config.exists()


@pytest.mark.parametrize(
    ("nombre", "radio", "error"),
    [
        ("Nadie", 100, "desconocido"),
        ("", 100, "nombre"),
        ("Sol", 0, "radio"),
        ("Sol", "9", "radio"),
    ],
)
def test_proponer_rechaza_lo_invalido(m, nombre, radio, error):
    assert m.datos.proponer_esfera(nombre, radio) == {"error": error}


def test_si_no_se_puede_consultar_el_tamano_se_dice_pero_se_propone(tmp_path):
    montaje = Montaje(tmp_path)

    def sin_red(url, cabeceras):
        raise OSError

    montaje.datos._abrir = sin_red
    try:
        p = montaje.datos.proponer_esfera("Sol", 100)
        assert p["tamano"] is None
        assert p["error_tamano"] == "red"
        assert p["descarga_necesaria"] is True
    finally:
        montaje.escritor.detener()


def test_achicar_lo_ya_descargado_no_pide_descargar(m):
    m.datos.aplicar_esfera("Sol", 100, True)
    esperar_hilo(m)
    assert m.datos.proponer_esfera("Sol", 50)["descarga_necesaria"] is False
    assert m.datos.proponer_esfera("Sol", 200)["descarga_necesaria"] is True


def test_aplicar_sin_descargar_guarda_cambia_y_limpia_lo_que_queda_fuera(m):
    sembrar_lejano(m)
    esfera_nueva = {"nombre": "Sol", "centro": [0.0, 0.0, 0.0], "radio": 50.0}

    assert m.datos.aplicar_esfera("Sol", 50, False) == {"ok": True, "descargando": False}

    assert m.datos.configuracion()["esfera"] == esfera_nueva
    assert ajustes.esfera(m.config).radio == 50.0
    assert m.esfera.actual.radio == 50.0
    m.escritor.encolar(lambda c: None)
    assert m.consultar("SELECT count(*) FROM market_prices") == [(0,)]


def test_aplicar_con_descarga_no_limpia_hasta_que_termina(m):
    sembrar_lejano(m)
    m.mantenimiento.aplicar_esfera = lambda: pytest.fail("limpió antes de tiempo")
    m.gestor._al_terminar = m._al_terminar = lambda: None

    resultado = m.datos.aplicar_esfera("Sol", 50, True)

    assert resultado == {"ok": True, "descargando": True}
    esperar_hilo(m)


def test_tras_la_descarga_se_limpia_con_la_esfera_nueva(m):
    sembrar_lejano(m)
    m.datos.aplicar_esfera("Sol", 100, True)
    esperar_hilo(m)
    assert m.terminadas == 1
    assert m.consultar("SELECT count(*) FROM market_prices WHERE origen = 'eddn'") == [(0,)]


def test_no_se_cambia_la_esfera_con_un_trabajo_en_marcha(tmp_path):
    montaje = Montaje(tmp_path, servidor=Frenado())
    try:
        assert montaje.datos.aplicar_esfera("Sol", 100, True)["ok"]
        assert montaje.servidor.llego.wait(10)

        assert montaje.datos.aplicar_esfera("Sol", 300, False) == {"error": "ocupado"}
        assert montaje.datos.proponer_esfera("Sol", 300)["ocupado"] is True
        assert montaje.esfera.actual.radio == 100.0
    finally:
        montaje.servidor.puerta.set()
        montaje.gestor.cancelar()
        montaje.gestor.detener()
        montaje.escritor.detener()


def test_dos_cambios_a_la_vez_no_se_pisan(tmp_path, monkeypatch):
    montaje = Montaje(tmp_path, servidor=Frenado())
    guardar = ajustes.guardar_esfera
    dentro, seguir = threading.Event(), threading.Event()

    def guardar_frenado(config, esfera):
        if esfera.radio == 100.0:
            dentro.set()
            seguir.wait(10)
        return guardar(config, esfera)

    monkeypatch.setattr(ajustes, "guardar_esfera", guardar_frenado)
    resultados = {}

    def aplicar(radio, descargar):
        resultados[radio] = montaje.datos.aplicar_esfera("Sol", radio, descargar)

    primero = threading.Thread(target=aplicar, args=(100, True))
    segundo = threading.Thread(target=aplicar, args=(300, False))
    try:
        primero.start()
        assert dentro.wait(10)
        segundo.start()
        segundo.join(0.2)
        assert segundo.is_alive()

        seguir.set()
        primero.join(10)
        segundo.join(10)
        assert resultados == {100: {"ok": True, "descargando": True}, 300: {"error": "ocupado"}}
        assert montaje.esfera.actual.radio == 100.0
        assert ajustes.esfera(montaje.config).radio == 100.0
    finally:
        seguir.set()
        montaje.servidor.puerta.set()
        montaje.gestor.cancelar()
        montaje.gestor.detener()
        montaje.escritor.detener()


def test_descargar_sin_gestor_es_un_error(tmp_path):
    montaje = Montaje(tmp_path, con_gestor=False)
    try:
        assert montaje.datos.aplicar_esfera("Sol", 100, True) == {"error": "sin_base"}
        assert not montaje.config.exists()
    finally:
        montaje.escritor.detener()


def test_si_no_se_puede_guardar_la_esfera_no_se_cambia(m, monkeypatch):
    monkeypatch.setattr(ajustes, "guardar_esfera", lambda *_: False)
    assert m.datos.aplicar_esfera("Sol", 50, False) == {"error": "no_guardado"}
    assert m.esfera.actual == SOL


@pytest.mark.parametrize("descargar", [1, "si", None, 0])
def test_descargar_tiene_que_ser_un_booleano(m, descargar):
    assert m.datos.aplicar_esfera("Sol", 50, descargar) == {"error": "parametro"}
    assert m.esfera.actual == SOL


def test_guardar_la_retencion_la_escribe(m):
    assert m.datos.guardar_retencion(5, 14.5) == {"ok": True}
    assert ajustes.dias_de_mercados_visitados(m.config) == 5.0
    assert ajustes.antiguedad_maxima_de_precios(m.config) == 14.5


@pytest.mark.parametrize("valor", [0, -1, True, "3", None, 366, float("nan"), float("inf")])
def test_la_retencion_invalida_no_se_guarda(m, valor):
    assert m.datos.guardar_retencion(valor, 30) == {"error": "dias"}
    assert m.datos.guardar_retencion(3, valor) == {"error": "dias"}
    assert not m.config.exists()


def test_desactivar_eddn_lo_guarda_y_para_la_escucha(m):
    m.eddn.iniciar()
    assert m.eddn.estado() == "conectado"

    assert m.datos.establecer_eddn(False) == {"ok": True}

    assert ajustes.eddn_activado(m.config) is False
    assert m.suscriptores[0].detenido
    assert m.eddn.estado() == DESACTIVADO


def test_activar_eddn_arranca_una_escucha_nueva(m):
    m.datos.establecer_eddn(False)
    m.datos.establecer_eddn(True)
    assert ajustes.eddn_activado(m.config) is True
    assert m.eddn.estado() == "conectado"


@pytest.mark.parametrize("valor", [1, "true", None])
def test_eddn_tiene_que_ser_booleano(m, valor):
    assert m.datos.establecer_eddn(valor) == {"error": "parametro"}


def test_el_servicio_no_arranca_dos_veces_ni_falla_al_parar_sin_empezar(m):
    m.eddn.detener()
    m.eddn.iniciar()
    m.eddn.iniciar()
    assert len(m.suscriptores) == 1


def test_el_servicio_sin_nada_que_escuchar_queda_desactivado():
    servicio = Servicio(lambda: None)
    servicio.iniciar()
    assert servicio.estado() == DESACTIVADO


def test_pausar_reanudar_y_cancelar_llegan_al_gestor(tmp_path):
    montaje = Montaje(tmp_path, servidor=Frenado())
    try:
        assert montaje.datos.reanudar() == {"ok": True}
        assert montaje.servidor.llego.wait(10)
        assert montaje.datos.reanudar() == {"error": "ocupado"}

        montaje.datos.pausar()
        montaje.servidor.puerta.set()
        esperar(montaje.gestor, {"pausada"})

        montaje.datos.cancelar()
        assert montaje.datos.spansh()["fase"] == "inactiva"
    finally:
        montaje.servidor.puerta.set()
        montaje.gestor.detener()
        montaje.escritor.detener()


def test_la_limpieza_horaria_espera_si_hay_una_descarga_en_marcha(tmp_path):
    ocupado = {"si": True}
    escritor = Escritor(tmp_path / "luna.db")
    escritor.iniciar()
    try:
        manto = Mantenimiento(
            escritor,
            EsferaViva(SOL),
            tmp_path / "config.json",
            0.02,
            en_pausa=lambda: ocupado["si"],
        )
        llamadas = []
        original = manto.limpiar
        manto.limpiar = lambda: (llamadas.append(1), original())
        manto.iniciar()
        time.sleep(0.2)
        assert llamadas == []
        ocupado["si"] = False
        limite = time.monotonic() + 10
        while not llamadas and time.monotonic() < limite:
            time.sleep(0.02)
        manto.detener()
        assert llamadas
    finally:
        escritor.detener()


def test_tras_reducir_sin_descargar_ya_no_se_dice_que_lo_descargado_cubre_la_zona_borrada(m):
    m.datos.aplicar_esfera("Sol", 100, True)
    esperar_hilo(m)
    assert m.datos.aplicar_esfera("Sol", 50, False)["ok"]

    assert m.datos.proponer_esfera("Sol", 50)["descarga_necesaria"] is False
    assert m.datos.proponer_esfera("Sol", 80)["descarga_necesaria"] is True


def test_agrandar_sin_descargar_no_inventa_cobertura_nueva(m):
    m.datos.aplicar_esfera("Sol", 100, True)
    esperar_hilo(m)
    m.datos.aplicar_esfera("Sol", 150, False)
    assert m.datos.proponer_esfera("Sol", 100)["descarga_necesaria"] is False
    assert m.datos.proponer_esfera("Sol", 120)["descarga_necesaria"] is True


def test_la_propuesta_avisa_de_que_se_borrara_lo_que_quede_fuera(m):
    m.datos.aplicar_esfera("Sol", 100, True)
    esperar_hilo(m)

    achicar = m.datos.proponer_esfera("Sol", 40)
    agrandar = m.datos.proponer_esfera("Sol", 300)

    assert achicar["borra_lo_de_fuera"] is True and achicar["descarga_necesaria"] is False
    assert agrandar["borra_lo_de_fuera"] is False and agrandar["descarga_necesaria"] is True


def test_sin_ninguna_descarga_la_propuesta_no_habla_de_borrar(m):
    assert m.datos.proponer_esfera("Sol", 40)["borra_lo_de_fuera"] is False
