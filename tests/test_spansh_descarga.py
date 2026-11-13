import gzip
import http.client
import random
import threading
import urllib.error
from email.message import Message

import pytest

from core.spansh import descarga
from core.spansh.descarga import Descarga, ErrorDeDescarga, Progreso

# Aleatorio para que gzip no lo comprima: los cortes de las pruebas caen dentro del archivo.
CONTENIDO = gzip.compress(random.Random(1).randbytes(100_000))  # noqa: S311 - datos de prueba reproducibles


class Respuesta:
    def __init__(self, status: int, cabeceras: dict, cuerpo: bytes, falla_tras: int | None = None):
        self.status = status
        self.headers = Message()
        for clave, valor in cabeceras.items():
            self.headers[clave] = valor
        self._cuerpo = cuerpo
        self._falla_tras = falla_tras
        self._leido = 0

    def read(self, cantidad: int) -> bytes:
        if self._falla_tras is not None and self._leido >= self._falla_tras:
            raise ConnectionResetError
        limite = cantidad
        if self._falla_tras is not None:
            limite = min(cantidad, self._falla_tras - self._leido)
        trozo = self._cuerpo[self._leido : self._leido + limite]
        self._leido += len(trozo)
        return trozo

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Servidor:
    """Contesta como Spansh: Range, If-Range y ETag, sin abrir ningún socket."""

    def __init__(self, contenido: bytes = CONTENIDO, etag: str = '"v1"'):
        self.contenido = contenido
        self.etag = etag
        self.peticiones: list[dict] = []
        self.falla_tras: int | None = None
        self.corta_en: int | None = None

    def __call__(self, url, cabeceras):
        self.peticiones.append(dict(cabeceras))
        total = len(self.contenido)
        desde = 0
        rango = cabeceras.get("Range")
        if rango and cabeceras.get("If-Range", self.etag) == self.etag:
            desde = int(rango.removeprefix("bytes=").removesuffix("-"))
        cuerpo = self.contenido[desde:]
        if self.corta_en is not None:
            cuerpo = cuerpo[: self.corta_en]
        base = {"ETag": self.etag}
        if desde:
            base["Content-Range"] = f"bytes {desde}-{total - 1}/{total}"
            return Respuesta(206, base, cuerpo, self.falla_tras)
        base["Content-Length"] = str(total)
        return Respuesta(200, base, cuerpo, self.falla_tras)


@pytest.fixture(autouse=True)
def disco_libre(monkeypatch):
    monkeypatch.setattr(descarga.shutil, "disk_usage", lambda _: type("U", (), {"free": 10**12})())


def descargar(carpeta, servidor, parar=None, **kw):
    progresos: list[Progreso] = []
    d = Descarga(carpeta, abrir=servidor, trozo=10_000, **kw)
    resultado = d.ejecutar(parar or threading.Event(), progresos.append)
    return d, resultado, progresos


def test_una_descarga_completa_deja_el_archivo_y_limpia(tmp_path):
    servidor = Servidor()
    _, resultado, progresos = descargar(tmp_path, servidor)
    assert resultado == tmp_path / descarga.NOMBRE
    assert resultado.read_bytes() == CONTENIDO
    assert sorted(p.name for p in tmp_path.iterdir()) == [descarga.NOMBRE]
    assert progresos[-1] == Progreso(len(CONTENIDO), len(CONTENIDO))
    assert "Range" not in servidor.peticiones[0]


def test_una_descarga_cortada_se_reanuda_donde_quedo(tmp_path):
    servidor = Servidor()
    servidor.falla_tras = 30_000
    with pytest.raises(ErrorDeDescarga) as error:
        descargar(tmp_path, servidor)
    assert error.value.motivo == descarga.MOTIVO_RED
    assert (tmp_path / f"{descarga.NOMBRE}.part").stat().st_size == 30_000

    servidor.falla_tras = None
    _, resultado, _ = descargar(tmp_path, servidor)
    assert resultado.read_bytes() == CONTENIDO
    assert servidor.peticiones[1]["Range"] == "bytes=30000-"
    assert servidor.peticiones[1]["If-Range"] == '"v1"'


def test_pausar_deja_el_parcial_y_devuelve_none(tmp_path):
    parar = threading.Event()
    servidor = Servidor()
    d = Descarga(tmp_path, abrir=servidor, trozo=10_000)

    def al_progresar(progreso: Progreso) -> None:
        if progreso.descargado >= 20_000:
            parar.set()

    assert d.ejecutar(parar, al_progresar) is None
    assert not d.final.exists()
    assert (tmp_path / f"{descarga.NOMBRE}.part").stat().st_size == 20_000

    _, resultado, _ = descargar(tmp_path, servidor)
    assert resultado.read_bytes() == CONTENIDO


def test_si_el_archivo_cambio_en_el_servidor_se_empieza_de_cero(tmp_path):
    servidor = Servidor()
    servidor.falla_tras = 30_000
    with pytest.raises(ErrorDeDescarga):
        descargar(tmp_path, servidor)
    nuevo = gzip.compress(random.Random(2).randbytes(120_000))  # noqa: S311 - idem
    servidor.contenido, servidor.etag, servidor.falla_tras = nuevo, '"v2"', None
    _, resultado, _ = descargar(tmp_path, servidor)
    assert resultado.read_bytes() == nuevo


