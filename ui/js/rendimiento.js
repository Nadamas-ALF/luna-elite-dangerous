// Pantalla Rendimiento (SPEC.md §7.5): lo ganado de verdad por sesión, ruta y
// mercancía, y la ganancia por hora real contra la que estimaba LUNA.
import * as api from './api.js';
import { crear, estacion } from './celdas.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';
import { ESENCIAL, pintarTabla, SECUNDARIA } from './tabla.js';

const clave = (nombre) => `comercio.rendimiento.${nombre}`;
const TODO = 'todo';
// Con menos tramos la comparación es orientativa: se dice (DESIGN.md §4.4).
const TRAMOS_SUFICIENTES = 5;

const sinDato = () => texto('formato.sin_dato');
const porHora = (valor) => (valor === null ? sinDato() : formato.creditosPorHora(valor));

function desviacion(comparacion) {
  if (!comparacion || comparacion.desviacion === null) return sinDato();
  return formato.porcentajeConSigno(comparacion.desviacion);
}

function ruta(r) {
  const bloque = crear('div', 'ruta');
  const flecha = crear('span', 'ruta__flecha', texto(clave('rutas.hacia')));
  bloque.append(estacion(r.origen), flecha, estacion(r.destino));
  return bloque;
}

const nombres = (mercancias) => mercancias.map((m) => m.nombre).join(', ');

const COLUMNAS_DE_RUTAS = [
  ['ruta', ESENCIAL, ruta],
  ['por_hora', ESENCIAL, (r) => porHora(r.por_hora)],
  ['desviacion', ESENCIAL, (r) => desviacion(r.comparacion)],
  ['mercancias', null, (r) => nombres(r.mercancias)],
  ['viajes', null, (r) => String(r.viajes)],
  ['ganancia', null, (r) => formato.creditos(r.ganancia)],
  ['tiempo', null, (r) => formato.duracion(r.segundos)],
  ['estimada', SECUNDARIA, (r) => porHora(r.comparacion?.por_hora_estimada ?? null)],
];

function gananciaDeMercancia(m) {
  const ganancia = formato.creditos(m.ganancia);
  if (!m.sin_precio_de_compra) return ganancia;
  return texto(clave('mercancias.sin_precio'), { ganancia, n: m.sin_precio_de_compra });
}

const COLUMNAS_DE_MERCANCIAS = [
  ['mercancia', ESENCIAL, (m) => m.mercancia.nombre],
  ['ganancia', ESENCIAL, gananciaDeMercancia],
  ['toneladas', null, (m) => formato.toneladas(m.toneladas)],
  ['ventas', null, (m) => String(m.ventas)],
];

function estadoDeSesion(s) {
  if (s.en_curso) return texto(clave('sesiones.en_curso'));
  return s.bloques > 1 ? texto(clave('sesiones.bloques'), { n: s.bloques }) : '';
}

const COLUMNAS_DE_SESIONES = [
  ['sesion', ESENCIAL, (s) => formato.fechaHora(s.inicio)],
  ['ganancia', ESENCIAL, (s) => formato.creditos(s.ganancia)],
  ['por_hora', ESENCIAL, (s) => porHora(s.por_hora)],
  ['duracion', null, (s) => formato.duracion(s.segundos)],
  ['toneladas', null, (s) => formato.toneladas(s.toneladas)],
  ['saltos', SECUNDARIA, (s) => String(s.saltos)],
  ['saldo', SECUNDARIA, (s) => (s.saldo_fin === null ? sinDato() : formato.creditos(s.saldo_fin))],
  ['estado_sesion', null, estadoDeSesion],
];

function campos(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  return c;
}

function mostrarTexto(elemento, mensaje) {
  elemento.hidden = !mensaje;
  elemento.textContent = mensaje ?? '';
}

function opcion(valor, etiqueta) {
  const elemento = crear('option', null, etiqueta);
  elemento.value = valor;
  return elemento;
}

function etiquetaDeSesion(s) {
  const datos = { fecha: formato.fechaHora(s.inicio), duracion: formato.duracion(s.segundos) };
  return texto(clave(s.en_curso ? 'opcion_en_curso' : 'opcion'), datos);
}

function textoDeComparacion(comparacion) {
  if (!comparacion) return texto(clave('comparacion.sin_tramos'));
  const datos = {
    n: comparacion.tramos,
    real: porHora(comparacion.por_hora_real),
    estimada: porHora(comparacion.por_hora_estimada),
    desviacion: desviacion(comparacion),
  };
  const frase = texto(clave('comparacion.resultado'), datos);
  if (comparacion.tramos >= TRAMOS_SUFICIENTES) return frase;
  return `${frase} ${texto(clave('comparacion.pocos'), { minimo: TRAMOS_SUFICIENTES })}`;
}

