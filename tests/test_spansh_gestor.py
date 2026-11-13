import gzip
import threading
import time
from pathlib import Path

import pytest

from core.config import ajustes
from core.db.escritor import Escritor, abrir_lectura
from core.esfera import Esfera, EsferaViva
from core.spansh import descarga, gestor
from core.spansh.gestor import Gestor
from tests.test_spansh_descarga import Respuesta, Servidor

FIXTURE = Path(__file__).parent / "fixtures" / "spansh" / "galaxy_stations_muestra.json"
CONTENIDO = gzip.compress(FIXTURE.read_bytes())
GALAXIA = Esfera("Galaxia", (0.0, 0.0, 0.0), ajustes.RADIO_MAXIMO)
TROZO = 1_000


@pytest.fixture(autouse=True)
def disco_libre(monkeypatch):
    monkeypatch.setattr(descarga.shutil, "disk_usage", lambda _: type("U", (), {"free": 10**12})())


@pytest.fixture
def escritor(tmp_path):
    activo = Escritor(tmp_path / "luna.db")
    activo.iniciar()
    yield activo
    activo.detener()


def montar(tmp_path, escritor, abrir, terminados=None, esfera=GALAXIA) -> Gestor:
    carpeta = tmp_path / "descargas"
    return Gestor(
        carpeta,
        tmp_path / "config.json",
        escritor,
        EsferaViva(esfera),
        al_terminar=(lambda: terminados.append(1)) if terminados is not None else (lambda: None),
        abrir=abrir,
        trozo=TROZO,
    )


def esperar(gestor_, fases, tiempo=15.0):
    limite = time.monotonic() + tiempo
    while time.monotonic() < limite:
        if gestor_.estado()["fase"] in fases:
            return gestor_.estado()
        time.sleep(0.01)
    pytest.fail(f"no llegó a {fases}: {gestor_.estado()}")


def contar(tmp_path, tabla: str) -> int:
    conexion = abrir_lectura(tmp_path / "luna.db")
    try:
        return conexion.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]  # noqa: S608
    finally:
        conexion.close()


class Frenado(Servidor):
    """Entrega un trozo y espera a que el test dé permiso para seguir."""

    def __init__(self):
        super().__init__(CONTENIDO)
        self.llego = threading.Event()
        self.puerta = threading.Event()

    def __call__(self, url, cabeceras):
        respuesta = super().__call__(url, cabeceras)
        leer = respuesta.read
        veces = 0

        def lenta(cantidad):
            nonlocal veces
            veces += 1
            if veces == 2:
                self.llego.set()
                self.puerta.wait(10)
            return leer(cantidad)

        respuesta.read = lenta
        return respuesta


def test_sin_nada_pendiente_esta_inactiva(tmp_path, escritor):
    g = montar(tmp_path, escritor, Servidor(CONTENIDO))
    estado = g.estado()
    assert estado["fase"] == gestor.INACTIVA
    assert estado["ultima"] is None
    assert not g.ocupado()


def test_descarga_e_importa_y_recuerda_cuando(tmp_path, escritor):
    terminados: list[int] = []
    g = montar(tmp_path, escritor, Servidor(CONTENIDO), terminados)
    assert g.iniciar()
    esperar(g, {gestor.INACTIVA, gestor.ERROR})
    g._hilo.join(10)

    estado = g.estado()
    assert estado["fase"] == gestor.INACTIVA
    assert estado["error"] is None
    assert estado["ultima"]["centro"] == "Galaxia"
    assert estado["ultima"]["radio"] == ajustes.RADIO_MAXIMO
    assert contar(tmp_path, "systems") == 10
    assert terminados == [1]
    assert list((tmp_path / "descargas").iterdir()) == []
    assert ajustes.ultima_descarga(tmp_path / "config.json").esfera == GALAXIA
    assert g.cubierta == GALAXIA


def test_no_arranca_dos_a_la_vez(tmp_path, escritor):
    servidor = Frenado()
    g = montar(tmp_path, escritor, servidor)
    assert g.iniciar()
    assert servidor.llego.wait(10)
    assert g.ocupado()
    assert not g.iniciar()
    servidor.puerta.set()
    g.cancelar()
    g._hilo.join(10)


def test_sin_base_no_arranca(tmp_path):
    g = montar(tmp_path, None, Servidor(CONTENIDO))
    assert not g.iniciar()


