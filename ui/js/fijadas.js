// Pantalla Fijadas (prefase 8, bloque 5): la ruta que haces ahora, las rutas fijadas recalculadas
// con los precios de hoy y «Estimar una ruta». Python guarda solo estaciones y mercancías y calcula
// todo (`modules/comercio/estimar.py`); aquí se pintan los resultados.
import * as api from './api.js';
import { antiguedad, crear, estacionEnlazada } from './celdas.js';
import { abrirDetalle, pintarDetalle } from './detalle.js';
import { crearBuscadorDeEstaciones } from './estaciones.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';
import { ESENCIAL, pintarTabla, SECUNDARIA } from './tabla.js';

const clave = (nombre) => `comercio.fijadas.${nombre}`;
const MAXIMO_DE_PARADAS = 10;
const MINIMO_DE_PARADAS = 2;
const MS_POR_HORA = 3_600_000;

function campos(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  return c;
}

function mostrarTexto(elemento, mensaje) {
  elemento.hidden = !mensaje;
  elemento.textContent = mensaje ?? '';
}

const sinDato = () => texto('formato.sin_dato');
const hayResumen = (f) => f.resumen !== null;
const flecha = (cerrada, n) => texto(clave(cerrada && n === 2 ? 'flecha_cerrada' : 'flecha'));

/** Las estaciones de la ruta con su flecha; una cerrada de más de dos paradas lleva «↻» al final. */
function rutaCelda(fijada, enCurso) {
  const bloque = crear('div', 'ruta');
  const paradas = fijada.paradas;
  paradas.forEach((parada, i) => {
    if (i > 0) bloque.append(crear('span', 'ruta__flecha', flecha(fijada.cerrada, paradas.length)));
    bloque.append(estacionEnlazada(parada));
  });
  if (fijada.cerrada && paradas.length > 2) bloque.append(crear('span', 'ruta__flecha', texto(clave('vuelve'))));
  if (enCurso) bloque.append(crear('span', 'etiqueta', texto(clave('tabla.en_curso'))));
  return bloque;
}

function nombresDeMercancias(fijada) {
  const nombres = fijada.tramos.map((t) => t.mercancia?.nombre).filter(Boolean);
  return nombres.length === 0 ? null : [...new Set(nombres)].join(' / ');
}

/** El primer problema de la ruta, en palabras; vacío si está bien. */
function estadoDe(fijada) {
  for (const motivo of ['sin_precios', 'sin_trato']) {
    if (fijada.tramos.some((t) => t.estado === motivo)) return texto(clave(`estado.${motivo}`));
  }
  return fijada.paradas.some((p) => p.no_cabe) ? texto(clave('estado.no_cabe')) : '';
}

function antiguedadDe(fijada) {
  const marca = new Date(Date.now() - fijada.resumen.horas_max * MS_POR_HORA).toISOString();
  return antiguedad({ horas: fijada.resumen.horas_max, observado: marca });
}

function columnas(idEnCurso) {
  const dato = (valor) => (f) => (hayResumen(f) ? valor(f.resumen) : sinDato());
  return [
    ['ruta', ESENCIAL, (f) => rutaCelda(f, f.id === idEnCurso), (f) => f.paradas[0].estacion],
    ['ganancia_hora', ESENCIAL, dato((r) => formato.creditosPorHora(r.ganancia_hora)), (f) => f.resumen?.ganancia_hora ?? null],
    ['antiguedad', ESENCIAL, (f) => (hayResumen(f) ? antiguedadDe(f) : sinDato()), (f) => f.resumen?.horas_max ?? null],
    ['mercancias', null, (f) => nombresDeMercancias(f) ?? sinDato(), nombresDeMercancias],
    ['ganancia_viaje', null, dato((r) => formato.gananciaEnCreditos(r.ganancia_viaje)), (f) => f.resumen?.ganancia_viaje ?? null],
    ['tiempo', SECUNDARIA, dato((r) => formato.duracion(r.segundos)), (f) => f.resumen?.segundos ?? null],
    ['estado_ruta', ESENCIAL, estadoDe, estadoDe],
  ];
}

/** Una ruta sin cifras hoy: sus estaciones por nombre y qué falla en cada tramo. */
function pintarIncompleta(contenedor, fijada) {
  const lista = crear('ol', 'paradas');
  fijada.paradas.forEach((parada, i) => {
    const item = crear('li', 'paradas__item');
    const linea = crear('p', 'motivo');
    linea.append(crear('strong', null, parada.estacion), ` · ${parada.sistema}`);
    item.append(linea);
    if (parada.no_cabe) item.append(crear('p', 'motivo', texto(clave('detalle.no_cabe'), { plataforma: parada.plataforma })));
    const tramo = fijada.tramos.find((t) => t.desde === i);
    if (tramo) item.append(crear('p', 'motivo', texto(clave(`detalle.tramo.${tramo.estado}`))));
    lista.append(item);
  });
  contenedor.replaceChildren(crear('p', 'motivo', texto(clave('detalle.sin_calculo'))), lista);
}

