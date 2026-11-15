// Pantalla Rutas (SPEC.md §9.2): el perfil a la izquierda y los resultados a la
// derecha. Python filtra, calcula y ordena; aquí solo se pinta lo que devuelve.
import * as api from './api.js';
import { antiguedad, estacion, masViejo, origenes } from './celdas.js';
import { pintarDetalle } from './detalle.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';
import { ESENCIAL, pintarTabla, SECUNDARIA } from './tabla.js';

const lados = (tramo) => [tramo.compra, tramo.venta];

export const COLUMNAS = {
  un_salto: [
    ['mercancia', ESENCIAL, (t) => t.mercancia.nombre],
    ['comprar', ESENCIAL, (t) => estacion(t.compra)],
    ['vender', ESENCIAL, (t) => estacion(t.venta)],
    ['ganancia_hora', ESENCIAL, (t) => formato.creditosPorHora(t.ganancia_hora)],
    ['antiguedad', ESENCIAL, (t) => antiguedad(masViejo(lados(t)))],
    ['precio_compra', null, (t) => formato.creditos(t.compra.precio)],
    ['precio_venta', null, (t) => formato.creditos(t.venta.precio)],
    ['ganancia_tonelada', null, (t) => formato.creditosPorTonelada(t.ganancia_tonelada)],
    ['toneladas', null, (t) => formato.toneladas(t.toneladas)],
    ['ganancia_viaje', null, (t) => formato.creditos(t.ganancia_viaje)],
    ['saltos', null, (t) => String(t.saltos)],
    ['distancia_ly', SECUNDARIA, (t) => formato.anosLuz(t.distancia_ly)],
    ['distancia_ls', SECUNDARIA, (t) => formato.segundosLuz(t.venta.distancia_ls)],
    ['tiempo', null, (t) => formato.duracion(t.segundos)],
    ['ganancia_sesion', null, (t) => formato.creditos(t.ganancia_sesion)],
    ['origen', SECUNDARIA, (t) => origenes(lados(t))],
  ],
  bucle: [
    ['ida', ESENCIAL, (b) => b.ida.mercancia.nombre],
    ['vuelta', ESENCIAL, (b) => b.vuelta.mercancia.nombre],
    ['estacion_a', ESENCIAL, (b) => estacion(b.ida.compra)],
    ['estacion_b', ESENCIAL, (b) => estacion(b.ida.venta)],
    ['ganancia_hora', ESENCIAL, (b) => formato.creditosPorHora(b.ganancia_hora)],
    ['antiguedad', ESENCIAL, (b) => antiguedad(masViejo([...lados(b.ida), ...lados(b.vuelta)]))],
    ['ganancia_viaje', null, (b) => formato.creditos(b.ganancia_viaje)],
    ['distancia_ly', SECUNDARIA, (b) => formato.anosLuz(b.distancia_ly)],
    ['tiempo', null, (b) => formato.duracion(b.segundos)],
    ['ganancia_sesion', null, (b) => formato.creditos(b.ganancia_sesion)],
    ['origen', SECUNDARIA, (b) => origenes([...lados(b.ida), ...lados(b.vuelta)])],
  ],
};

function campos(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  return c;
}

function mostrarTexto(elemento, mensaje) {
  elemento.hidden = !mensaje;
  elemento.textContent = mensaje ?? '';
}

export function crearVistaRutas(raiz, perfil) {
  const c = campos(raiz);
  let turno = 0;
  let mostrada = null;

  function limpiar() {
    c.tabla_contenedor.hidden = true;
    c.detalle.hidden = true;
    c.tabla_cuerpo.replaceChildren();
    mostrarTexto(c.resultados_error, null);
  }

  function seleccionar(resultado) {
    pintarDetalle(c.detalle_tramos, mostrada.modo, resultado, mostrada.horasSesion);
    c.detalle.hidden = false;
  }

  function pintarResultados(respuesta, perfilUsado) {
    const { resultados } = respuesta;
    mostrada = { modo: respuesta.modo, horasSesion: perfilUsado.horas_sesion };
    pintarTabla(c.tabla, COLUMNAS[respuesta.modo], resultados, 'comercio.rutas.columnas', seleccionar);
    c.tabla_contenedor.hidden = resultados.length === 0;
    const orden = texto(`comercio.perfil.ordenes.${perfilUsado.orden}`).toLowerCase();
    const resumen =
      resultados.length === 1
        ? texto('comercio.rutas.resumen_una')
        : texto('comercio.rutas.resumen', { n: resultados.length, orden });
    mostrarTexto(
      c.resultados_estado,
      resultados.length === 0 ? texto('comercio.rutas.sin_resultados') : resumen,
    );
  }

  function pintarError(respuesta) {
    if (respuesta.error === 'perfil') perfil.rechazar(respuesta);
    mostrarTexto(c.resultados_estado, null);
    mostrarTexto(c.resultados_error, texto(`comercio.rutas.errores.${respuesta.error}`));
  }

  async function buscar(evento) {
    evento.preventDefault();
    // Una búsqueda nueva deja sin efecto la anterior: Python la cancela y aquí no se pinta.
    const mio = ++turno;
    const modo = new FormData(c.busqueda_formulario).get('modo');
    const perfilUsado = perfil.leer();
    limpiar();
    mostrarTexto(c.resultados_estado, texto('comercio.rutas.buscando'));
    let respuesta;
    try {
      respuesta = await api.buscarRutas(modo, perfilUsado);
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (mio !== turno || respuesta.cancelada) return;
    if (respuesta.error) pintarError(respuesta);
    else pintarResultados(respuesta, perfilUsado);
  }

  c.busqueda_formulario.addEventListener('submit', buscar);
  mostrarTexto(c.resultados_estado, texto('comercio.rutas.inicial'));
}
