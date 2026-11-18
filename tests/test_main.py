from dataclasses import dataclass, field

import pytest

import main
from core import events, plataforma, textos
from core.config.rutas import Ubicacion
from core.db.escritor import Escritor
from core.esfera import Esfera, EsferaViva


class EstadoFalso:
    """Imita un enum de .NET: lo que se compara es su str()."""

    def __init__(self, nombre: str) -> None:
        self._nombre = nombre

    def __str__(self) -> str:
        return self._nombre


@dataclass
class LimitesFalsos:
    X: int
    Y: int
    Width: int
    Height: int


@dataclass
class FormaFalsa:
    """Lo que expone un formulario de WinForms, con los valores medidos."""

    WindowState: EstadoFalso
    Bounds: LimitesFalsos
    RestoreBounds: LimitesFalsos
    puestos: list = field(default_factory=list)

    def SetBounds(self, x, y, ancho, alto):  # noqa: N802 - nombre de WinForms
        self.puestos.append((x, y, ancho, alto))


def forma(estado="Normal", bounds=(400, 200, 1100, 700), restore=(300, 140, 1280, 800)):
    return FormaFalsa(
        WindowState=EstadoFalso(estado),
        Bounds=LimitesFalsos(*bounds),
        RestoreBounds=LimitesFalsos(*restore),
    )


def test_el_enum_de_winforms_se_convierte_al_nombre_que_comparamos():
    """`geometria_de_forma` compara `str(WindowState)` con "Normal".

    Si pythonnet cambiara ese str(), la ventana dejaria de recordar su
    geometria sin un solo error, asi que la invariante se ancla a la
    dependencia como se hace con is_local_url.
    """
    import clr

    clr.AddReference("System.Windows.Forms")
    import System.Windows.Forms as WinForms

    assert str(WinForms.FormWindowState.Normal) == plataforma.ESTADO_NORMAL
    assert str(WinForms.FormWindowState.Maximized) == plataforma.ESTADO_MAXIMIZADA


def test_en_estado_normal_se_guardan_los_limites_vivos():
    """RestoreBounds se queda con los limites de creacion mientras es normal."""
    geometria = plataforma.geometria_de_forma(forma("Normal"))

    assert (geometria.x, geometria.y) == (400, 200)
    assert (geometria.ancho, geometria.alto) == (1100, 700)
    assert not geometria.maximizada


def test_maximizada_se_guardan_los_limites_de_antes_de_maximizar():
    """Bounds devuelve un rectangulo que se sale de la pantalla (-8,-8)."""
    geometria = plataforma.geometria_de_forma(forma("Maximized", bounds=(-8, -8, 1936, 1048)))

    assert (geometria.x, geometria.y) == (300, 140)
    assert (geometria.ancho, geometria.alto) == (1280, 800)
    assert geometria.maximizada


def test_minimizada_no_guarda_el_tamano_diminuto():
    geometria = plataforma.geometria_de_forma(forma("Minimized", bounds=(-32000, -32000, 160, 28)))

    assert (geometria.ancho, geometria.alto) == (1280, 800)
    assert not geometria.maximizada


def test_aplicar_geometria_usa_pixeles_fisicos():
    """Se escribe la misma propiedad que se lee, sin factores de escala."""
    destino = forma()

    plataforma.aplicar_geometria(destino, main.ventana.Geometria(1400, 900, x=-1800, y=60))

    assert destino.puestos == [(-1800, 60, 1400, 900)]


def test_aplicar_geometria_sin_posicion_conserva_la_que_tenga():
    destino = forma(bounds=(500, 300, 1000, 700))

    plataforma.aplicar_geometria(destino, main.ventana.Geometria(1400, 900))

    assert destino.puestos == [(500, 300, 1400, 900)]


def test_el_viaje_completo_de_la_geometria_no_deriva():
    """Cinco sesiones seguidas: aplicar y volver a leer no debe mover nada.

    El fallo que esto vigila era acumulativo: la ventana se desplazaba y
    cambiaba de tamano un poco en cada arranque.
    """
    geometria = main.ventana.Geometria(1400, 900, x=-1800, y=60)

    for _ in range(5):
        destino = forma()
        plataforma.aplicar_geometria(destino, geometria)
        x, y, ancho, alto = destino.puestos[-1]
        leida = plataforma.geometria_de_forma(forma("Normal", bounds=(x, y, ancho, alto)))
        assert leida == geometria
        geometria = leida