/** «Antes: Oro» en cada tramo cuya mejor mercancía de hoy no es la que se fijó. */
const antesDe = (fijada) => fijada.tramos.map((t) => (t.cambiada ? t.mercancia_fijada.nombre : null));

function horasDe(detalle) {
  const { ganancia_sesion: sesion, ganancia_hora: porHora } = detalle.totales;
  return porHora ? sesion / porHora : 0;
}

function pintarRuta(contenedor, fijada) {
  if (fijada.detalle === null) pintarIncompleta(contenedor, fijada);
  else pintarDetalle(contenedor, fijada.detalle, horasDe(fijada.detalle), { antes: antesDe(fijada) });
}

const mensajeDeError = (respuesta) => texto(clave(`errores.${respuesta.error}`));

function crearPanelDeEstimar(raiz, c, alFijar) {
  let elegidas = [];

  function pintarElegidas() {
    c.estimar_vacio.hidden = elegidas.length > 0;
    c.estimar_paradas.replaceChildren(
      ...elegidas.map((parada, i) => {
        const item = crear('li', 'estimar__parada');
        const quitar = crear('button', 'boton boton--vidrio boton--pequeno', texto(clave('estimar.quitar')));
        quitar.type = 'button';
        quitar.setAttribute('aria-label', texto(clave('estimar.quitar_aria'), { estacion: parada.estacion }));
        quitar.addEventListener('click', () => {
          elegidas = elegidas.filter((_, j) => j !== i);
          pintarElegidas();
        });
        item.append(crear('span', null, texto(clave('estimar.parada'), parada)), quitar);
        return item;
      }),
    );
    const falta = elegidas.length < MINIMO_DE_PARADAS;
    c.estimar_calcular.disabled = falta;
    c.estimar_fijar.disabled = falta;
  }

  function anadir(estacion) {
    mostrarTexto(c.estimar_error, null);
    if (elegidas.length >= MAXIMO_DE_PARADAS) {
      mostrarTexto(c.estimar_error, texto(clave('estimar.errores.demasiadas'), { n: MAXIMO_DE_PARADAS }));
      return;
    }
    const { market_id: marketId, estacion: nombre, sistema } = estacion;
    elegidas = [...elegidas, { market_id: marketId, estacion: nombre, sistema }];
    pintarElegidas();
  }

  const pedida = () => ({
    cerrada: c.estimar_cerrada.checked,
    paradas: elegidas.map((p) => ({ market_id: p.market_id, mercancia: null })),
  });

  function rechazar(respuesta) {
    mostrarTexto(c.estimar_error, texto(clave(`estimar.errores.${respuesta.error}`), { n: MAXIMO_DE_PARADAS }));
  }

  async function llamar(accion) {
    mostrarTexto(c.estimar_error, null);
    mostrarTexto(c.estimar_resultado, null);
    try {
      return await accion(pedida());
    } catch (error) {
      console.error(error);
      return { error: 'sin_respuesta' };
    }
  }

  c.estimar_calcular.addEventListener('click', async () => {
    const respuesta = await llamar(api.estimarRuta);
    if (respuesta.error) {
      rechazar(respuesta);
      c.estimar_detalle.replaceChildren();
      return;
    }
    pintarRuta(c.estimar_detalle, respuesta);
  });

  c.estimar_fijar.addEventListener('click', async () => {
    const respuesta = await llamar(api.fijarRuta);
    if (respuesta.error) rechazar(respuesta);
    else if (respuesta.pendiente) mostrarTexto(c.estimar_resultado, texto(clave('estimar.pendiente')));
    else {
      mostrarTexto(c.estimar_resultado, texto(clave(respuesta.ya_fijada ? 'estimar.ya_fijada' : 'estimar.fijada')));
      alFijar();
    }
  });

  crearBuscadorDeEstaciones(c.estimar_panel, [[clave('estimar.anadir'), anadir]]);
  pintarElegidas();
}

function textoDeLaRutaEnCurso(enCurso) {
  const separador = texto(clave(enCurso.cerrada && enCurso.paradas.length === 2 ? 'flecha_cerrada' : 'flecha'));
  return enCurso.paradas.map((p) => p.estacion).join(` ${separador} `);
}

