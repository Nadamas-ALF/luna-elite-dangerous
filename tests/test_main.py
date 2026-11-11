from dataclasses import dataclass, field

import pytest

import main
from core import plataforma, textos


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
    geometria = plataforma.geometria_de_forma(
        forma("Maximized", bounds=(-8, -8, 1936, 1048))
    )

    assert (geometria.x, geometria.y) == (300, 140)
    assert (geometria.ancho, geometria.alto) == (1280, 800)
    assert geometria.maximizada


def test_minimizada_no_guarda_el_tamano_diminuto():
    geometria = plataforma.geometria_de_forma(
        forma("Minimized", bounds=(-32000, -32000, 160, 28))
    )

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
        leida = plataforma.geometria_de_forma(
            forma("Normal", bounds=(x, y, ancho, alto))
        )
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
