import urllib.error

import pytest

from core.db.escritor import Escritor
from core.esfera import Esfera
from core.spansh import cambio, descarga
from core.spansh.cambio import ErrorDeCambio
from core.spansh.descarga import ErrorDeDescarga
from tests.test_spansh_descarga import Respuesta

SOL = Esfera("Sol", (0.0, 0.0, 0.0), 100.0)


@pytest.fixture
def base(tmp_path):
    escritor = Escritor(tmp_path / "luna.db")
    escritor.iniciar()

    def sembrar(conexion):
        for direccion, nombre, x in ((1, "Colonia", -9530.0), (2, "Sagittarius A*", 25.0)):
            conexion.execute(
                "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, "
                "actualizado) VALUES (?, ?, ?, 1.0, 2.0, 0, '2026-11-01T00:00:00Z')",
                (direccion, nombre, x),
            )
        conexion.execute(
            "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, actualizado) "
            "VALUES (3, 'Sin coordenadas', NULL, NULL, NULL, NULL, 't')"
        )

    escritor.encolar(sembrar)
    escritor.detener()
    return tmp_path / "luna.db"


def test_el_sol_se_conoce_sin_base():
    esfera = cambio.resolver_centro(None, "  sol ")
    assert (esfera.nombre, esfera.centro) == ("Sol", (0.0, 0.0, 0.0))


def test_un_sistema_de_la_base_da_sus_coordenadas(base):
    esfera = cambio.resolver_centro(base, "colonia")
    assert (esfera.nombre, esfera.centro) == ("Colonia", (-9530.0, 1.0, 2.0))


def test_un_sistema_desconocido_se_dice(base):
    with pytest.raises(ErrorDeCambio) as error:
        cambio.resolver_centro(base, "Nadie")
    assert error.value.motivo == cambio.MOTIVO_DESCONOCIDO


def test_sin_base_solo_se_conoce_el_sol(tmp_path):
    with pytest.raises(ErrorDeCambio) as error:
        cambio.resolver_centro(tmp_path / "no-existe.db", "Colonia")
    assert error.value.motivo == cambio.MOTIVO_DESCONOCIDO


def test_un_sistema_sin_coordenadas_no_sirve_de_centro(base):
    with pytest.raises(ErrorDeCambio):
        cambio.resolver_centro(base, "Sin coordenadas")


def test_dos_sistemas_con_el_mismo_nombre_piden_aclarar(base):
    escritor = Escritor(base)
    escritor.iniciar()
    escritor.encolar(
        lambda c: c.execute(
            "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, actualizado) "
            "VALUES (99, 'COLONIA', 5.0, 5.0, 5.0, 0, 't')"
        )
    )
    escritor.detener()
    with pytest.raises(ErrorDeCambio) as error:
        cambio.resolver_centro(base, "Colonia")
    assert error.value.motivo == cambio.MOTIVO_AMBIGUO


@pytest.mark.parametrize("nombre", ["", "   ", None, 5, "x" * 101, ["Sol"]], ids=repr)
def test_un_nombre_invalido_se_rechaza(base, nombre):
    with pytest.raises(ErrorDeCambio) as error:
        cambio.resolver_centro(base, nombre)
    assert error.value.motivo == cambio.MOTIVO_NOMBRE


@pytest.mark.parametrize("radio", [0, -1, True, "100", None, float("nan"), float("inf"), 1e9])
def test_un_radio_invalido_se_rechaza(radio):
    with pytest.raises(ErrorDeCambio) as error:
        cambio.validar_radio(radio)
    assert error.value.motivo == cambio.MOTIVO_RADIO


def test_un_radio_valido_se_devuelve_como_decimal():
    assert cambio.validar_radio(250) == 250.0


def test_sin_descarga_previa_siempre_hace_falta():
    assert cambio.descarga_necesaria(None, SOL)


def test_achicar_la_esfera_no_pide_descargar():
    assert not cambio.descarga_necesaria(SOL, Esfera("Sol", (0.0, 0.0, 0.0), 50.0))


def test_la_misma_esfera_no_pide_descargar():
    assert not cambio.descarga_necesaria(SOL, SOL)


def test_agrandar_la_esfera_pide_descargar():
    assert cambio.descarga_necesaria(SOL, Esfera("Sol", (0.0, 0.0, 0.0), 101.0))


def test_mover_el_centro_dentro_de_lo_cubierto_no_pide_descargar():
    assert not cambio.descarga_necesaria(SOL, Esfera("Cerca", (40.0, 0.0, 0.0), 60.0))


def test_mover_el_centro_hasta_salirse_pide_descargar():
    assert cambio.descarga_necesaria(SOL, Esfera("Cerca", (40.0, 0.0, 0.0), 61.0))


