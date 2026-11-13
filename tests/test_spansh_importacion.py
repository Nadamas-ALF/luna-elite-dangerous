import gzip
import json
import threading
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.db import escritor as modulo_escritor
from core.db import mercado
from core.db.escritor import Escritor
from core.esfera import Esfera
from core.journal.mercado import Articulo
from core.spansh import importacion
from core.spansh.importacion import ErrorDeImportacion

FIXTURE = Path(__file__).parent / "fixtures" / "spansh" / "galaxy_stations_muestra.json"
GALAXIA = Esfera("Sol", (0.0, 0.0, 0.0), 1_000_000.0)
AHORA = datetime(2026, 12, 1, tzinfo=UTC)


@pytest.fixture
def escritor(tmp_path):
    activo = Escritor(tmp_path / "luna.db")
    activo.iniciar()
    yield activo
    activo.detener()


def consultar(escritor, sql: str, *parametros):
    with closing(modulo_escritor.abrir_lectura(escritor._ruta)) as conexion:
        return conexion.execute(sql, parametros).fetchall()


def escribir_gz(carpeta: Path, contenido: bytes) -> Path:
    archivo = carpeta / "volcado.json.gz"
    archivo.write_bytes(gzip.compress(contenido))
    return archivo


@pytest.fixture
def volcado_de_muestra(tmp_path) -> Path:
    return escribir_gz(tmp_path, FIXTURE.read_bytes())


def importar(archivo, escritor, esfera=GALAXIA, parar=None, avisos=None):
    return importacion.importar(
        archivo,
        esfera,
        escritor,
        parar or threading.Event(),
        (avisos if avisos is not None else []).append,
        AHORA,
    )


def tabla_vacia(escritor) -> bool:
    return all(
        consultar(escritor, f"SELECT count(*) FROM {t}") == [(0,)]  # noqa: S608
        for t in ("systems", "stations", "market_prices")
    )


def test_importa_los_sistemas_estaciones_y_precios(volcado_de_muestra, escritor):
    resumen = importar(volcado_de_muestra, escritor)

    assert resumen.sistemas == 10
    assert resumen.descartados == 0
    assert consultar(escritor, "SELECT count(*) FROM systems") == [(10,)]
    assert consultar(escritor, "SELECT count(*) FROM stations") == [(resumen.estaciones,)]
    assert consultar(escritor, "SELECT count(*) FROM market_prices") == [(resumen.precios,)]
    assert resumen.precios > 0


def test_los_precios_llevan_origen_spansh_y_niveles_desconocidos(volcado_de_muestra, escritor):
    importar(volcado_de_muestra, escritor)
    origenes = consultar(escritor, "SELECT DISTINCT origen FROM market_prices")
    niveles = consultar(
        escritor, "SELECT DISTINCT stock_bracket, demand_bracket FROM market_prices"
    )
    assert origenes == [("spansh",)]
    assert niveles == [(-1, -1)]


def test_al_terminar_se_borra_el_descargado_y_el_intermedio(volcado_de_muestra, escritor):
    importar(volcado_de_muestra, escritor)
    assert list(volcado_de_muestra.parent.glob("*.gz*")) == []
    assert not list(volcado_de_muestra.parent.glob("*.esfera"))


def test_solo_se_guarda_lo_que_cae_dentro_de_la_esfera(volcado_de_muestra, escritor):
    resumen = importar(volcado_de_muestra, escritor, Esfera("Cerca", (-491.6, -18.2, 1654.1), 50.0))
    nombres = consultar(escritor, "SELECT nombre FROM systems")
    assert nombres == [("HD 168444",)]
    assert resumen.leidas > resumen.sistemas
    assert consultar(escritor, "SELECT count(*) FROM stations WHERE system_address IS NULL") == [
        (0,)
    ]


def test_una_esfera_vacia_no_guarda_nada_pero_termina_bien(volcado_de_muestra, escritor):
    resumen = importar(volcado_de_muestra, escritor, Esfera("Nada", (9e4, 9e4, 9e4), 1.0))
    assert resumen.sistemas == 0
    assert tabla_vacia(escritor)
    assert not volcado_de_muestra.exists()


def test_el_progreso_cuenta_lineas_sistemas_y_guardados(volcado_de_muestra, escritor):
    avisos: list = []
    importar(volcado_de_muestra, escritor, avisos=avisos)
    ultimo = avisos[-1]
    assert (ultimo.fase, ultimo.encontrados, ultimo.guardados) == (importacion.GUARDANDO, 10, 10)
    assert {a.fase for a in avisos} == {importacion.LEYENDO, importacion.GUARDANDO}


