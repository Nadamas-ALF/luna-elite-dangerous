// Detalle de una ruta (SPEC.md §9.2): tramos, tiempos y de dónde salen, y la
// antigüedad y el origen de cada dato.
import { antiguedad, crear, estacion, origen } from './celdas.js';
import { copiar } from './copiar.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';

const clave = (nombre) => `comercio.rutas.detalle.${nombre}`;

function fila(lista, nombre, ...valor) {
  const dd = crear('dd');
  dd.append(...valor.map((v) => (typeof v === 'string' ? crear('span', null, v) : v)));
  lista.append(crear('dt', null, texto(clave(nombre))), dd);
}

const nota = (mensaje) => crear('p', 'motivo', mensaje);

function conCopia(lado) {
  const bloque = estacion(lado);
  const sistema = bloque.querySelector('.estacion__sistema');
  sistema.classList.add('seleccionable');
  const boton = crear('button', 'boton boton--vidrio boton--pequeno', texto('estado.ubicacion.copiar'));
  boton.type = 'button';
  boton.setAttribute('aria-label', texto(clave('copiar_aria'), { sistema: lado.sistema }));
  boton.addEventListener('click', () => copiar(boton, lado.sistema, sistema));
  const contenedor = crear('div', 'datos__con-accion');
  contenedor.append(bloque, boton);
  return contenedor;
}

function dato(lado) {
  const valor = crear('span', 'dato');
  valor.append(antiguedad(lado), crear('span', 'dato__origen', origen(lado)));
  return valor;
}

/** Cada parte con su duración y de dónde sale (SPEC.md §8.4); sin salto no hay salida. */
function tiempo(tramo) {
  const partes = tramo.tiempo.filter((p) => p.segundos > 0).map((p) => nota(texto(clave('parte'), {
    parte: texto(clave(`partes.${p.parte}`)),
    duracion: formato.duracion(p.segundos),
    fuente: texto(clave(`fuente.${p.fuente}`), { muestras: p.muestras }),
  })));
  return [formato.duracion(tramo.segundos), ...partes];
}

function llegada(lado) {
  const ls = formato.segundosLuz(lado.distancia_ls);
  return nota(texto(clave(lado.planetaria ? 'llegada_planetaria' : 'llegada'), { ls }));
}

function bloqueDeTramo(titulo, tramo) {
  const seccion = crear('section', 'tramo');
  const lista = crear('dl', 'datos');
  const { compra, venta } = tramo;
  fila(lista, 'comprar_en', conCopia(compra), nota(texto(clave('desde_origen'), {
    distancia: formato.anosLuz(compra.distancia_origen),
  })));
  fila(lista, 'precio_compra', formato.creditos(compra.precio));
  fila(lista, 'stock', formato.toneladas(compra.cantidad));
  fila(lista, 'dato', dato(compra));
  fila(lista, 'vender_en', conCopia(venta), llegada(venta));
  fila(lista, 'precio_venta', formato.creditos(venta.precio));
  fila(lista, 'demanda', formato.toneladas(venta.cantidad));
  fila(lista, 'dato', dato(venta));
  fila(lista, 'toneladas', formato.toneladas(tramo.toneladas));
  fila(lista, 'ganancia_tonelada', formato.creditosPorTonelada(tramo.ganancia_tonelada));
  fila(lista, 'ganancia_viaje', formato.creditos(tramo.ganancia_viaje));
  fila(lista, 'distancia', texto(clave('distancia_valor'), {
    ly: formato.anosLuz(tramo.distancia_ly),
    saltos: tramo.saltos,
  }));
  fila(lista, 'tiempo', ...tiempo(tramo));
  seccion.append(crear('h3', 'tramo__titulo', titulo), lista);
  return seccion;
}

/** Lo que vale la ruta entera: en un bucle, la suma de ida y vuelta. */
function bloqueDeTotal(titulo, ruta, horasSesion) {
  const seccion = crear('section', 'tramo');
  const lista = crear('dl', 'datos');
  if (titulo) {
    fila(lista, 'ganancia_viaje', formato.creditos(ruta.ganancia_viaje));
    fila(lista, 'tiempo', formato.duracion(ruta.segundos));
  }
  fila(lista, 'ganancia_hora', formato.creditosPorHora(ruta.ganancia_hora));
  lista.append(
    crear('dt', null, texto(clave('ganancia_sesion'), { horas: formato.cantidad(horasSesion) })),
    crear('dd', null, formato.creditos(ruta.ganancia_sesion)),
  );
  fila(lista, 'confianza', formato.porcentaje(ruta.confianza, 1), nota(texto(clave('confianza_ayuda'))));
  if (titulo) seccion.append(crear('h3', 'tramo__titulo', titulo));
  seccion.append(lista);
  return seccion;
}

export function pintarDetalle(contenedor, modo, ruta, horasSesion) {
  if (modo === 'bucle') {
    contenedor.replaceChildren(
      bloqueDeTramo(texto(clave('ida'), { mercancia: ruta.ida.mercancia.nombre }), ruta.ida),
      bloqueDeTramo(texto(clave('vuelta'), { mercancia: ruta.vuelta.mercancia.nombre }), ruta.vuelta),
      bloqueDeTotal(texto(clave('total')), ruta, horasSesion),
    );
  } else {
    contenedor.replaceChildren(
      bloqueDeTramo(ruta.mercancia.nombre, ruta),
      bloqueDeTotal(null, ruta, horasSesion),
    );
  }
}
