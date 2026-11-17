// Piezas que comparten Rutas y Ahora: una estación, la antigüedad de un dato y
// de dónde vino. Todo con textContent: los nombres llegan de EDDN y de Spansh.
import { copiar } from './copiar.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';

// Los mismos cortes que la confianza (docs/decisiones.md, «Fase 5»).
const HORAS_RECIENTE = 1;
const HORAS_ACEPTABLE = 24;

export function crear(etiqueta, clase, contenido) {
  const elemento = document.createElement(etiqueta);
  if (clase) elemento.className = clase;
  if (contenido !== undefined) elemento.textContent = contenido;
  return elemento;
}

/** La estación y, debajo, su sistema. `lado` es una punta de un trato tal como la manda Python. */
export function estacion(lado) {
  const bloque = crear('div', 'estacion');
  bloque.append(
    crear('span', 'estacion__nombre', lado.estacion),
    crear('span', 'estacion__sistema', lado.sistema),
  );
  return bloque;
}

/** En el detalle: el botón que copia el sistema; `fuente` es el elemento con su nombre. */
export function botonCopiarSistema(lado, fuente) {
  const boton = crear('button', 'boton boton--vidrio boton--pequeno', texto('estado.ubicacion.copiar'));
  boton.type = 'button';
  boton.setAttribute('aria-label', texto('comercio.rutas.detalle.copiar_aria', { sistema: lado.sistema }));
  boton.addEventListener('click', () => copiar(boton, lado.sistema, fuente));
  return boton;
}

/** En las tablas: el sistema es un enlace que se copia al pulsarlo, sin botón aparte. */
export function estacionEnlazada(lado) {
  const bloque = crear('div', 'estacion');
  const enlace = crear('button', 'estacion__sistema enlace-copiar', lado.sistema);
  enlace.type = 'button';
  enlace.title = texto('comercio.rutas.copiar_sistema', { sistema: lado.sistema });
  enlace.addEventListener('click', (evento) => {
    // La fila entera se elige al pulsar: copiar no debe abrir el detalle.
    evento.stopPropagation();
    copiar(enlace, lado.sistema, enlace, lado.sistema);
  });
  bloque.append(crear('span', 'estacion__nombre', lado.estacion), enlace);
  return bloque;
}

function edad(horas) {
  if (horas < HORAS_RECIENTE) return 'reciente';
  return horas < HORAS_ACEPTABLE ? 'aceptable' : 'vieja';
}

/** «hace 3 h», con el color de su edad; el texto basta sin el color (DESIGN.md §2). */
export function antiguedad(lado) {
  return crear('span', `antiguedad antiguedad--${edad(lado.horas)}`, formato.hace(lado.observado));
}

export const masViejo = (lados) => lados.reduce((viejo, lado) => (lado.horas > viejo.horas ? lado : viejo));

export const origen = (lado) => texto(`comercio.perfil.origen_dato.${lado.origen}`);

/** «EDDN», o «EDDN, Spansh» si los datos vienen de varios sitios. */
export const origenes = (lados) => [...new Set(lados.map(origen))].join(', ');
