// Paneles «Retención de precios», «Búsqueda de rutas» y «EDDN» de Configuración.
import * as api from './api.js';
import { texto } from './i18n.js';

function campos(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  return c;
}

function mostrarTexto(elemento, mensaje) {
  elemento.hidden = !mensaje;
  elemento.textContent = mensaje ?? '';
}

const mensajeDeError = (codigo) => texto(`configuracion.errores.${codigo}`);

export function crearPanelRetencion(raiz) {
  const c = campos(raiz);

  c.retencion_formulario.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    mostrarTexto(c.retencion_error, null);
    mostrarTexto(c.retencion_resultado, null);
    const respuesta = await api.guardarRetencion(
      c.retencion_visitados.valueAsNumber,
      c.retencion_antiguedad.valueAsNumber,
    );
    if (respuesta.error) mostrarTexto(c.retencion_error, mensajeDeError(respuesta.error));
    else mostrarTexto(c.retencion_resultado, texto('configuracion.retencion.guardado'));
  });

  return {
    cargar(retencion) {
      c.retencion_visitados.value = String(retencion.visitados_dias);
      c.retencion_antiguedad.value = String(retencion.antiguedad_maxima_dias);
    },
  };
}

function marcadas(raiz) {
  return [...raiz.querySelectorAll('input[name="tipos"]:checked')].map((casilla) => casilla.value);
}

/** Lo que pueden pedir las búsquedas de Rutas y Ahora; los tipos son los que trae un perfil nuevo. */
export function crearPanelComercio(raiz) {
  const c = campos(raiz);
  const entradas = { tope_antiguedad_dias: c.comercio_tope, tipos: c.comercio_tipos };
  let maximo = Number(c.comercio_tope.max);

  function limpiar() {
    mostrarTexto(c.comercio_error, null);
    mostrarTexto(c.comercio_resultado, null);
    for (const entrada of Object.values(entradas)) entrada.removeAttribute('aria-invalid');
  }

  function pintar(datos) {
    maximo = datos.tope_maximo_dias;
    c.comercio_tope.max = String(maximo);
    c.comercio_tope.value = String(datos.tope_antiguedad_dias);
    c.comercio_tope_ayuda.textContent = texto('configuracion.comercio.tope_ayuda', { maximo });
    for (const casilla of raiz.querySelectorAll('input[name="tipos"]')) {
      casilla.checked = datos.tipos.includes(casilla.value);
    }
  }

  function rechazar(respuesta) {
    const entrada = entradas[respuesta.campo];
    if (!entrada) {
      mostrarTexto(c.comercio_error, mensajeDeError(respuesta.error));
      return;
    }
    entrada.setAttribute('aria-invalid', 'true');
    mostrarTexto(c.comercio_error, texto(`configuracion.comercio.errores.${respuesta.campo}`, { maximo }));
    (entrada.querySelector('input') ?? entrada).focus();
  }

  c.comercio_formulario.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    limpiar();
    const tope = Number.isNaN(c.comercio_tope.valueAsNumber) ? null : c.comercio_tope.valueAsNumber;
    const respuesta = await api.guardarAjustesDeBusqueda(tope, marcadas(raiz));
    if (respuesta.error) {
      rechazar(respuesta);
      return;
    }
    pintar(respuesta);
    mostrarTexto(c.comercio_resultado, texto('configuracion.comercio.guardado'));
  });

  return {
    async cargar() {
      limpiar();
      const datos = await api.ajustesDeBusqueda();
      if (datos.error) mostrarTexto(c.comercio_error, mensajeDeError(datos.error));
      else pintar(datos);
    },
  };
}

export function crearPanelEddn(raiz) {
  const c = campos(raiz);

  c.eddn_activado.addEventListener('change', async () => {
    mostrarTexto(c.eddn_error, null);
    const respuesta = await api.establecerEddn(c.eddn_activado.checked);
    if (respuesta.error) {
      mostrarTexto(c.eddn_error, mensajeDeError(respuesta.error));
      // El ajuste no cambió: la casilla vuelve a lo que de verdad hay.
      c.eddn_activado.checked = !c.eddn_activado.checked;
    }
  });

  return {
    cargar(eddn) {
      c.eddn_activado.checked = eddn.activado;
      c.eddn_activado.disabled = !eddn.disponible;
      c.eddn_sin_base.hidden = eddn.disponible;
    },
  };
}
