// Detalle de una ruta por paradas (SPEC.md §9.2): los totales arriba y, debajo, una tarjeta por
// estación con lo que se vende al llegar y lo que se compra al salir. El trayecto va entre
// tarjetas, en la parada a la que llega. Python arma el modelo (`modules/comercio/paradas.py`)
// y este módulo solo lo pinta, sea cual sea el número de paradas.
import * as api from './api.js';
import { antiguedad, botonCopiarSistema, crear, origen } from './celdas.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';

const clave = (nombre) => `comercio.rutas.detalle.${nombre}`;
// Cuánto hay que alejarse del origen para que valga la pena decirlo (en «Comprar desde aquí» es 0).
const DISTANCIA_MINIMA_AL_ORIGEN = 0.1;

const sinDato = () => texto('formato.sin_dato');
const nota = (mensaje) => crear('p', 'motivo', mensaje);

function par(lista, etiqueta, valor) {
  const dd = crear('dd');
  dd.append(valor);
  const grupo = crear('div');
  grupo.append(crear('dt', null, etiqueta), dd);
  lista.append(grupo);
}

function dato(lado) {
  const valor = crear('span', 'dato');
  valor.append(antiguedad(lado), crear('span', 'dato__origen', origen(lado)));
  return valor;
}

// Qué total es cada clave y cómo se escribe; solo salen las que trae el detalle.
const TOTALES = [
  ['ganancia_hora', 'ganancia_hora', formato.creditosPorHora],
  ['ingreso_hora', 'ingreso_hora', formato.creditosPorHora],
  ['ganancia_viaje', 'ganancia_viaje', formato.gananciaEnCreditos],
  ['ingreso_viaje', 'ingreso_viaje', formato.creditos],
  ['segundos', 'tiempo', formato.duracion],
  ['ganancia_sesion', 'ganancia_sesion', formato.gananciaEnCreditos],
  ['distancia_ly', 'distancia_total', formato.anosLuz],
  ['confianza', 'confianza', (valor) => formato.porcentaje(valor, 1)],
];

function totales(valores, horasSesion) {
  const seccion = crear('section', 'totales');
  const lista = crear('dl', 'totales__lista');
  for (const [campo, etiqueta, formatear] of TOTALES) {
    if (!(campo in valores)) continue;
    const valor = valores[campo];
    par(
      lista,
      texto(clave(etiqueta), { horas: formato.cantidad(horasSesion) }),
      valor === null ? sinDato() : formatear(valor),
    );
  }
  seccion.append(crear('h3', 'solo-lectores', texto(clave('totales'))), lista);
  if ('confianza' in valores) seccion.append(nota(texto(clave('confianza_ayuda'))));
  return seccion;
}

/** Cada parte con su duración y de dónde sale (SPEC.md §8.4); sin salto no hay salida. */
function partesDelTiempo(trayecto) {
  const detalles = crear('details', 'trayecto__tiempo');
  detalles.append(crear('summary', null, texto(clave('de_donde_sale'))));
  for (const p of trayecto.tiempo.filter((parte) => parte.segundos > 0)) {
    detalles.append(nota(texto(clave('parte'), {
      parte: texto(clave(`partes.${p.parte}`)),
      duracion: formato.duracion(p.segundos),
      fuente: texto(clave(`fuente.${p.fuente}`), { muestras: p.muestras }),
    })));
  }
  detalles.append(nota(texto(clave('recta'))));
  return detalles;
}

/** `etiqueta`: de dónde sale el trayecto cuando no es la parada anterior. */
function trayecto(datos, etiqueta) {
  const bloque = crear('div', 'trayecto');
  const linea = crear('p', 'trayecto__linea', texto(clave('trayecto'), {
    ly: formato.anosLuz(datos.distancia_ly),
    saltos: datos.saltos,
    tiempo: formato.duracion(datos.segundos),
  }));
  bloque.append(...(etiqueta ? [crear('p', 'trayecto__etiqueta', etiqueta)] : []), linea, partesDelTiempo(datos));
  return bloque;
}

/** Los pares de una mercancía en rejilla: lo que el usuario necesita para hacer el trato. */
function operacion(titulo, pares) {
  const seccion = crear('section', 'operacion');
  const lista = crear('dl', 'operacion__rejilla');
  for (const [etiqueta, valor] of pares) par(lista, etiqueta, valor);
  seccion.append(crear('h4', 'operacion__titulo', titulo), lista);
  return seccion;
}

const etiqueta = (nombre) => texto(clave(nombre));

/** `antes`: el nombre de la mercancía con la que se fijó la ruta, si hoy la mejor es otra. */
function seccionDeCompra(c, antes) {
  const seccion = operacion(texto(clave('comprar_al_salir'), { mercancia: c.mercancia.nombre }), [
    [etiqueta('precio'), formato.creditos(c.precio)],
    [etiqueta('stock'), formato.toneladas(c.stock)],
    [etiqueta('toneladas'), formato.toneladas(c.toneladas)],
    [etiqueta('dato'), dato(c)],
  ]);
  if (antes) seccion.prepend(nota(texto(clave('antes'), { mercancia: antes })));
  return seccion;
}

function seccionDeVenta(v) {
  return operacion(texto(clave('vender_al_llegar'), { mercancia: v.mercancia.nombre }), [
    [etiqueta('precio'), formato.creditos(v.precio)],
    [etiqueta('demanda'), formato.toneladas(v.demanda)],
    [etiqueta('toneladas'), formato.toneladas(v.toneladas)],
    [etiqueta('ingreso'), formato.creditos(v.ingreso)],
    [etiqueta('ganancia_tonelada'), v.ganancia_tonelada === null ? sinDato() : formato.gananciaPorTonelada(v.ganancia_tonelada)],
    [etiqueta('ganancia'), v.ganancia === null ? sinDato() : formato.gananciaEnCreditos(v.ganancia)],
    [etiqueta('dato'), dato(v)],
  ]);
}