def test_texto_devuelve_none_si_falta_la_clave():
    assert textos.texto(("ventana", "inexistente"), {"ventana": {}}) is None
    assert textos.texto(("ventana", "titulo"), {"ventana": {"titulo": 5}}) is None
    assert textos.texto(("ventana", "titulo"), {"ventana": {"titulo": "LUNA"}}) == "LUNA"


def test_con_detalle_no_se_rompe_con_una_plantilla_mala():
    """Se usa dentro del manejador de errores: si lanza, no hay aviso ninguno."""
    assert textos.con_detalle(("a",), {"a": "fallo: {error}"}, "x") == "fallo: x"
    assert "x" in textos.con_detalle(("a",), {"a": "fallo: {otra}"}, "x")
    assert "x" in textos.con_detalle(("a",), {"a": "fallo: {"}, "x")
    assert textos.con_detalle(("a",), {}, "x") == "x"


def test_el_motor_de_la_interfaz_es_el_esperado():
    """Sin WebView2, pywebview cae a MSHTML y la interfaz quedaria en blanco."""
    main.comprobar_motor()


def test_se_avisa_si_el_motor_no_es_webview2(monkeypatch):
    class ModuloFalso:
        renderer = "mshtml"

    monkeypatch.setattr(main.webview, "initialize", lambda *a, **k: ModuloFalso())
    with pytest.raises(main.FaltaWebView2):
        main.comprobar_motor()


SOL = EsferaViva(Esfera("Sol", (0.0, 0.0, 0.0), 100.0))


def test_eddn_no_arranca_sin_base_de_datos(tmp_path):
    assert main.preparar_eddn(Ubicacion(tmp_path, portable=True), None, events.Bus(), SOL) is None


def test_eddn_no_arranca_si_el_usuario_lo_desactivo(tmp_path):
    (tmp_path / "config.json").write_text('{"eddn": {"activado": false}}', encoding="utf-8")
    escritor = Escritor(tmp_path / "luna.db")
    escritor.iniciar()
    try:
        ubicacion = Ubicacion(tmp_path, portable=True)
        assert main.preparar_eddn(ubicacion, escritor, events.Bus(), SOL) is None
    finally:
        escritor.detener()


def test_eddn_arranca_por_defecto_y_empieza_conectando(tmp_path):
    escritor = Escritor(tmp_path / "luna.db")
    escritor.iniciar()
    try:
        ubicacion = Ubicacion(tmp_path, portable=True)
        suscriptor = main.preparar_eddn(ubicacion, escritor, events.Bus(), SOL)

        assert suscriptor is not None
        assert suscriptor.estado() == "conectando"
    finally:
        escritor.detener()


def test_preparar_marca_la_bienvenida_solo_la_primera_vez(tmp_path, monkeypatch):
    from core.config import ajustes, rutas

    monkeypatch.setenv(rutas.VARIABLE_DE_DESARROLLO, str(tmp_path))
    monkeypatch.setattr(main, "configurar_registro", lambda _carpeta: None)
    config = tmp_path / "config.json"

    main.preparar()
    assert ajustes.bienvenida_pendiente(config)

    ajustes.terminar_bienvenida(config)
    main.preparar()
    assert not ajustes.bienvenida_pendiente(config)


def test_una_segunda_instancia_con_los_mismos_datos_se_detecta(tmp_path):
    from core import plataforma
    from core.config.rutas import Ubicacion

    nombre = main.nombre_de_instancia(Ubicacion(tmp_path, portable=True))

    assert not plataforma.hay_otra_instancia(nombre)
    assert plataforma.hay_otra_instancia(nombre)


def test_carpetas_de_datos_distintas_no_se_estorban(tmp_path):
    from core.config.rutas import Ubicacion

    una = main.nombre_de_instancia(Ubicacion(tmp_path / "a", portable=True))
    otra = main.nombre_de_instancia(Ubicacion(tmp_path / "b", portable=True))
    misma = main.nombre_de_instancia(Ubicacion(tmp_path / "A", portable=True))

    assert una != otra
    assert una == misma  # Windows no distingue mayúsculas en las rutas
    assert una.startswith("Local\\LUNA-")