export function crearVistaFijadas(raiz) {
  const c = campos(raiz);
  let visible = false;
  let turno = 0;
  let firma = null;
  let datos = { fijadas: [], en_curso: null };
  let elegidaId = null;

  function pintarEnCurso() {
    const enCurso = datos.en_curso;
    c.en_curso_fijar.hidden = true;
    mostrarTexto(c.en_curso_aviso, null);
    if (enCurso === null) {
      c.en_curso_cuerpo.replaceChildren(crear('p', 'motivo', texto(clave('en_curso.ninguna'))));
      return;
    }
    const real = formato.creditosPorHora(enCurso.por_hora_real);
    const resumen = enCurso.estimacion.resumen;
    const cifras = resumen
      ? texto(clave('en_curso.cifras'), { real, hoy: formato.creditosPorHora(resumen.ganancia_hora) })
      : texto(clave('en_curso.sin_estimacion'), { real });
    c.en_curso_cuerpo.replaceChildren(
      crear('p', 'en-curso__ruta', texto(clave('en_curso.linea'), { ruta: textoDeLaRutaEnCurso(enCurso), viajes: enCurso.viajes })),
      crear('p', 'motivo', cifras),
    );
    if (enCurso.id === null) c.en_curso_fijar.hidden = false;
    else mostrarTexto(c.en_curso_aviso, texto(clave('en_curso.fijada')));
  }

  function elegir(fijada) {
    elegidaId = fijada.id;
    pintarRuta(c.detalle_tramos, fijada);
    mostrarTexto(c.detalle_aviso, null);
    abrirDetalle(c.detalle);
  }

  function pintarTablaDeFijadas() {
    const hay = datos.fijadas.length > 0;
    c.fijadas_contenedor.hidden = !hay;
    c.fijadas_vacio.hidden = hay;
    pintarTabla(c.fijadas_tabla, columnas(datos.en_curso?.id ?? null), datos.fijadas, clave('tabla.columnas'), elegir);
    const abierta = datos.fijadas.find((f) => f.id === elegidaId);
    if (abierta) pintarRuta(c.detalle_tramos, abierta);
    else c.detalle.hidden = true;
  }

  async function actualizar() {
    // Solo se pinta la última respuesta: una llamada lenta no pisa a una más nueva.
    const mio = ++turno;
    mostrarTexto(c.fijadas_estado, texto(clave('calculando')));
    let respuesta;
    try {
      respuesta = await api.rutasFijadas();
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (mio !== turno) return;
    if (respuesta.error) {
      mostrarTexto(c.fijadas_estado, null);
      mostrarTexto(c.fijadas_error, mensajeDeError(respuesta));
      return;
    }
    mostrarTexto(c.fijadas_error, null);
    datos = respuesta;
    pintarEnCurso();
    pintarTablaDeFijadas();
    mostrarTexto(c.fijadas_estado, texto(clave('actualizado'), { hora: formato.hora(new Date()) }));
  }

  c.fijadas_actualizar.addEventListener('click', actualizar);

  c.en_curso_fijar.addEventListener('click', async () => {
    const { cerrada, paradas } = datos.en_curso;
    const ruta = { cerrada, paradas: paradas.map((p) => ({ market_id: p.market_id, mercancia: p.mercancia })) };
    let respuesta;
    try {
      respuesta = await api.fijarRuta(ruta);
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (respuesta.error) mostrarTexto(c.en_curso_aviso, mensajeDeError(respuesta));
    else await actualizar();
  });

  c.detalle_quitar.addEventListener('click', async () => {
    let respuesta;
    try {
      respuesta = await api.desfijarRuta(elegidaId);
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (respuesta.error) {
      mostrarTexto(c.detalle_aviso, mensajeDeError(respuesta));
      return;
    }
    elegidaId = null;
    await actualizar();
  });

  function abrirEstimar(abrir) {
    c.estimar_panel.hidden = !abrir;
    c.fijadas_estimar.setAttribute('aria-expanded', String(abrir));
    if (abrir) c.estimar_panel.querySelector('input[type="text"]').focus();
    else c.fijadas_estimar.focus();
  }

  c.fijadas_estimar.addEventListener('click', () => abrirEstimar(c.estimar_panel.hidden));
  c.estimar_cerrar.addEventListener('click', () => abrirEstimar(false));
  raiz.addEventListener('keydown', (evento) => {
    if (evento.key === 'Escape' && !c.estimar_panel.hidden) abrirEstimar(false);
  });
  crearPanelDeEstimar(raiz, c, actualizar);

  return {
    mostrar() {
      visible = true;
      actualizar();
    },
    salir() {
      visible = false;
    },
    /** Recibe cada lectura del estado; recalcula al atracar o despegar si se está viendo. */
    alEstado(estado) {
      const nueva = JSON.stringify(estado.ubicacion?.estacion?.nombre ?? null);
      if (nueva === firma) return;
      const habiaFirma = firma !== null;
      firma = nueva;
      if (visible && habiaFirma) actualizar();
    },
  };
}
