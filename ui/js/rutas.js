// Pantalla Rutas (SPEC.md §9.2): el perfil a la izquierda y los resultados a la
// derecha. Python filtra, calcula y ordena; aquí solo se pinta lo que devuelve.
import * as api from './api.js';
import * as aspecto from './aspecto.js';
import { antiguedad, crear, estacionEnlazada, masViejo, origenes } from './celdas.js';
import { abrirDetalle, pintarDetalle } from './detalle.js';
import { crearBuscadorDeEstaciones } from './estaciones.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';
import { ESENCIAL, pintarTabla, SECUNDARIA } from './tabla.js';

const lados = (tramo) => [tramo.compra, tramo.venta];
const ladosDe = (bucle) => [...lados(bucle.ida), ...lados(bucle.vuelta)];

const ladosDeRuta = (ruta) => ruta.tramos.flatMap(lados);

/** Las estaciones en el orden del recorrido; en un circuito la última no se repite. */
function estacionesDe(ruta) {
  const salidas = ruta.tramos.map((tramo) => tramo.compra);
  return ruta.cerrada ? salidas : [...salidas, ruta.tramos.at(-1).venta];
}

function rutaEnLineas(ruta) {
  const bloque = crear('div', 'lineas');
  estacionesDe(ruta).forEach((lado, i) => {
    const fila = crear('div', 'lineas__fila');
    fila.append(crear('span', 'lineas__n', String(i + 1)), estacionEnlazada(lado));
    bloque.append(fila);
  });
  if (ruta.cerrada) bloque.append(crear('span', 'lineas__vuelta', texto('comercio.rutas.vuelve')));
  return bloque;
}

function mercanciasEnLineas(ruta) {
  const bloque = crear('div', 'lineas');
  bloque.append(...ruta.tramos.map((tramo) => crear('span', null, tramo.mercancia.nombre)));
  return bloque;
}

/** Varias paradas y Circuito comparten columnas: solo cambia si la ruta vuelve al principio. */
const columnasDeRuta = () => [
  ['ruta', ESENCIAL, rutaEnLineas, (r) => estacionesDe(r)[0].estacion],
  ['mercancias', null, mercanciasEnLineas, (r) => r.tramos[0].mercancia.nombre],
  ['paradas', null, (r) => String(r.paradas), (r) => r.paradas],
  ['ganancia_hora', ESENCIAL, (r) => formato.creditosPorHora(r.ganancia_hora), (r) => r.ganancia_hora],
  ['antiguedad', ESENCIAL, (r) => antiguedad(masViejo(ladosDeRuta(r))), (r) => masViejo(ladosDeRuta(r)).horas],
  ['ganancia_viaje', null, (r) => formato.creditos(r.ganancia_viaje), (r) => r.ganancia_viaje],
  ['tiempo', null, (r) => formato.duracion(r.segundos), (r) => r.segundos],
  ['saltos', null, (r) => String(r.saltos), (r) => r.saltos],
  ['distancia_ly', SECUNDARIA, (r) => formato.anosLuz(r.distancia_ly), (r) => r.distancia_ly],
  ['ganancia_sesion', null, (r) => formato.creditos(r.ganancia_sesion), (r) => r.ganancia_sesion],
  ['origen', SECUNDARIA, (r) => origenes(ladosDeRuta(r)), (r) => origenes(ladosDeRuta(r))],
];

const MODOS_CON_PARADAS = new Set(['cadena', 'circuito']);
// Las mismas que acepta Python (`PARADAS_MINIMAS` a `PARADAS_MAXIMAS`).
const PARADAS = [3, 4, 5, 6];
const PARADAS_POR_DEFECTO = 4;

