// Buscador de estaciones (prefase 8, bloque 3): dónde está una estación y qué edad tiene su
// mercado. Python busca solo en lo guardado y devuelve una lista corta; aquí solo se pinta.
import * as api from './api.js';
import { antiguedad } from './celdas.js';
import { copiar } from './copiar.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';

const crear = (etiqueta, clase, contenido) => {
  const elemento = document.createElement(etiqueta);
  if (clase) elemento.className = clase;
  if (contenido !== undefined) elemento.textContent = contenido;
  return elemento;
};

function boton(clave, alPulsar) {
  const b = crear('button', 'boton boton--vidrio', texto(clave));
  b.type = 'button';
  b.addEventListener('click', () => alPulsar(b));
  return b;
}

function datos(estacion) {
  const partes = [
    texto(`comercio.estaciones.tipo.${estacion.tipo}`),
    estacion.plataforma ? texto('comercio.estaciones.plataforma', { valor: estacion.plataforma }) : null,
    estacion.distancia_ls === null ? null : formato.segundosLuz(estacion.distancia_ls),
    estacion.distancia_ly === null
      ? null
      : texto('comercio.estaciones.distancia', { ly: formato.anosLuz(estacion.distancia_ly) }),
  ];
  return partes.filter(Boolean).join(' · ');
}

/** `acciones`: lista de `[clave del rótulo, (estación) => …]`; «Copiar sistema» sale siempre. */
function fila(estacion, acciones) {
  const item = crear('li', 'buscador__estacion');
  const nombre = crear('strong', null, estacion.estacion);
  const sistema = crear('span', 'motivo', estacion.sistema);
  const mercado =
    estacion.horas === null
      ? crear('span', 'motivo', texto('comercio.estaciones.sin_mercado'))
      : antiguedad(estacion);
  const botones = crear('div', 'acciones');
  botones.append(
    ...acciones.map(([clave, alPulsar]) => boton(clave, () => alPulsar(estacion))),
    boton('comercio.estaciones.copiar', (b) =>
      copiar(b, estacion.sistema, sistema, texto('comercio.estaciones.copiar')),
    ),
  );
  item.append(nombre, sistema, crear('span', 'motivo', datos(estacion)), mercado, botones);
  return item;
}

export function crearBuscadorDeEstaciones(raiz, acciones) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  let turno = 0;

  function avisar(clave) {
    c.buscador_estado.hidden = !clave;
    c.buscador_estado.textContent = clave ? texto(clave) : '';
  }

  async function buscar(evento) {
    evento.preventDefault();
    const mio = ++turno;
    c.buscador_lista.replaceChildren();
    avisar('comercio.estaciones.buscando');
    let respuesta;
    try {
      respuesta = await api.buscarEstaciones(c.buscador_texto.value);
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (mio !== turno) return;
    if (respuesta.error) {
      avisar(respuesta.error === 'parametro' ? 'comercio.estaciones.demasiado_corto' : 'comercio.estaciones.error');
      return;
    }
    c.buscador_lista.replaceChildren(...respuesta.estaciones.map((e) => fila(e, acciones)));
    if (respuesta.estaciones.length === 0) avisar('comercio.estaciones.ninguna');
    else avisar(respuesta.hay_mas ? 'comercio.estaciones.hay_mas' : null);
  }

  c.buscador_formulario.addEventListener('submit', buscar);
}