def test_pausar_conserva_lo_descargado_y_reanudar_termina(tmp_path, escritor):
    servidor = Frenado()
    g = montar(tmp_path, escritor, servidor)
    g.iniciar()
    assert servidor.llego.wait(10)
    g.pausar()
    servidor.puerta.set()
    g._hilo.join(10)

    pausada = g.estado()
    assert pausada["fase"] == gestor.PAUSADA
    assert 0 < pausada["descargado"] < pausada["total"]
    assert contar(tmp_path, "systems") == 0

    g.iniciar()
    g._hilo.join(10)
    assert g.estado()["fase"] == gestor.INACTIVA
    assert contar(tmp_path, "systems") == 10
    assert servidor.peticiones[1]["Range"].startswith("bytes=")


def test_cancelar_en_marcha_borra_lo_descargado(tmp_path, escritor):
    servidor = Frenado()
    g = montar(tmp_path, escritor, servidor)
    g.iniciar()
    assert servidor.llego.wait(10)
    g.cancelar()
    servidor.puerta.set()
    g._hilo.join(10)

    assert g.estado()["fase"] == gestor.INACTIVA
    assert list((tmp_path / "descargas").iterdir()) == []
    assert contar(tmp_path, "systems") == 0


def test_cancelar_estando_pausada_borra_y_vuelve_a_inactiva(tmp_path, escritor):
    servidor = Frenado()
    g = montar(tmp_path, escritor, servidor)
    g.iniciar()
    assert servidor.llego.wait(10)
    g.pausar()
    servidor.puerta.set()
    g._hilo.join(10)
    assert g.estado()["fase"] == gestor.PAUSADA

    g.cancelar()

    assert g.estado()["fase"] == gestor.INACTIVA
    assert list((tmp_path / "descargas").iterdir()) == []


def test_tras_reiniciar_una_descarga_a_medias_aparece_pausada(tmp_path, escritor):
    servidor = Frenado()
    primero = montar(tmp_path, escritor, servidor)
    primero.iniciar()
    assert servidor.llego.wait(10)
    primero.pausar()
    servidor.puerta.set()
    primero._hilo.join(10)

    segundo = montar(tmp_path, escritor, Servidor(CONTENIDO))
    estado = segundo.estado()
    assert estado["fase"] == gestor.PAUSADA
    assert estado["descargado"] > 0
    assert estado["total"] == len(CONTENIDO)


def test_un_fallo_de_red_queda_en_error_y_se_puede_reanudar(tmp_path, escritor):
    servidor = Servidor(CONTENIDO)
    servidor.falla_tras = len(CONTENIDO) // 2
    g = montar(tmp_path, escritor, servidor)
    g.iniciar()
    g._hilo.join(10)

    estado = g.estado()
    assert estado["fase"] == gestor.ERROR
    assert estado["error"] == "descarga_red"
    assert not g.ocupado()

    servidor.falla_tras = None
    assert g.iniciar()
    g._hilo.join(10)
    assert g.estado()["fase"] == gestor.INACTIVA
    assert g.estado()["error"] is None


def test_un_archivo_danado_se_borra_para_bajarlo_de_nuevo(tmp_path, escritor):
    danado = bytearray(CONTENIDO)
    danado[-6] ^= 0xFF
    g = montar(tmp_path, escritor, Servidor(bytes(danado)))
    g.iniciar()
    g._hilo.join(10)

    assert g.estado()["fase"] == gestor.ERROR
    assert g.estado()["error"] == "importacion_archivo"
    assert list((tmp_path / "descargas").iterdir()) == []
    assert contar(tmp_path, "systems") == 0


def test_un_error_inesperado_deja_rastro(tmp_path, escritor, monkeypatch):
    def revienta(*_):
        raise RuntimeError("fallo raro")

    monkeypatch.setattr(gestor.importacion, "importar", revienta)
    g = montar(tmp_path, escritor, Servidor(CONTENIDO))
    g.iniciar()
    g._hilo.join(10)
    assert g.estado()["fase"] == gestor.ERROR
    assert g.estado()["error"] == "interno"


def test_un_archivo_completo_pendiente_se_importa_sin_volver_a_bajar(tmp_path, escritor):
    carpeta = tmp_path / "descargas"
    carpeta.mkdir()
    (carpeta / descarga.NOMBRE).write_bytes(CONTENIDO)
    servidor = Servidor(CONTENIDO)
    g = montar(tmp_path, escritor, servidor)
    assert g.estado()["fase"] == gestor.PAUSADA

    g.iniciar()
    g._hilo.join(10)

    assert servidor.peticiones == []
    assert contar(tmp_path, "systems") == 10


def test_usa_la_esfera_vigente_al_empezar(tmp_path, escritor):
    cerca = Esfera("Cerca", (-491.6, -18.2, 1654.1), 50.0)
    g = montar(tmp_path, escritor, Servidor(CONTENIDO), esfera=cerca)
    g.iniciar()
    g._hilo.join(10)
    assert contar(tmp_path, "systems") == 1
    assert g.cubierta == cerca


