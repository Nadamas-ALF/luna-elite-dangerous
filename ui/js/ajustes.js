// Paneles «Retención de precios» y «EDDN» de Configuración.
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