export const COLUMNAS = {
  un_salto: [
    ['mercancia', ESENCIAL, (t) => t.mercancia.nombre, (t) => t.mercancia.nombre],
    ['comprar', ESENCIAL, (t) => estacionEnlazada(t.compra), (t) => t.compra.estacion],
    ['vender', ESENCIAL, (t) => estacionEnlazada(t.venta), (t) => t.venta.estacion],
    ['ganancia_hora', ESENCIAL, (t) => formato.creditosPorHora(t.ganancia_hora), (t) => t.ganancia_hora],
    ['antiguedad', ESENCIAL, (t) => antiguedad(masViejo(lados(t))), (t) => masViejo(lados(t)).horas],
    ['precio_compra', null, (t) => formato.creditos(t.compra.precio), (t) => t.compra.precio],
    ['precio_venta', null, (t) => formato.creditos(t.venta.precio), (t) => t.venta.precio],
    ['ganancia_tonelada', null, (t) => formato.creditosPorTonelada(t.ganancia_tonelada), (t) => t.ganancia_tonelada],
    ['toneladas', null, (t) => formato.toneladas(t.toneladas), (t) => t.toneladas],
    ['ganancia_viaje', null, (t) => formato.creditos(t.ganancia_viaje), (t) => t.ganancia_viaje],
    ['saltos', null, (t) => String(t.saltos), (t) => t.saltos],
    ['distancia_ly', SECUNDARIA, (t) => formato.anosLuz(t.distancia_ly), (t) => t.distancia_ly],
    ['distancia_ls', SECUNDARIA, (t) => formato.segundosLuz(t.venta.distancia_ls), (t) => t.venta.distancia_ls],
    ['tiempo', null, (t) => formato.duracion(t.segundos), (t) => t.segundos],
    ['ganancia_sesion', null, (t) => formato.creditos(t.ganancia_sesion), (t) => t.ganancia_sesion],
    ['origen', SECUNDARIA, (t) => origenes(lados(t)), (t) => origenes(lados(t))],
  ],
  bucle: [
    ['ida', ESENCIAL, (b) => b.ida.mercancia.nombre, (b) => b.ida.mercancia.nombre],
    ['vuelta', ESENCIAL, (b) => b.vuelta.mercancia.nombre, (b) => b.vuelta.mercancia.nombre],
    ['estacion_a', ESENCIAL, (b) => estacionEnlazada(b.ida.compra), (b) => b.ida.compra.estacion],
    ['estacion_b', ESENCIAL, (b) => estacionEnlazada(b.ida.venta), (b) => b.ida.venta.estacion],
    ['ganancia_hora', ESENCIAL, (b) => formato.creditosPorHora(b.ganancia_hora), (b) => b.ganancia_hora],
    ['antiguedad', ESENCIAL, (b) => antiguedad(masViejo(ladosDe(b))), (b) => masViejo(ladosDe(b)).horas],
    ['ganancia_viaje', null, (b) => formato.creditos(b.ganancia_viaje), (b) => b.ganancia_viaje],
    ['distancia_ly', SECUNDARIA, (b) => formato.anosLuz(b.distancia_ly), (b) => b.distancia_ly],
    ['tiempo', null, (b) => formato.duracion(b.segundos), (b) => b.segundos],
    ['ganancia_sesion', null, (b) => formato.creditos(b.ganancia_sesion), (b) => b.ganancia_sesion],
    ['origen', SECUNDARIA, (b) => origenes(ladosDe(b)), (b) => origenes(ladosDe(b))],
  ],
  cadena: columnasDeRuta(),
  circuito: columnasDeRuta(),
};

/**
 * Las columnas de un modo que el usuario eligió en Configuración (todas, si aún no se saben).
 * Sin prioridad: lo elegido se enseña siempre y, si no cabe, la tabla se desplaza (§9.3).
 */
export function columnasElegidas(modo, todas = false) {
  const elegidas = todas ? null : aspecto.elegidas(modo);
  return COLUMNAS[modo]
    .filter(([nombre]) => !elegidas || elegidas.includes(nombre))
    .map(([nombre, , valor, clave]) => [nombre, null, valor, clave]);
}

function campos(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  return c;
}

function mostrarTexto(elemento, mensaje) {
  elemento.hidden = !mensaje;
  elemento.textContent = mensaje ?? '';
}

const FILTROS = [
  ['plataforma', 'estaciones'],
  ['distancia_ls', 'estaciones'],
  ['tipo', 'estaciones'],
  ['antiguedad', 'precios'],
  ['origen', 'precios'],
  ['raras', 'precios'],
  ['stock_minimo', 'precios'],
  ['saldo', 'tratos'],
  ['ganancia_min', 'tratos'],
];

/**
 * Lo que quitó cada filtro, de más a menos: una frase y una línea por filtro, para no unir
 * frases en JS. Sin descartes que contar, solo la frase.
 */
export function explicarDescartes(descartes) {
  if (descartes.estaciones_en_radio === 0) {
    return { frase: texto('comercio.rutas.descartes.sin_estaciones'), filtros: [] };
  }
  const filtros = FILTROS.map(([filtro, unidad]) => [filtro, unidad, descartes.descartes[filtro]])
    .filter(([, , n]) => n > 0)
    .sort((a, b) => b[2] - a[2])
    .map(([filtro, unidad, n]) =>
      texto(`comercio.rutas.descartes.filtro.${filtro}`, {
        cuanto: texto(`comercio.rutas.descartes.${unidad}`, { n: formato.cantidad(n) }),
      }),
    );
  const frase = filtros.length === 0 ? 'nada_descartado' : 'intro';
  return { frase: texto(`comercio.rutas.descartes.${frase}`), filtros };
}

function pintarExplicacion(elemento, { frase, filtros }) {
  const parrafo = document.createElement('p');
  parrafo.textContent = frase;
  const hijos = [parrafo];
  if (filtros.length > 0) {
    const lista = document.createElement('ul');
    lista.className = 'descartes';
    for (const filtro of filtros) {
      const linea = document.createElement('li');
      linea.textContent = filtro;
      lista.append(linea);
    }
    hijos.push(lista);
  }
  elemento.replaceChildren(...hijos);
  elemento.hidden = false;
}