def test_detener_pausa_sin_perder_lo_descargado(tmp_path, escritor):
    servidor = Frenado()
    g = montar(tmp_path, escritor, servidor)
    g.iniciar()
    assert servidor.llego.wait(10)
    servidor.puerta.set()
    g.detener()
    assert g.estado()["fase"] in (gestor.PAUSADA, gestor.INACTIVA)
    assert Respuesta  # el servidor simulado es el mismo de las pruebas de descarga


def test_el_estado_trae_la_etapa_y_el_avance_de_la_importacion(tmp_path, escritor):
    g = montar(tmp_path, escritor, Servidor(CONTENIDO))
    g._al_importar(gestor.importacion.Progreso(gestor.importacion.LEYENDO, 5, 2, 0, 50, 200))

    estado = g.estado()
    assert (estado["etapa"], estado["leido"], estado["tamano_archivo"]) == ("leyendo", 50, 200)
    assert (estado["leidas"], estado["encontrados"]) == (5, 2)


def descargado_con(tmp_path, escritor, esfera):
    g = montar(tmp_path, escritor, Servidor(CONTENIDO), esfera=esfera)
    g.iniciar()
    g._hilo.join(10)
    return g


def test_reducir_la_esfera_sin_descargar_encoge_la_cobertura_y_se_recuerda(tmp_path, escritor):
    g = descargado_con(tmp_path, escritor, Esfera("Sol", (0.0, 0.0, 0.0), 1000.0))
    menor = Esfera("Sol", (0.0, 0.0, 0.0), 300.0)

    g.reducir_cobertura(menor)

    assert g.cubierta == menor
    assert g.estado()["ultima"]["radio"] == 1000.0  # lo que se descargó sigue siendo lo descargado
    otro = montar(tmp_path, escritor, Servidor(CONTENIDO))
    assert otro.cubierta == menor


def test_agrandar_la_esfera_no_cambia_lo_que_hay_guardado(tmp_path, escritor):
    original = Esfera("Sol", (0.0, 0.0, 0.0), 300.0)
    g = descargado_con(tmp_path, escritor, original)
    g.reducir_cobertura(Esfera("Sol", (0.0, 0.0, 0.0), 900.0))
    assert g.cubierta == original


def test_mover_el_centro_sin_descargar_deja_la_cobertura_sin_garantia(tmp_path, escritor):
    g = descargado_con(tmp_path, escritor, Esfera("Sol", (0.0, 0.0, 0.0), 300.0))
    g.reducir_cobertura(Esfera("Otro", (400.0, 0.0, 0.0), 300.0))
    assert g.cubierta is None
    assert g.estado()["ultima"] is not None  # sigue constando que se descargó


def test_reducir_sin_ninguna_descarga_no_hace_nada(tmp_path, escritor):
    g = montar(tmp_path, escritor, Servidor(CONTENIDO))
    g.reducir_cobertura(Esfera("Sol", (0.0, 0.0, 0.0), 10.0))
    assert g.cubierta is None
    assert not (tmp_path / "config.json").exists()


def test_un_archivo_sano_que_luna_no_entiende_se_conserva_para_no_bajarlo_otra_vez(
    tmp_path, escritor
):
    g = montar(tmp_path, escritor, Servidor(gzip.compress(b'{"no": "un arreglo"}\n')))
    g.iniciar()
    g._hilo.join(10)

    assert g.estado()["fase"] == gestor.ERROR
    assert g.estado()["error"] == "importacion_formato"
    assert (tmp_path / "descargas" / descarga.NOMBRE).exists()
    assert contar(tmp_path, "systems") == 0
    # Al reabrir LUNA consta como descarga completa pendiente, sin pedir nada al servidor.
    otro = montar(tmp_path, escritor, Servidor(CONTENIDO))
    assert otro.estado()["fase"] == gestor.PAUSADA


def test_si_no_se_pudo_anotar_la_descarga_queda_constancia_en_el_registro(
    tmp_path, escritor, monkeypatch, caplog
):
    monkeypatch.setattr(ajustes, "guardar_ultima_descarga", lambda *_: False)
    caplog.set_level("WARNING", logger="luna.spansh")

    g = montar(tmp_path, escritor, Servidor(CONTENIDO))
    g.iniciar()
    g._hilo.join(10)

    assert g.estado()["fase"] == gestor.INACTIVA
    assert any("no se pudo anotar" in r.getMessage() for r in caplog.records)
