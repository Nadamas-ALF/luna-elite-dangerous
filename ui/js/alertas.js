// Pantalla Alertas (SPEC.md §7.4): los umbrales y los avisos recientes. El aviso
// emergente sale en cualquier pantalla: la interfaz pregunta por avisos nuevos cada
// pocos segundos y Python ya ha hecho sonar el suyo.
import * as api from './api.js';
import { crear, estacion } from './celdas.js';
import { pintarDetalle } from './detalle.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';
import { ESENCIAL, pintarTabla, SECUNDARIA } from './tabla.js';

const clave = (nombre) => `comercio.alertas.${nombre}`;
const INTERVALO_DE_AVISOS = 3000;
const UMBRALES = [
  'ganancia_tonelada_min',
  'ganancia_hora_min',
  'distancia_max_ly',
  'antiguedad_max_h',
  'repetir_min',
  'mejora_pct',
];

const esBucle = (aviso) => aviso.modo === 'bucle';
function puntas(aviso) {
  const tramo = esBucle(aviso) ? aviso.ruta.ida : aviso.ruta;
  return [tramo.compra, tramo.venta];
}

function mercancias(aviso) {
  if (!esBucle(aviso)) return aviso.ruta.mercancia.nombre;
  return texto(clave('avisos.ida_y_vuelta'), {
    ida: aviso.ruta.ida.mercancia.nombre,
    vuelta: aviso.ruta.vuelta.mercancia.nombre,
  });
}

function ruta(aviso) {
  const [a, b] = puntas(aviso);
  const bloque = crear('div', 'ruta');
  const flecha = texto(clave(esBucle(aviso) ? 'avisos.bucle_flecha' : 'avisos.flecha'));
  bloque.append(estacion(a), crear('span', 'ruta__flecha', flecha), estacion(b));
  return bloque;
}

const COLUMNAS = [
  ['ruta', ESENCIAL, ruta],
  ['ganancia_hora', ESENCIAL, (a) => formato.creditosPorHora(a.ganancia_hora)],
  ['cuando', ESENCIAL, (a) => formato.hace(a.momento)],
  ['mercancias', null, mercancias],
  ['modo', null, (a) => texto(`comercio.rutas.modos.${a.modo}`)],
  ['ganancia_tonelada', SECUNDARIA, (a) => formato.creditosPorTonelada(a.ruta.ganancia_tonelada)],
];

/** «0,01» o «1.000»: un límite de las reglas en cifras españolas. */
const cifra = (valor) => formato.decimales(valor, Number.isInteger(valor) ? 0 : 2);

function campos(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  return c;
}

function mostrarTexto(elemento, mensaje) {
  elemento.hidden = !mensaje;
  elemento.textContent = mensaje ?? '';
}

/** Lo que dice el aviso emergente: la ruta mejor pagada y cuántas más llegaron con ella. */
function resumenDeAvisos(nuevos) {
  const [mejor] = [...nuevos].sort((x, y) => y.ganancia_hora - x.ganancia_hora);
  const [a, b] = puntas(mejor);
  const datos = {
    mercancia: mercancias(mejor),
    desde: a.estacion,
    hasta: b.estacion,
    cr_h: formato.creditosPorHora(mejor.ganancia_hora),
  };
  const frase = texto(clave('aviso.ruta'), datos);
  if (nuevos.length === 1) return { mejor, frase };
  return { mejor, frase: `${frase} ${texto(clave('aviso.mas'), { n: nuevos.length - 1 })}` };
}

function crearPanelReglas(raiz) {
  const c = campos(raiz);
  const formulario = c.reglas_formulario;
  const entrada = (nombre) => formulario.elements.namedItem(nombre);
  let limites = {};

  function pintar({ reglas, limites: nuevos }) {
    limites = nuevos ?? limites;
    entrada('activadas').checked = reglas.activadas;
    for (const nombre of UMBRALES) entrada(nombre).value = String(reglas[nombre]);
  }

  function leer() {
    const reglas = { activadas: entrada('activadas').checked };
    for (const nombre of UMBRALES) {
      const valor = entrada(nombre).valueAsNumber;
      reglas[nombre] = Number.isNaN(valor) ? null : valor;
    }
    return reglas;
  }

  function limpiar() {
    mostrarTexto(c.reglas_error, null);
    mostrarTexto(c.reglas_resultado, null);
    for (const nombre of UMBRALES) entrada(nombre).removeAttribute('aria-invalid');
  }

  function rechazar(respuesta) {
    if (respuesta.error !== 'regla' || !UMBRALES.includes(respuesta.campo)) {
      mostrarTexto(c.reglas_error, texto(clave(`errores.${respuesta.error}`)));
      return;
    }
    const [minimo, maximo] = (limites[respuesta.campo] ?? []).map(cifra);
    entrada(respuesta.campo).setAttribute('aria-invalid', 'true');
    entrada(respuesta.campo).focus();
    const campo = texto(clave(`reglas.${respuesta.campo}`));
    mostrarTexto(c.reglas_error, texto(clave('errores.umbral'), { campo, minimo, maximo }));
  }

  formulario.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    limpiar();
    let respuesta;
    try {
      respuesta = await api.guardarReglasDeAlertas(leer());
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (respuesta.error) rechazar(respuesta);
    else if (respuesta.pendiente) mostrarTexto(c.reglas_resultado, texto(clave('reglas.pendiente')));
    else {
      pintar(respuesta);
      mostrarTexto(c.reglas_resultado, texto(clave('reglas.guardado')));
    }
  });

  return {
    async cargar() {
      limpiar();
      // Mientras llega la respuesta, el formulario no se puede tocar: vacío no es «sin reglas».
      formulario.inert = true;
      mostrarTexto(c.reglas_resultado, texto(clave('reglas.cargando')));
      let respuesta;
      try {
        respuesta = await api.reglasDeAlertas();
      } catch (error) {
        console.error(error);
        respuesta = { error: 'sin_respuesta' };
      } finally {
        formulario.inert = false;
        mostrarTexto(c.reglas_resultado, null);
      }
      if (respuesta.error) mostrarTexto(c.reglas_error, texto(clave(`errores.${respuesta.error}`)));
      else pintar(respuesta);
    },
  };
}