function avisoDeResumen(respuesta) {
  if (respuesta.seleccion === TODO) return null;
  const elegida = respuesta.sesiones.find((s) => s.inicio === respuesta.seleccion);
  return elegida?.en_curso ? texto(clave('resumen.en_curso')) : null;
}

function saldoDe(respuesta) {
  const elegida = respuesta.sesiones.find((s) => s.inicio === respuesta.seleccion);
  if (!elegida || elegida.saldo_inicio === null || elegida.saldo_fin === null) return null;
  return texto(clave('resumen.saldo_valor'), {
    inicio: formato.creditos(elegida.saldo_inicio),
    fin: formato.creditos(elegida.saldo_fin),
  });
}

function mensajeDeError(respuesta) {
  return texto(clave(`errores.${respuesta.error}`));
}

export function crearVistaRendimiento(raiz) {
  const c = campos(raiz);
  let turno = 0;

  function pintarSelector(respuesta) {
    const opciones = respuesta.sesiones.map((s) => opcion(s.inicio, etiquetaDeSesion(s)));
    if (opciones.length) opciones.push(opcion(TODO, texto(clave('todo'))));
    c.sesion.replaceChildren(...opciones);
    c.sesion.value = respuesta.seleccion ?? '';
    c.sesion.disabled = opciones.length === 0;
  }

  function pintarResumen(respuesta) {
    const { resumen } = respuesta;
    c.resumen.hidden = false;
    mostrarTexto(c.resumen_aviso, avisoDeResumen(respuesta));
    c.resumen_ganancia.textContent = formato.creditos(resumen.ganancia);
    c.resumen_tiempo.textContent = formato.duracion(resumen.segundos);
    c.resumen_por_hora.textContent = porHora(resumen.por_hora);
    c.resumen_toneladas.textContent = formato.toneladas(resumen.toneladas);
    c.resumen_saltos.textContent = String(resumen.saltos);
    const saldo = saldoDe(respuesta);
    c.resumen_saldo.textContent = saldo ?? '';
    c.resumen_saldo.hidden = saldo === null;
    c.resumen_saldo_etiqueta.hidden = saldo === null;
    c.comparacion.textContent = textoDeComparacion(resumen.comparacion);
  }

  function pintarLista(prefijo, columnas, datos, vacio) {
    c[`${prefijo}_panel`].hidden = false;
    pintarTabla(c[`${prefijo}_tabla`], columnas, datos, clave(`${prefijo}.columnas`));
    c[`${prefijo}_contenedor`].hidden = datos.length === 0;
    mostrarTexto(c[`${prefijo}_vacio`], datos.length === 0 ? vacio : null);
  }

  function pintarSesiones(respuesta) {
    c.sesiones_panel.hidden = false;
    const { pausa_horas: horas, por_partida: porPartida } = respuesta.ajuste;
    c.sesiones_ayuda.textContent = porPartida
      ? texto(clave('sesiones.ayuda_partida'))
      : texto(clave('sesiones.ayuda_pausa'), { horas });
    const elegir = (s) => cargar(s.inicio);
    pintarTabla(c.sesiones_tabla, COLUMNAS_DE_SESIONES, respuesta.sesiones, clave('sesiones.columnas'), elegir);
  }

  function ocultarTodo() {
    for (const nombre of ['resumen', 'rutas_panel', 'mercancias_panel', 'sesiones_panel']) {
      c[nombre].hidden = true;
    }
    mostrarTexto(c.error, null);
  }

  function pintar(respuesta) {
    pintarSelector(respuesta);
    if (respuesta.sesiones.length === 0) {
      mostrarTexto(c.estado, texto(clave('sin_sesiones')));
      return;
    }
    pintarResumen(respuesta);
    pintarLista('rutas', COLUMNAS_DE_RUTAS, respuesta.rutas, texto(clave('rutas.vacio')));
    pintarLista('mercancias', COLUMNAS_DE_MERCANCIAS, respuesta.mercancias, texto(clave('mercancias.vacio')));
    pintarSesiones(respuesta);
    mostrarTexto(c.estado, texto(clave('actualizado'), { hora: formato.hora(new Date()) }));
  }

  async function cargar(sesion) {
    const mio = ++turno;
    mostrarTexto(c.estado, texto(clave('cargando')));
    let respuesta;
    try {
      respuesta = await api.rendimiento(sesion ?? null);
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (mio !== turno) return;
    // La sesión elegida desaparece si cambia el umbral en Configuración: se pide la última.
    if (respuesta.error === 'sesion_desconocida' && sesion) {
      cargar(null);
      return;
    }
    ocultarTodo();
    if (respuesta.error) {
      mostrarTexto(c.estado, null);
      mostrarTexto(c.error, mensajeDeError(respuesta));
      return;
    }
    pintar(respuesta);
  }

  c.sesion.addEventListener('change', () => cargar(c.sesion.value));
  c.actualizar.addEventListener('click', () => cargar(c.sesion.value || null));

  return {
    mostrar: () => cargar(c.sesion.value || null),
  };
}