def test_un_gzip_cortado_no_toca_la_base_y_conserva_el_archivo(tmp_path, escritor):
    completo = gzip.compress(FIXTURE.read_bytes())
    archivo = tmp_path / "volcado.json.gz"
    archivo.write_bytes(completo[: len(completo) // 2])
    with pytest.raises(ErrorDeImportacion) as error:
        importar(archivo, escritor)
    assert error.value.motivo == importacion.MOTIVO_ARCHIVO
    assert tabla_vacia(escritor)
    assert archivo.exists()
    assert not list(tmp_path.glob("*.esfera"))


def test_un_gzip_con_el_final_dañado_no_toca_la_base(tmp_path, escritor):
    completo = bytearray(gzip.compress(FIXTURE.read_bytes()))
    completo[-6] ^= 0xFF  # el CRC del final: el contenido parece bien hasta la última comprobación
    archivo = tmp_path / "volcado.json.gz"
    archivo.write_bytes(bytes(completo))
    with pytest.raises(ErrorDeImportacion) as error:
        importar(archivo, escritor)
    assert error.value.motivo == importacion.MOTIVO_ARCHIVO
    assert tabla_vacia(escritor)


def test_lo_que_no_es_un_gzip_se_rechaza(tmp_path, escritor):
    archivo = tmp_path / "volcado.json.gz"
    archivo.write_bytes(b"<html>no soy un gzip</html>")
    with pytest.raises(ErrorDeImportacion) as error:
        importar(archivo, escritor)
    assert error.value.motivo == importacion.MOTIVO_ARCHIVO


@pytest.mark.parametrize(
    "contenido",
    [
        b'{"no": "un arreglo"}\n',
        b'[\n\t{"id64":1,"name":"A","coords":{"x":1,"y":1,"z":1},"date":"2026-11-01T00:00:00Z"}\n',
        b"[\n]\n[\n]\n",
        b"",
    ],
)
def test_un_volcado_con_otra_estructura_se_rechaza(tmp_path, escritor, contenido):
    with pytest.raises(ErrorDeImportacion) as error:
        importar(escribir_gz(tmp_path, contenido), escritor)
    assert error.value.motivo == importacion.MOTIVO_FORMATO
    assert tabla_vacia(escritor)


def sistema_en_linea(numero: int, **cambios) -> bytes:
    datos = {
        "id64": numero,
        "name": f"S{numero}",
        "coords": {"x": float(numero), "y": 0.0, "z": 0.0},
        "date": "2026-11-01T10:00:00Z",
        "stations": [],
    } | cambios
    return b"\t" + json.dumps(datos, separators=(",", ":")).encode() + b",\n"


def volcado_de(*lineas: bytes) -> bytes:
    return b"[\n" + b"".join(lineas) + b"]\n"


def test_unas_pocas_lineas_rotas_se_cuentan_y_el_resto_se_guarda(tmp_path, escritor):
    lineas = [sistema_en_linea(n) for n in range(1, 301)]
    lineas[10] = b'\t{"id64":11,"name":"S11","coords":{"x":11.0,"y":0.0,"z":0.0},"date":roto,\n'
    resumen = importar(escribir_gz(tmp_path, volcado_de(*lineas)), escritor)
    assert resumen.sistemas == 299
    assert resumen.descartados == 1


def test_demasiadas_lineas_rotas_son_un_cambio_de_formato(tmp_path, escritor):
    lineas = [sistema_en_linea(n, date="ayer") for n in range(1, 301)]
    with pytest.raises(ErrorDeImportacion) as error:
        importar(escribir_gz(tmp_path, volcado_de(*lineas)), escritor)
    assert error.value.motivo == importacion.MOTIVO_FORMATO
    assert tabla_vacia(escritor)


def test_una_linea_gigante_se_salta_sin_desalinear_las_siguientes(tmp_path, escritor, monkeypatch):
    monkeypatch.setattr(importacion.volcado, "TAMANO_MAXIMO_DE_LINEA", 2000)
    gigante = sistema_en_linea(5, bodies=[{"name": "x" * 10_000}])
    resumen = importar(
        escribir_gz(tmp_path, volcado_de(sistema_en_linea(1), gigante, sistema_en_linea(2))),
        escritor,
    )
    assert resumen.sistemas == 2
    assert resumen.descartados == 1
    assert {n for (n,) in consultar(escritor, "SELECT nombre FROM systems")} == {"S1", "S2"}


def test_cancelar_mientras_se_lee_no_toca_la_base_y_conserva_el_archivo(tmp_path, escritor):
    parar = threading.Event()
    parar.set()
    lineas = [sistema_en_linea(n) for n in range(1, 3001)]
    archivo = escribir_gz(tmp_path, volcado_de(*lineas))
    assert importar(archivo, escritor, parar=parar) is None
    assert tabla_vacia(escritor)
    assert archivo.exists()
    assert not list(tmp_path.glob("*.esfera"))


def test_cancelar_mientras_se_guarda_deshace_todo(tmp_path, escritor, monkeypatch):
    monkeypatch.setattr(importacion, "SEGUNDOS_ENTRE_AVISOS", 0.0)
    parar = threading.Event()
    lineas = [sistema_en_linea(n) for n in range(1, 1001)]
    archivo = escribir_gz(tmp_path, volcado_de(*lineas))

    def avisar(progreso):
        if progreso.fase == importacion.GUARDANDO and progreso.guardados >= 400:
            parar.set()

    resultado = importacion.importar(archivo, GALAXIA, escritor, parar, avisar, AHORA)
    assert resultado is None
    assert tabla_vacia(escritor)
    assert archivo.exists()


def test_un_fallo_de_la_base_a_mitad_deshace_todo(tmp_path, escritor, monkeypatch):
    llamadas = []
    original = mercado.guardar_sistema

    def falla_en_el_tercero(conexion, sistema, observado):
        llamadas.append(sistema.system_address)
        if len(llamadas) == 3:
            raise RuntimeError("disco lleno")
        original(conexion, sistema, observado)

    monkeypatch.setattr(mercado, "guardar_sistema", falla_en_el_tercero)
    archivo = escribir_gz(tmp_path, volcado_de(*[sistema_en_linea(n) for n in range(1, 6)]))
    with pytest.raises(ErrorDeImportacion) as error:
        importar(archivo, escritor)
    assert error.value.motivo == importacion.MOTIVO_BASE
    assert tabla_vacia(escritor)
    assert archivo.exists()


def articulo(simbolo: str, demanda: int = 0, stock: int = 0, venta: int = 0) -> Articulo:
    return Articulo(simbolo, None, None, 0, venta, stock, demanda, 3, 3, False)


def estacion_conocida(escritor, categoria: str, observado: str, mercado_propio: bool = True):
    sistema = mercado.Sistema(819519, "Phua Fraae AA-A h0", (0.0, 0.0, 0.0), 0.0)
    ficha = mercado.Estacion(3708716800, "T2X-02X", categoria, None, None, False)

    def guardar(conexion):
        mercado.guardar_sistema(conexion, sistema, observado)
        mercado.guardar_estacion(conexion, ficha, sistema.system_address, observado)
        if mercado_propio:
            mercado.guardar_precios(
                conexion, ficha.market_id, (articulo("tritium", stock=5),), "propio", observado
            )

    escritor.encolar(guardar)


def test_un_mercado_mas_reciente_no_se_pisa(volcado_de_muestra, escritor):
    estacion_conocida(escritor, "fleet_carrier", "2026-11-20T00:00:00Z")
    importar(volcado_de_muestra, escritor)
    filas = consultar(
        escritor, "SELECT origen, stock FROM market_prices WHERE market_id = 3708716800"
    )
    assert filas == [("propio", 5)]


def test_un_mercado_mas_viejo_se_sustituye(volcado_de_muestra, escritor):
    estacion_conocida(escritor, "fleet_carrier", "2026-01-01T00:00:00Z")
    importar(volcado_de_muestra, escritor)
    origenes = consultar(
        escritor, "SELECT DISTINCT origen FROM market_prices WHERE market_id = 3708716800"
    )
    assert origenes == [("spansh",)]


def test_spansh_completa_una_estacion_desconocida_pero_no_pisa_una_conocida(
    volcado_de_muestra, escritor
):
    estacion_conocida(escritor, "desconocida", "2026-11-20T00:00:00Z", mercado_propio=False)
    importar(volcado_de_muestra, escritor)
    assert consultar(escritor, "SELECT categoria FROM stations WHERE market_id = 3708716800") == [
        ("fleet_carrier",)
    ]


def test_la_categoria_vista_por_el_jugador_no_se_cambia(volcado_de_muestra, escritor):
    estacion_conocida(escritor, "orbital", "2026-11-20T00:00:00Z", mercado_propio=False)
    importar(volcado_de_muestra, escritor)
    assert consultar(escritor, "SELECT categoria FROM stations WHERE market_id = 3708716800") == [
        ("orbital",)
    ]


def test_importar_dos_veces_da_lo_mismo(tmp_path, escritor):
    lineas = volcado_de(*[sistema_en_linea(n) for n in range(1, 11)])
    importar(escribir_gz(tmp_path, lineas), escritor)
    antes = consultar(escritor, "SELECT * FROM systems ORDER BY system_address")
    importar(escribir_gz(tmp_path, lineas), escritor)
    assert consultar(escritor, "SELECT * FROM systems ORDER BY system_address") == antes


def test_el_progreso_de_lectura_avanza_y_acaba_en_el_total_del_archivo(
    tmp_path, escritor, monkeypatch
):
    monkeypatch.setattr(importacion, "SEGUNDOS_ENTRE_AVISOS", 0.0)
    archivo = escribir_gz(tmp_path, volcado_de(*[sistema_en_linea(n) for n in range(1, 301)]))
    tamano = archivo.stat().st_size
    avisos: list = []
    importar(archivo, escritor, avisos=avisos)

    lecturas = [a for a in avisos if a.fase == importacion.LEYENDO]
    posiciones = [a.posicion for a in lecturas]
    assert posiciones == sorted(posiciones)
    assert lecturas[-1].posicion == lecturas[-1].total == tamano
    assert all(0 <= a.posicion <= a.total for a in avisos)


def test_el_intermedio_es_compacto_aunque_las_lineas_traigan_mucho_relleno(
    tmp_path, escritor, monkeypatch
):
    relleno = [{"name": f"cuerpo {i}", "datos": "x" * 2000} for i in range(50)]
    lineas = [sistema_en_linea(n, bodies=relleno) for n in range(1, 21)]
    archivo = escribir_gz(tmp_path, volcado_de(*lineas))
    tamanos: list[int] = []
    original = importacion._guardar

    def espiar(intermedio, *resto):
        tamanos.append(intermedio.stat().st_size)
        return original(intermedio, *resto)

    monkeypatch.setattr(importacion, "_guardar", espiar)
    importar(archivo, escritor)
    assert tamanos[0] < sum(len(linea) for linea in lineas) / 20


def estacion_con_mercado(market_id: int, actualizado: str) -> dict:
    return {
        "id": market_id,
        "name": f"E{market_id}",
        "type": "Coriolis Starport",
        "market": {
            "updateTime": actualizado,
            "commodities": [
                {"symbol": "Gold", "supply": 5, "demand": 0, "buyPrice": 9, "sellPrice": 8}
            ],
        },
    }


def test_los_mercados_mas_viejos_que_la_antiguedad_maxima_no_se_guardan(tmp_path, escritor):
    estaciones = [
        estacion_con_mercado(1, "2026-11-20T00:00:00Z"),
        estacion_con_mercado(2, "2020-06-11T00:00:00Z"),
    ]
    archivo = escribir_gz(tmp_path, volcado_de(sistema_en_linea(1, stations=estaciones)))

    resumen = importacion.importar(
        archivo, GALAXIA, escritor, threading.Event(), lambda _: None, AHORA, dias_maximos=30
    )

    assert (resumen.mercados, resumen.mercados_viejos, resumen.precios) == (1, 1, 1)
    assert consultar(escritor, "SELECT DISTINCT market_id FROM market_prices") == [(1,)]


def test_una_estacion_con_mercado_viejo_se_guarda_sin_sus_precios(tmp_path, escritor):
    archivo = escribir_gz(
        tmp_path,
        volcado_de(sistema_en_linea(1, stations=[estacion_con_mercado(2, "2020-06-11T00:00:00Z")])),
    )
    importacion.importar(
        archivo, GALAXIA, escritor, threading.Event(), lambda _: None, AHORA, dias_maximos=30
    )
    assert consultar(escritor, "SELECT market_id, categoria FROM stations") == [(2, "orbital")]
    assert consultar(escritor, "SELECT count(*) FROM market_prices") == [(0,)]


def test_un_mercado_viejo_no_pisa_a_los_precios_ya_guardados(tmp_path, escritor):
    nuevo = escribir_gz(
        tmp_path,
        volcado_de(sistema_en_linea(1, stations=[estacion_con_mercado(2, "2026-11-20T00:00:00Z")])),
    )
    importacion.importar(nuevo, GALAXIA, escritor, threading.Event(), lambda _: None, AHORA, 30)
    viejo = escribir_gz(
        tmp_path,
        volcado_de(sistema_en_linea(1, stations=[estacion_con_mercado(2, "2020-06-11T00:00:00Z")])),
    )
    importacion.importar(viejo, GALAXIA, escritor, threading.Event(), lambda _: None, AHORA, 30)
    assert consultar(escritor, "SELECT observado FROM market_prices") == [("2026-11-20T00:00:00Z",)]


def test_sin_antiguedad_maxima_se_guarda_todo(tmp_path, escritor):
    archivo = escribir_gz(
        tmp_path,
        volcado_de(sistema_en_linea(1, stations=[estacion_con_mercado(2, "2020-06-11T00:00:00Z")])),
    )
    resumen = importar(archivo, escritor)
    assert (resumen.mercados, resumen.mercados_viejos) == (1, 0)
