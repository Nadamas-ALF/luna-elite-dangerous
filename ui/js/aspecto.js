// Ajustes de lectura (prefase 8, bloque 2): tamaño de letra, densidad, tema, filas por página y qué
// columnas enseña cada tabla de Rutas. Se aplican al arrancar y en el momento de elegirlos.
// Se guardan en config.json (Python los valida); la ventana no recuerda nada por su cuenta.
import * as api from './api.js';
import { configurarPaginacion } from './tabla.js';

const raiz = document.documentElement;
// Hasta que llegan los ajustes, cada modo enseña todas sus columnas: mejor de más que una tabla vacía.
const columnas = { un_salto: null, bucle: null, cadena: null, circuito: null };
const oyentes = new Set();

/** Pone el tamaño de letra, la densidad, el tema y el vidrio en <html>; el CSS hace el resto con tokens. */
export function aplicar({ tamano_letra: letra, densidad, tema, vidrio }) {
  if (letra !== undefined) raiz.dataset.letra = letra;
  if (densidad !== undefined) raiz.dataset.densidad = densidad;
  if (tema !== undefined) raiz.dataset.tema = tema;
  if (vidrio !== undefined) raiz.dataset.vidrio = vidrio;
}

// `main.py` pone el tema y el vidrio en el fragmento de la URL: aplicarlos al cargar el módulo evita ver el Sobrio
// hasta que responde Python. Lo que no sea un valor conocido se ignora.
const ARRANQUE = new URLSearchParams(location.hash.slice(1));
const TEMAS = ['sobrio', 'lunar'];
const VIDRIOS = ['desenfocado', 'liso'];
if (TEMAS.includes(ARRANQUE.get('tema'))) raiz.dataset.tema = ARRANQUE.get('tema');
if (VIDRIOS.includes(ARRANQUE.get('vidrio'))) raiz.dataset.vidrio = ARRANQUE.get('vidrio');

/** Las columnas que el usuario eligió para un modo, o `null` si aún no se conocen. */
export const elegidas = (modo) => columnas[modo];

/** `aviso()` se llama cada vez que cambian las columnas elegidas, para repintar lo que ya se enseña. */
export function alCambiarColumnas(aviso) {
  oyentes.add(aviso);
}

export function fijarColumnas(modo, nuevas) {
  columnas[modo] = nuevas;
  for (const aviso of oyentes) aviso();
}

/** Lee los ajustes y los aplica. Devuelve lo leído, o `null` si Python no respondió. */
export async function cargarAspecto() {
  let datos;
  try {
    datos = await api.ajustesDeAspecto();
  } catch (error) {
    console.error(error);
    return null;
  }
  if (datos.error) return null;
  aplicar(datos);
  configurarPaginacion({
    filas: datos.filas_por_pagina,
    opciones: datos.opciones.filas,
    alCambiar: async (filas) => {
      const respuesta = await api.guardarFilasPorPagina(filas);
      // Si no se pudo guardar, la tabla sigue como se ve: solo se pierde la elección al cerrar.
      if (respuesta.error) console.error(`no se guardaron las filas por página: ${respuesta.error}`);
    },
  });
  for (const [modo, { elegidas: nuevas }] of Object.entries(datos.columnas)) columnas[modo] = nuevas;
  return datos;
}