export function crearVistaAlertas(raiz, avisoEmergente, irA) {
  const c = campos(raiz);
  const reglas = crearPanelReglas(raiz);
  const a = campos(avisoEmergente);
  let avisos = [];
  let ultimo = null;
  let visible = false;
  let pendiente = null;
  let preguntando = false;

  function elegir(aviso) {
    const { ganancia_sesion: sesion, ganancia_hora: porHora } = aviso.ruta;
    const horas = porHora ? sesion / porHora : 0;
    pintarDetalle(c.detalle_tramos, aviso.modo, aviso.ruta, horas);
    c.detalle.hidden = false;
  }

  function pintarAvisos() {
    c.avisos_contenedor.hidden = avisos.length === 0;
    pintarTabla(c.avisos_tabla, COLUMNAS, avisos, clave('avisos.columnas'), elegir);
    const estado = avisos.length === 0 ? 'avisos.vacio' : 'avisos.ayuda';
    mostrarTexto(c.avisos_estado, texto(clave(estado)));
  }

  async function cargarAvisos() {
    mostrarTexto(c.avisos_error, null);
    mostrarTexto(c.avisos_estado, texto(clave('avisos.cargando')));
    let respuesta;
    try {
      respuesta = await api.avisos(null);
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (respuesta.error) {
      mostrarTexto(c.avisos_estado, null);
      mostrarTexto(c.avisos_error, texto(clave(`errores.${respuesta.error}`)));
      return;
    }
    avisos = respuesta.avisos;
    pintarAvisos();
  }

  async function mostrar() {
    visible = true;
    c.detalle.hidden = true;
    await Promise.all([reglas.cargar(), cargarAvisos()]);
  }

  async function abrir(aviso) {
    cerrarAviso();
    irA('alertas');
    await mostrar();
    const fila = [...c.avisos_tabla.tBodies[0].rows][avisos.findIndex((x) => x.id === aviso.id)];
    if (fila) fila.click();
    else elegir(aviso);
    // El aviso se cerró: el foco pasa a la ruta que se acaba de abrir.
    c.detalle.focus();
    c.detalle.scrollIntoView({ block: 'nearest' });
  }

  function cerrarAviso() {
    avisoEmergente.hidden = true;
    pendiente = null;
  }

  function avisar(nuevos) {
    const { mejor, frase } = resumenDeAvisos(nuevos);
    pendiente = mejor;
    a.aviso_texto.textContent = frase;
    avisoEmergente.hidden = false;
  }

  async function preguntar() {
    if (preguntando) return;
    preguntando = true;
    try {
      const respuesta = await api.avisos(ultimo);
      if (respuesta.error) return;
      // La primera vez solo se apunta dónde va la lista: lo de antes ya avisó.
      if (ultimo !== null && respuesta.avisos.length > 0) {
        avisar(respuesta.avisos);
        if (visible) await cargarAvisos();
      }
      ultimo = respuesta.ultimo;
    } catch (error) {
      console.error(error);
    } finally {
      preguntando = false;
    }
  }

  a.aviso_abrir.addEventListener('click', () => pendiente && abrir(pendiente));
  a.aviso_cerrar.addEventListener('click', cerrarAviso);
  document.addEventListener('keydown', (evento) => {
    if (evento.key === 'Escape' && !avisoEmergente.hidden) cerrarAviso();
  });

  return {
    mostrar,
    salir() {
      visible = false;
    },
    /** Empieza a preguntar por avisos nuevos; se llama cuando el puente con Python ya está. */
    vigilar() {
      preguntar();
      setInterval(preguntar, INTERVALO_DE_AVISOS);
    },
  };
}