export function crearVistaRutas(raiz, perfil) {
  const c = campos(raiz);
  let turno = 0;
  let mostrada = null;
  let resultados = [];

  function limpiar() {
    c.tabla_contenedor.hidden = true;
    c.detalle.hidden = true;
    c.tabla_cuerpo.replaceChildren();
    resultados = [];
    mostrarTexto(c.resultados_error, null);
    mostrarTexto(c.resultados_explicacion, null);
    mostrarTexto(c.resultados_cortada, null);
  }

  const modoElegido = () => new FormData(c.busqueda_formulario).get('modo');

  /** «Paradas» solo se ve con los modos que la usan, y su ayuda dice si son exactas o un tope. */
  function reflejarModo() {
    const modo = modoElegido();
    c.paradas_campo.hidden = !MODOS_CON_PARADAS.has(modo);
    if (MODOS_CON_PARADAS.has(modo)) c.paradas_ayuda.textContent = texto(`comercio.rutas.paradas_ayuda_${modo}`);
  }

  /** El límite de Configuración, para decir cuánto puede tardar; sin él, el aviso genérico. */
  async function limiteDeBusqueda() {
    try {
      return (await api.ajustesDeBusqueda()).limite_busqueda_s ?? null;
    } catch (error) {
      console.error(error);
      return null;
    }
  }

  /** Python cuenta los descartes aparte, para que la búsqueda no espere a los recuentos. */
  async function explicar(mio, perfilUsado) {
    mostrarTexto(c.resultados_explicacion, texto('comercio.rutas.descartes.calculando'));
    let respuesta;
    try {
      respuesta = await api.explicarBusqueda(perfilUsado);
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (mio !== turno || respuesta.cancelada) return;
    if (respuesta.error) {
      mostrarTexto(c.resultados_explicacion, texto('comercio.rutas.descartes.error'));
      return;
    }
    pintarExplicacion(c.resultados_explicacion, explicarDescartes(respuesta.descartes));
  }

  function seleccionar(resultado) {
    pintarDetalle(c.detalle_tramos, resultado.detalle, mostrada.horasSesion, { fijar: true });
    abrirDetalle(c.detalle);
  }

  function pintarLaTabla() {
    pintarTabla(c.tabla, columnasElegidas(mostrada.modo), resultados, 'comercio.rutas.columnas', seleccionar);
  }

  function pintarResultados(respuesta, perfilUsado) {
    resultados = respuesta.resultados;
    mostrada = { modo: respuesta.modo, horasSesion: perfilUsado.horas_sesion };
    pintarLaTabla();
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
    mostrarTexto(c.resultados_cortada, respuesta.cortada ? texto('comercio.rutas.cortada', { s: respuesta.limite_s }) : null);
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
    const modo = modoElegido();
    const paradas = MODOS_CON_PARADAS.has(modo) ? Number(c.paradas.value) : null;
    const perfilUsado = perfil.leer();
    limpiar();
    mostrarTexto(c.resultados_estado, texto('comercio.rutas.buscando'));
    if (paradas !== null) {
      const limite = await limiteDeBusqueda();
      if (mio !== turno) return;
      if (limite !== null) mostrarTexto(c.resultados_estado, texto('comercio.rutas.buscando_largo', { s: limite }));
    }
    let respuesta;
    try {
      respuesta = await api.buscarRutas(modo, perfilUsado, paradas);
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (mio !== turno || respuesta.cancelada) return;
    if (respuesta.error) {
      pintarError(respuesta);
      return;
    }
    pintarResultados(respuesta, perfilUsado);
    perfil.plegarSiEstrecho();
    if (respuesta.corta) await explicar(mio, perfilUsado);
  }

  // Si cambian las columnas elegidas con resultados a la vista, la tabla se rehace con ellas.
  aspecto.alCambiarColumnas(() => {
    if (mostrada && resultados.length > 0) pintarLaTabla();
  });
  c.busqueda_formulario.addEventListener('submit', buscar);
  c.busqueda_formulario.addEventListener('change', reflejarModo);
  c.paradas.replaceChildren(
    ...PARADAS.map((n) => {
      const opcion = crear('option', null, String(n));
      opcion.value = String(n);
      opcion.selected = n === PARADAS_POR_DEFECTO;
      return opcion;
    }),
  );
  reflejarModo();
  crearBuscadorDeEstaciones(raiz, [
    ['comercio.estaciones.usar_origen', (estacion) => perfil.fijarOrigen(estacion.sistema)],
  ]);
  mostrarTexto(c.resultados_estado, texto('comercio.rutas.inicial'));
}
