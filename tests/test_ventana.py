from dataclasses import dataclass

from core.config import archivo, ventana


@dataclass
class PantallaFalsa:
    x: int
    y: int
    width: int
    height: int


# Los casos geométricos que importan: un origen en (0,0), un monitor a la
# izquierda con x negativa y uno vertical con y negativa.
PRINCIPAL = PantallaFalsa(0, 0, 1920, 1080)
CON_X_NEGATIVA = PantallaFalsa(-1920, 0, 1920, 1080)
VERTICAL_CON_Y_NEGATIVA = PantallaFalsa(1920, -836, 1080, 1920)
PANTALLAS = [PRINCIPAL, CON_X_NEGATIVA, VERTICAL_CON_Y_NEGATIVA]


def test_desde_dict_valido():
    geometria = ventana.desde_dict({"ancho": 1400, "alto": 900, "x": -1800, "y": 50})
    assert geometria == ventana.Geometria(ancho=1400, alto=900, x=-1800, y=50)


def test_desde_dict_respeta_el_minimo():
    geometria = ventana.desde_dict({"ancho": 300, "alto": 200})
    assert geometria.ancho == ventana.ANCHO_MINIMO
    assert geometria.alto == ventana.ALTO_MINIMO


def test_desde_dict_descarta_tipos_invalidos():
    geometria = ventana.desde_dict({"ancho": "1400", "alto": None, "x": 1.5, "y": True})
    assert geometria == ventana.POR_DEFECTO


def test_desde_dict_acepta_coordenada_cero():
    geometria = ventana.desde_dict({"ancho": 1200, "alto": 700, "x": 0, "y": 0})
    assert (geometria.x, geometria.y) == (0, 0)


def test_desde_dict_ignora_una_coordenada_suelta():
    geometria = ventana.desde_dict({"ancho": 1200, "alto": 700, "x": 100})
    assert geometria.x is None
    assert geometria.y is None


def test_desde_dict_con_basura():
    assert ventana.desde_dict(None) == ventana.POR_DEFECTO
    assert ventana.desde_dict([1, 2]) == ventana.POR_DEFECTO


def test_el_viaje_de_ida_y_vuelta_conserva_todo():
    original = ventana.Geometria(1400, 900, x=-1800, y=60, maximizada=True)
    assert ventana.desde_dict(ventana.a_dict(original)) == original


def test_esta_a_la_vista_en_la_pantalla_principal():
    assert ventana._esta_a_la_vista(ventana.Geometria(1280, 800, x=100, y=100), PANTALLAS)


def test_esta_a_la_vista_con_coordenadas_negativas():
    assert ventana._esta_a_la_vista(ventana.Geometria(1280, 800, x=-1500, y=200), PANTALLAS)


def test_esta_a_la_vista_en_el_monitor_vertical():
    assert ventana._esta_a_la_vista(ventana.Geometria(1000, 900, x=1950, y=-800), PANTALLAS)


def test_no_esta_a_la_vista_si_el_monitor_desaparecio():
    assert not ventana._esta_a_la_vista(ventana.Geometria(1280, 800, x=4000, y=2000), PANTALLAS)


def test_no_esta_a_la_vista_con_la_barra_de_titulo_por_encima():
    # Solapa la pantalla, pero la barra de título queda fuera y no habría forma
    # de arrastrarla.
    assert not ventana._esta_a_la_vista(ventana.Geometria(1280, 800, x=100, y=-200), PANTALLAS)


def test_no_esta_a_la_vista_sin_coordenadas():
    assert not ventana._esta_a_la_vista(ventana.Geometria(1280, 800), PANTALLAS)


def test_recortar_usa_una_sola_pantalla():
    """Mezclar el ancho de un monitor con el alto de otro daba un cuadrado de
    1920x1920, que no cabe en ninguno de los dos."""
    recortada = ventana._recortar(ventana.Geometria(99999, 99999, x=10, y=10), PANTALLAS)
    assert (recortada.ancho, recortada.alto) == (1920, 1080)


def test_recortar_contra_el_monitor_vertical():
    recortada = ventana._recortar(ventana.Geometria(99999, 99999, x=2000, y=-700), PANTALLAS)
    assert (recortada.ancho, recortada.alto) == (1080, 1920)


def test_recortar_no_agranda():
    original = ventana.Geometria(1024, 768, x=10, y=10)
    assert ventana._recortar(original, PANTALLAS) == original


def test_recortar_sin_pantallas_no_toca_nada():
    original = ventana.Geometria(1280, 800, x=10, y=20)
    assert ventana._recortar(original, []) == original


def test_cargar_sin_config(tmp_path):
    assert ventana.cargar(tmp_path / "config.json", PANTALLAS) == ventana.POR_DEFECTO


def test_cargar_con_config_danada(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{ esto no es json", encoding="utf-8")
    assert ventana.cargar(config, PANTALLAS) == ventana.POR_DEFECTO


def test_cargar_centra_una_posicion_fuera_de_pantalla(tmp_path):
    config = tmp_path / "config.json"
    archivo.escribir(config, {"ventana": {"ancho": 1300, "alto": 850, "x": 9000, "y": 9000}})

    assert ventana.cargar(config, PANTALLAS) == ventana.Geometria(1300, 850)


def test_cargar_conserva_el_estado_maximizado_al_centrar(tmp_path):
    config = tmp_path / "config.json"
    archivo.escribir(
        config,
        {"ventana": {"ancho": 1300, "alto": 850, "x": 9000, "y": 9000, "maximizada": True}},
    )

    assert ventana.cargar(config, PANTALLAS).maximizada


def test_guardar_y_cargar_mantienen_posicion_y_estado(tmp_path):
    config = tmp_path / "config.json"
    original = ventana.Geometria(1400, 900, x=-1800, y=60, maximizada=True)

    ventana.guardar(config, original)

    assert ventana.cargar(config, PANTALLAS) == original


def test_guardar_no_borra_otras_claves(tmp_path):
    config = tmp_path / "config.json"
    archivo.escribir(config, {"radio_esfera": 150})

    ventana.guardar(config, ventana.Geometria(1280, 800, x=10, y=20))

    assert archivo.leer(config)["radio_esfera"] == 150