def test_un_content_range_que_no_empieza_donde_toca_se_rechaza(tmp_path):
    servidor = Servidor()
    servidor.falla_tras = 30_000
    with pytest.raises(ErrorDeDescarga):
        descargar(tmp_path, servidor)

    def mentiroso(url, cabeceras):
        return Respuesta(206, {"Content-Range": f"bytes 0-9/{len(CONTENIDO)}"}, b"0" * 10)

    with pytest.raises(ErrorDeDescarga) as error:
        descargar(tmp_path, mentiroso)
    assert error.value.motivo == descarga.MOTIVO_HTTP


def test_un_cuerpo_mas_corto_que_el_prometido_es_una_descarga_cortada(tmp_path):
    servidor = Servidor()
    servidor.corta_en = 40_000
    with pytest.raises(ErrorDeDescarga) as error:
        descargar(tmp_path, servidor)
    assert error.value.motivo == descarga.MOTIVO_CORTADA
    assert (tmp_path / f"{descarga.NOMBRE}.part").exists()


def test_lo_que_no_es_gzip_se_descarta_entero(tmp_path):
    servidor = Servidor(contenido=b"<html>no soy un gzip</html>" * 1000)
    with pytest.raises(ErrorDeDescarga) as error:
        descargar(tmp_path, servidor)
    assert error.value.motivo == descarga.MOTIVO_FORMATO
    assert list(tmp_path.iterdir()) == []


def test_sin_espacio_en_disco_no_empieza(tmp_path, monkeypatch):
    monkeypatch.setattr(descarga.shutil, "disk_usage", lambda _: type("U", (), {"free": 1000})())
    with pytest.raises(ErrorDeDescarga) as error:
        descargar(tmp_path, Servidor())
    assert error.value.motivo == descarga.MOTIVO_ESPACIO
    assert not (tmp_path / f"{descarga.NOMBRE}.part").exists()


def test_un_error_http_es_un_error_de_descarga(tmp_path):
    def falla(url, cabeceras):
        raise urllib.error.HTTPError(url, 503, "no", Message(), None)

    with pytest.raises(ErrorDeDescarga) as error:
        descargar(tmp_path, falla)
    assert error.value.motivo == descarga.MOTIVO_HTTP


def test_un_416_descarta_lo_guardado_para_empezar_de_cero(tmp_path):
    servidor = Servidor()
    servidor.falla_tras = 30_000
    with pytest.raises(ErrorDeDescarga):
        descargar(tmp_path, servidor)

    def fuera_de_rango(url, cabeceras):
        raise urllib.error.HTTPError(url, 416, "no", Message(), None)

    with pytest.raises(ErrorDeDescarga):
        descargar(tmp_path, fuera_de_rango)
    assert list(tmp_path.iterdir()) == []


def test_sin_red_es_un_error_de_red(tmp_path):
    def sin_red(url, cabeceras):
        raise http.client.RemoteDisconnected

    with pytest.raises(ErrorDeDescarga) as error:
        descargar(tmp_path, sin_red)
    assert error.value.motivo == descarga.MOTIVO_RED


def test_un_parcial_ya_completo_solo_se_renombra(tmp_path):
    servidor = Servidor()
    (tmp_path / f"{descarga.NOMBRE}.part").write_bytes(CONTENIDO)
    (tmp_path / f"{descarga.NOMBRE}.part.json").write_text(
        f'{{"url": "{descarga.URL}", "etag": "\\"v1\\"", "total": {len(CONTENIDO)}}}'
    )
    _, resultado, _ = descargar(tmp_path, servidor)
    assert resultado.read_bytes() == CONTENIDO
    assert servidor.peticiones == []


@pytest.mark.parametrize("meta", ["no es json", "[]", '{"url": "otra", "etag": null, "total": 5}'])
def test_un_parcial_con_metadatos_inservibles_se_tira(tmp_path, meta):
    (tmp_path / f"{descarga.NOMBRE}.part").write_bytes(b"basura")
    (tmp_path / f"{descarga.NOMBRE}.part.json").write_text(meta)
    servidor = Servidor()
    _, resultado, _ = descargar(tmp_path, servidor)
    assert resultado.read_bytes() == CONTENIDO
    assert "Range" not in servidor.peticiones[0]


def test_descartar_borra_el_parcial(tmp_path):
    servidor = Servidor()
    servidor.falla_tras = 30_000
    with pytest.raises(ErrorDeDescarga):
        d, *_ = descargar(tmp_path, servidor)
    Descarga(tmp_path).descartar()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "url",
    [
        "http://downloads.spansh.co.uk/galaxy_stations.json.gz",
        "https://evil.example/galaxy_stations.json.gz",
        "https://downloads.spansh.co.uk.evil.example/x",
        "https://usuario@downloads.spansh.co.uk/x",
        "https://downloads.spansh.co.uk:8443/x",
        "file:///C:/windows/win.ini",
    ],
)
def test_solo_se_acepta_https_al_servidor_de_spansh(tmp_path, url):
    with pytest.raises(ErrorDeDescarga) as error:
        Descarga(tmp_path, url=url)
    assert error.value.motivo == descarga.MOTIVO_URL


def test_una_redireccion_a_otro_servidor_se_rechaza():
    manejador = descarga._SoloSpansh()
    with pytest.raises(ErrorDeDescarga):
        manejador.redirect_request(None, None, 302, "", Message(), "https://evil.example/x")
