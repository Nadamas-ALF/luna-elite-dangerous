// Pantalla Ahora (SPEC.md §9.2): dónde vender lo que llevas y qué comprar aquí.
// Se recalcula sola al atracar, al despegar o al cambiar la carga, con el perfil de Rutas.
import * as api from './api.js';
import { antiguedad, crear, estacion, origen } from './celdas.js';
import { pintarDetalle } from './detalle.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';
import { COLUMNAS as COLUMNAS_DE_RUTAS } from './rutas.js';
import { crearTabla, ESENCIAL, pintarTabla, SECUNDARIA } from './tabla.js';

const clave = (nombre) => `comercio.ahora.${nombre}`;

const COLUMNAS_DE_VENTA = [
  ['vender', ESENCIAL, (v) => estacion(v.venta)],
  ['ingreso_hora', ESENCIAL, (v) => formato.creditosPorHora(v.ingreso_hora)],
  ['antiguedad', ESENCIAL, (v) => antiguedad(v.venta)],
  ['precio_venta', null, (v) => formato.creditos(v.venta.precio)],
  ['toneladas', null, (v) => formato.toneladas(v.toneladas)],
  ['ingreso', null, (v) => formato.creditos(v.ingreso)],
  ['ganancia', null, (v) => (v.ganancia === null ? texto('formato.sin_dato') : formato.creditos(v.ganancia))],
  ['saltos', null, (v) => String(v.saltos)],
  ['distancia_ly', SECUNDARIA, (v) => formato.anosLuz(v.distancia_ly)],
  ['distancia_ls', SECUNDARIA, (v) => formato.segundosLuz(v.venta.distancia_ls)],
  ['tiempo', null, (v) => formato.duracion(v.segundos)],
  ['origen', SECUNDARIA, (v) => origen(v.venta)],
];

// Desde aquí se compra siempre en la estación donde estás: esa columna sobra.
const COLUMNAS_DESDE_AQUI = COLUMNAS_DE_RUTAS.un_salto.filter(([nombre]) => nombre !== 'comprar');

function campos(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  return c;
}

function mostrarTexto(elemento, mensaje) {
  elemento.hidden = !mensaje;
  elemento.textContent = mensaje ?? '';
}

/** Lo que dispara un recálculo: atracar o despegar, y cualquier cambio en la bodega. */
function firmaDe(estado) {
  const { ubicacion, carga } = estado;
  return JSON.stringify([ubicacion?.estacion?.nombre ?? null, carga?.mercancias ?? null]);
}

function resumenDeArticulo(articulo) {
  const toneladas = formato.toneladas(articulo.cantidad);
  if (articulo.precio_compra === null) return texto(clave('vender.sin_precio'), { toneladas });
  const precio = formato.creditosPorTonelada(articulo.precio_compra);
  return texto(clave('vender.comprada'), { toneladas, precio });
}

function bloqueDeArticulo(articulo) {
  const bloque = crear('section', 'articulo');
  const { nombre } = articulo.mercancia;
  bloque.append(crear('h3', 'articulo__titulo', nombre), crear('p', 'motivo', resumenDeArticulo(articulo)));
  if (articulo.destinos.length === 0) {
    bloque.append(crear('p', 'motivo', texto(clave('vender.sin_destinos'))));
    return bloque;
  }
  const { contenedor, tabla } = crearTabla(texto(clave('vender.tabla'), { mercancia: nombre }));
  pintarTabla(tabla, COLUMNAS_DE_VENTA, articulo.destinos, clave('columnas'));
  bloque.append(contenedor);
  return bloque;
}

function mensajeDeError(respuesta) {
  if (respuesta.error !== 'perfil') return texto(clave(`errores.${respuesta.error}`));
  return texto(clave('errores.perfil'), { campo: texto(`comercio.perfil.${respuesta.campo}`) });
}

export function crearVistaAhora(raiz, perfil) {
  const c = campos(raiz);
  let visible = false;
  let firma = null;
  let turno = 0;
  let horasSesion = 0;

  function limpiar() {
    c.vender_lista.replaceChildren();
    mostrarTexto(c.vender_motivo, null);
    mostrarTexto(c.desde_aqui_motivo, null);
    c.desde_aqui_contenedor.hidden = true;
    c.detalle.hidden = true;
    mostrarTexto(c.ahora_error, null);
  }

  function pintarVender(vender) {
    mostrarTexto(c.vender_motivo, vender.length === 0 ? texto(clave('vender.vacia')) : null);
    c.vender_lista.replaceChildren(...vender.map(bloqueDeArticulo));
  }

  function elegir(tramo) {
    pintarDetalle(c.detalle_tramos, 'un_salto', tramo, horasSesion);
    c.detalle.hidden = false;
  }

  function pintarDesdeAqui(tramos) {
    if (tramos === null) {
      mostrarTexto(c.desde_aqui_motivo, texto(clave('desde_aqui.sin_atracar')));
      return;
    }
    pintarTabla(c.desde_aqui_tabla, COLUMNAS_DESDE_AQUI, tramos, 'comercio.rutas.columnas', elegir);
    c.desde_aqui_contenedor.hidden = tramos.length === 0;
    mostrarTexto(c.desde_aqui_motivo, tramos.length === 0 ? texto(clave('desde_aqui.nada')) : null);
  }

  async function pedir() {
    const error = await perfil.cargar();
    if (error) return { usado: null, respuesta: { error } };
    const usado = perfil.leer();
    return { usado, respuesta: await api.ahora(usado) };
  }

  async function actualizar() {
    // Solo se pinta la última: Python cancela la anterior de esta pantalla.
    const mio = ++turno;
    mostrarTexto(c.ahora_estado, texto(clave('calculando')));
    let usado = null;
    let respuesta;
    try {
      ({ usado, respuesta } = await pedir());
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (mio !== turno || respuesta.cancelada) return;
    limpiar();
    if (respuesta.error) {
      mostrarTexto(c.ahora_estado, null);
      mostrarTexto(c.ahora_error, mensajeDeError(respuesta));
      return;
    }
    horasSesion = usado.horas_sesion;
    pintarVender(respuesta.vender);
    pintarDesdeAqui(respuesta.desde_aqui);
    mostrarTexto(c.ahora_estado, texto(clave('actualizado'), { hora: formato.hora(new Date()) }));
  }

  c.ahora_actualizar.addEventListener('click', actualizar);

  return {
    mostrar() {
      visible = true;
      actualizar();
    },
    salir() {
      visible = false;
    },
    /** Recibe cada lectura del estado; solo recalcula si cambió algo que importa y se está viendo. */
    alEstado(estado) {
      const nueva = firmaDe(estado);
      if (nueva === firma) return;
      const habiaFirma = firma !== null;
      firma = nueva;
      if (visible && habiaFirma) actualizar();
    },
  };
}