/** Sistema, distancia a la estrella y, solo en la primera parada, a cuánto está del origen. */
function ubicacion(estacion, conOrigen) {
  const linea = crear('p', 'motivo parada__ubicacion');
  const sistema = crear('span', 'seleccionable', estacion.sistema);
  linea.append(sistema, ` · ${formato.segundosLuz(estacion.distancia_ls)}`);
  if (estacion.planetaria) linea.append(` · ${texto(clave('planetaria'))}`);
  if (conOrigen && estacion.distancia_origen >= DISTANCIA_MINIMA_AL_ORIGEN) {
    linea.append(` · ${texto(clave('desde_origen'), { distancia: formato.anosLuz(estacion.distancia_origen) })}`);
  }
  return { linea, sistema };
}

function tarjeta(parada, numero, conOrigen, identificador, antes) {
  const articulo = crear('article', 'parada');
  const titulo = crear('h3', 'parada__titulo', texto(clave('parada'), {
    n: numero,
    estacion: parada.estacion.estacion,
  }));
  titulo.id = identificador;
  articulo.setAttribute('aria-labelledby', identificador);
  const { linea, sistema } = ubicacion(parada.estacion, conOrigen);
  const cabecera = crear('header', 'parada__cabecera');
  cabecera.append(titulo, botonCopiarSistema(parada.estacion, sistema));
  articulo.append(cabecera, linea);
  for (const v of parada.vender) articulo.append(seccionDeVenta(v));
  for (const c of parada.comprar) articulo.append(seccionDeCompra(c, antes));
  return articulo;
}

function listaDeParadas(detalle, prefijo, antes) {
  const lista = crear('ol', 'paradas');
  detalle.paradas.forEach((parada, i) => {
    const item = crear('li', 'paradas__item');
    // En una ruta cerrada el trayecto de la parada 1 es la vuelta: va al final, no antes.
    const llega = parada.llegada && !(detalle.cerrada && i === 0);
    if (llega) item.append(trayecto(parada.llegada, detalle.desde_posicion ? texto(clave('desde_posicion')) : null));
    const conOrigen = i === 0 && !detalle.desde_posicion;
    item.append(tarjeta(parada, i + 1, conOrigen, `${prefijo}-parada-${i + 1}`, antes?.[i]));
    lista.append(item);
  });
  return lista;
}

/** Muestra un panel de detalle y lo acerca a la vista dentro de la zona que se desplaza. */
export function abrirDetalle(panel) {
  panel.hidden = false;
  panel.scrollIntoView({ block: 'nearest' });
}

/** Qué dice un error de fijar o de quitar una ruta; el texto es de `es.json`. */
const errorDeFijar = (respuesta) => texto(clave(`fijar_errores.${respuesta.error}`));

function resultadoDeFijar(respuesta) {
  if (respuesta.error) return errorDeFijar(respuesta);
  if (respuesta.pendiente) return texto(clave('fijar_pendiente'));
  return texto(clave(respuesta.ya_fijada ? 'ya_fijada' : 'fijada'));
}

/** Las paradas del detalle en la forma que pide `fijar_ruta`: solo ids y la mercancía que se compra. */
export function rutaDelDetalle(detalle) {
  return {
    cerrada: detalle.cerrada,
    paradas: detalle.paradas.map((parada) => ({
      market_id: parada.estacion.market_id,
      mercancia: parada.comprar[0]?.mercancia.simbolo ?? null,
    })),
  };
}

function botonFijar(detalle) {
  const envoltorio = crear('div', 'acciones detalle__fijar');
  const boton = crear('button', 'boton boton--vidrio', texto(clave('fijar')));
  boton.type = 'button';
  const aviso = crear('p', 'motivo');
  aviso.setAttribute('role', 'status');
  boton.addEventListener('click', async () => {
    boton.disabled = true;
    try {
      aviso.textContent = resultadoDeFijar(await api.fijarRuta(rutaDelDetalle(detalle)));
    } catch (error) {
      console.error(error);
      aviso.textContent = errorDeFijar({ error: 'sin_respuesta' });
    } finally {
      boton.disabled = false;
    }
  });
  envoltorio.append(boton, aviso);
  return envoltorio;
}

/**
 * `detalle` es `null` cuando un aviso viejo no se pudo convertir a paradas.
 * `opciones.fijar` añade el botón «Fijar esta ruta» (no sirve en «Vender la carga», que no es una
 * ruta); `opciones.antes` es, por parada, la mercancía con la que se fijó si hoy es otra.
 */
export function pintarDetalle(contenedor, detalle, horasSesion, opciones = {}) {
  if (detalle === null) {
    contenedor.replaceChildren(nota(texto(clave('sin_detalle'))));
    return;
  }
  // Los ids de las tarjetas llevan el del panel: Rutas, Ahora y Alertas tienen cada uno su detalle.
  const prefijo = contenedor.closest('[aria-labelledby]')?.getAttribute('aria-labelledby') ?? 'detalle';
  const piezas = [totales(detalle.totales, horasSesion)];
  if (opciones.fijar && !detalle.desde_posicion) piezas.push(botonFijar(detalle));
  if (detalle.cerrada) piezas.push(nota(texto(clave('primera_vuelta'))));
  piezas.push(listaDeParadas(detalle, prefijo, opciones.antes));
  if (detalle.cerrada) {
    const vuelta = detalle.paradas[0].llegada;
    piezas.push(trayecto(vuelta, texto(clave('vuelta'))));
  }
  contenedor.replaceChildren(...piezas);
}