def test_el_tamano_sale_del_content_range():
    def abrir(url, cabeceras):
        assert cabeceras == {"Range": "bytes=0-0"}
        return Respuesta(206, {"Content-Range": "bytes 0-0/4633476292"}, b"\x1f")

    assert cambio.tamano_del_volcado(abrir) == 4633476292


def test_si_el_servidor_ignora_el_rango_se_usa_content_length():
    def abrir(url, cabeceras):
        return Respuesta(200, {"Content-Length": "1234"}, b"")

    assert cambio.tamano_del_volcado(abrir) == 1234


def test_sin_tamano_es_un_error():
    def abrir(url, cabeceras):
        return Respuesta(200, {}, b"")

    with pytest.raises(ErrorDeDescarga):
        cambio.tamano_del_volcado(abrir)


def test_sin_red_es_un_error_de_red():
    def abrir(url, cabeceras):
        raise urllib.error.URLError("sin red")

    with pytest.raises(ErrorDeDescarga) as error:
        cambio.tamano_del_volcado(abrir)
    assert error.value.motivo == descarga.MOTIVO_RED


def test_una_esfera_cabe_dentro_de_otra_si_su_alcance_no_pasa():
    grande = Esfera("A", (0.0, 0.0, 0.0), 100.0)
    assert cambio.esfera_dentro(Esfera("B", (30.0, 0.0, 0.0), 70.0), grande)
    assert not cambio.esfera_dentro(Esfera("B", (30.0, 0.0, 0.0), 71.0), grande)
    assert cambio.esfera_dentro(grande, grande)


def test_al_reducir_sin_descargar_lo_guardado_pasa_a_ser_la_esfera_nueva():
    guardado = Esfera("Sol", (0.0, 0.0, 0.0), 100.0)
    nueva = Esfera("Sol", (0.0, 0.0, 0.0), 50.0)
    assert cambio.cobertura_tras_cambiar(guardado, nueva) == nueva


def test_al_agrandar_sin_descargar_lo_guardado_no_cambia():
    guardado = Esfera("Sol", (0.0, 0.0, 0.0), 100.0)
    assert (
        cambio.cobertura_tras_cambiar(guardado, Esfera("Sol", (0.0, 0.0, 0.0), 150.0)) == guardado
    )


def test_al_mover_el_centro_sin_descargar_ya_no_hay_garantia():
    guardado = Esfera("Sol", (0.0, 0.0, 0.0), 100.0)
    movida = Esfera("Otro", (80.0, 0.0, 0.0), 100.0)
    assert cambio.cobertura_tras_cambiar(guardado, movida) is None


def test_sin_cobertura_no_hay_nada_que_conservar():
    assert cambio.cobertura_tras_cambiar(None, Esfera("Sol", (0.0, 0.0, 0.0), 50.0)) is None


def insertar_sistema(ruta, direccion, nombre, x, fuente):
    escritor = Escritor(ruta)
    escritor.iniciar()
    escritor.encolar(
        lambda c: c.execute(
            "INSERT INTO systems (system_address, nombre, x, y, z, distancia_centro, actualizado, "
            "fuente) VALUES (?, ?, ?, 0, 0, 0, 't', ?)",
            (direccion, nombre, x, fuente),
        )
    )
    escritor.detener()


def test_un_duplicado_provisional_no_quita_el_nombre_a_un_sistema_fiable(base):
    # La fixture ya trae un «Colonia» provisional; el fiable, en otras coordenadas, es el que vale.
    insertar_sistema(base, 52, "colonia", -1234.0, "spansh")
    assert cambio.resolver_centro(base, "Colonia").centro[0] == -1234.0


def test_con_un_solo_fiable_y_duplicados_provisionales_se_elige_el_fiable(tmp_path):
    ruta = tmp_path / "luna.db"
    insertar_sistema(ruta, 1, "Rara", 5.0, "eddn")
    insertar_sistema(ruta, 2, "RARA", 6.0, "spansh")
    insertar_sistema(ruta, 3, "rara", 7.0, "eddn")
    assert cambio.resolver_centro(ruta, "rara").centro[0] == 6.0


def test_dos_fiables_con_el_mismo_nombre_siguen_siendo_ambiguos(tmp_path):
    ruta = tmp_path / "luna.db"
    insertar_sistema(ruta, 1, "Rara", 5.0, "spansh")
    insertar_sistema(ruta, 2, "Rara", 6.0, "propio")
    with pytest.raises(ErrorDeCambio) as error:
        cambio.resolver_centro(ruta, "rara")
    assert error.value.motivo == cambio.MOTIVO_AMBIGUO


def test_dos_provisionales_con_el_mismo_nombre_son_ambiguos(tmp_path):
    ruta = tmp_path / "luna.db"
    insertar_sistema(ruta, 1, "Rara", 5.0, "eddn")
    insertar_sistema(ruta, 2, "Rara", 6.0, "eddn")
    with pytest.raises(ErrorDeCambio):
        cambio.resolver_centro(ruta, "rara")
