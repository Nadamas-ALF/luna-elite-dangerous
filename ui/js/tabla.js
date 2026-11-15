// Tabla de resultados que comparten Rutas y Ahora. Cada columna es
// [nombre, prioridad, valor]; el rótulo sale de `${claves}.${nombre}`.
import { crear } from './celdas.js';
import { texto } from './i18n.js';

// Las esenciales van primero, para que se vean aunque la tabla tenga que desplazarse,
// y las secundarias son las primeras en ocultarse al estrechar (§9.3).
export const ESENCIAL = 'esencial';
export const SECUNDARIA = 'secundaria';

// Columnas de texto; las demás llevan cifras, a la derecha y con números tabulares.
const DE_TEXTO = new Set([
  'mercancia', 'comprar', 'vender', 'ida', 'vuelta', 'estacion_a', 'estacion_b', 'origen',
]);

function clasesDe(nombre, prioridad) {
  return [DE_TEXTO.has(nombre) ? null : 'cifra', prioridad && `col--${prioridad}`]
    .filter(Boolean)
    .join(' ');
}

function cabecera(columnas, claves) {
  const fila = crear('tr');
  for (const [nombre, prioridad] of columnas) {
    const celda = crear('th', clasesDe(nombre, prioridad), texto(`${claves}.${nombre}`));
    celda.scope = 'col';
    fila.append(celda);
  }
  return fila;
}

function filaDe(columnas, dato) {
  const fila = crear('tr');
  for (const [nombre, prioridad, valor] of columnas) {
    const celda = crear('td', clasesDe(nombre, prioridad));
    const contenido = valor(dato);
    if (typeof contenido === 'string') celda.textContent = contenido;
    else celda.append(contenido);
    fila.append(celda);
  }
  return fila;
}

function seleccionable(fila, cuerpo, alElegir) {
  fila.classList.add('resultado');
  fila.tabIndex = 0;
  fila.setAttribute('aria-selected', 'false');
  const elegir = () => {
    for (const otra of cuerpo.rows) otra.setAttribute('aria-selected', 'false');
    fila.setAttribute('aria-selected', 'true');
    alElegir();
  };
  fila.addEventListener('click', elegir);
  fila.addEventListener('keydown', (evento) => {
    if (evento.key !== 'Enter' && evento.key !== ' ') return;
    evento.preventDefault();
    elegir();
  });
}

/** Rellena `tabla` (con su thead y tbody). Con `alElegir`, las filas se pueden seleccionar. */
export function pintarTabla(tabla, columnas, datos, claves, alElegir) {
  tabla.tHead.replaceChildren(cabecera(columnas, claves));
  const cuerpo = tabla.tBodies[0];
  cuerpo.replaceChildren(
    ...datos.map((dato) => {
      const fila = filaDe(columnas, dato);
      if (alElegir) seleccionable(fila, cuerpo, () => alElegir(dato));
      return fila;
    }),
  );
}

/** Una tabla nueva dentro de su contenedor, que se desplaza en horizontal si no cabe. */
export function crearTabla(titulo) {
  const contenedor = crear('div', 'tabla-contenedor');
  const tabla = crear('table', 'tabla');
  tabla.append(crear('caption', 'solo-lectores', titulo), crear('thead'), crear('tbody'));
  contenedor.append(tabla);
  return { contenedor, tabla };
}
