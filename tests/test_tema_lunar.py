"""El tema Lunar es una capa: todo cuelga de `data-tema` y el texto se lee sobre su vidrio."""

import re

from core import recursos

RAIZ = recursos.carpeta_de_recursos()
LUNAR = (RAIZ / "ui" / "css" / "lunar.css").read_text("utf-8")
SIN_COMENTARIOS = re.sub(r"/\*.*?\*/", "", LUNAR, flags=re.DOTALL)
AA = 4.5


def _color(valor: str) -> tuple[float, float, float, float]:
    if valor.startswith("#"):
        return (*(int(valor[i : i + 2], 16) for i in (1, 3, 5)), 1.0)
    rojo, verde, azul, alfa = re.match(
        r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", valor
    ).groups()
    return int(rojo), int(verde), int(azul), float(alfa)


def token(nombre: str) -> tuple[float, float, float, float]:
    return _color(re.search(rf"--{nombre}:\s*([^;]+);", SIN_COMENTARIOS).group(1).strip())


def sobre(fondo, capa):
    """`capa` (con alfa) pintada encima de `fondo` opaco."""
    alfa = capa[3]
    return (*(c * alfa + f * (1 - alfa) for c, f in zip(capa[:3], fondo[:3], strict=True)), 1.0)


def luminancia(rgb) -> float:
    lineal = [
        (c / 255 / 12.92) if c / 255 <= 0.03928 else ((c / 255 + 0.055) / 1.055) ** 2.4
        for c in rgb[:3]
    ]
    return 0.2126 * lineal[0] + 0.7152 * lineal[1] + 0.0722 * lineal[2]


def contraste(a, b) -> float:
    claro, oscuro = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (claro + 0.05) / (oscuro + 0.05)


def test_toda_regla_cuelga_del_tema_lunar():
    sin_animaciones = re.sub(r"@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", SIN_COMENTARIOS)
    sin_medios = re.sub(r"@media[^{]+\{", "", sin_animaciones)
    preludios = re.findall(r"([^{}]+)\{", sin_medios)

    sueltos = [
        selector.strip()
        for preludio in preludios
        for selector in preludio.split(",")
        if not selector.strip().startswith('html[data-tema="lunar"]')
    ]
    assert sueltos == []


def _fondo_con_degradado():
    """El fondo de `body` donde más aclara su degradado radial azul. No cuenta las flores (E-43)."""
    return sobre(_color("#081327"), _color("rgba(84, 146, 255, 0.24)"))


def test_el_texto_cumple_contraste_aa_sobre_las_superficies():
    fondo = _fondo_con_degradado()
    superficies = [sobre(fondo, token("surface")), sobre(fondo, token("surface-raised"))]
    superficies += [token("cabecera-tabla"), token("panel-flotante")]

    for texto in ("text", "text-muted", "text-subtle", "accent", "positive"):
        for superficie in superficies:
            assert contraste(token(texto), superficie) >= AA, (texto, superficie)


def test_lo_elegido_y_la_tarjeta_de_parada_se_leen():
    panel = sobre(_fondo_con_degradado(), token("surface"))
    elegido = sobre(panel, _color("rgba(125, 200, 255, 0.2)"))
    parada = sobre(panel, _color("rgba(22, 42, 78, 0.5)"))

    for texto in ("text", "accent"):
        assert contraste(token(texto), elegido) >= AA, texto
    for texto in ("text", "text-muted", "text-subtle"):
        assert contraste(token(texto), parada) >= AA, texto


def test_el_texto_del_boton_primario_se_lee_sobre_su_degradado():
    # Los extremos del degradado de `.boton--primario`.
    for extremo in ("#a4e9ff", "#62c7f1"):
        assert contraste(token("on-accent"), _color(extremo)) >= AA, extremo


def test_el_vidrio_liso_no_deja_nada_con_desenfoque():
    liso = re.search(r'\[data-vidrio="liso"\] \{([^}]*)\}', SIN_COMENTARIOS).group(1)

    for nombre in ("lunar-desenfoque", "lunar-desenfoque-elegido", "lunar-desenfoque-leve"):
        assert re.search(rf"--{nombre}:\s*none;", liso), nombre
    assert not re.search(r"backdrop-filter:\s*blur", SIN_COMENTARIOS)


def test_las_imagenes_que_nombra_la_capa_existen():
    for ruta in re.findall(r'url\("\.\./([^"]+)"\)', LUNAR):
        assert (RAIZ / "ui" / ruta).is_file(), ruta
