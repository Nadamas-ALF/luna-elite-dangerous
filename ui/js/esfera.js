// Panel «Esfera de datos». Cambiar el centro o el radio exige confirmación
// (SPEC.md §5.4, regla 6): primero se pide una propuesta a Python, que no cambia
// nada, y solo al confirmar se aplica.
import * as api from './api.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';

// Margen sobre el tamaño del volcado: la importación necesita archivos temporales.
const MARGEN_DE_ESPACIO = 1.1;

function campos(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  return c;
}

function mostrarTexto(elemento, mensaje) {
  elemento.hidden = !mensaje;
  elemento.textContent = mensaje ?? '';
}

export function crearPanelEsfera(raiz, alAplicar) {
  const c = campos(raiz);
  let propuesta = null;

  const mensajeDeError = (codigo) => texto(`configuracion.errores.${codigo}`);

  function pintarActual(esfera) {
    c.esfera_actual.textContent = texto('configuracion.esfera.actual_valor', {
      centro: esfera.nombre,
      radio: formato.cantidad(esfera.radio),
    });
  }

  function cerrarPropuesta() {
    propuesta = null;
    c.esfera_propuesta.hidden = true;
  }

  function botones(principal, alternativa) {
    c.propuesta_confirmar.textContent = principal.texto;
    c.propuesta_confirmar.dataset.descargar = String(principal.descargar);
    c.propuesta_alternativa.hidden = !alternativa;
    if (alternativa) {
      c.propuesta_alternativa.textContent = alternativa.texto;
      c.propuesta_alternativa.dataset.descargar = String(alternativa.descargar);
    }
  }

  function textoDeDescarga(p) {
    const libre = p.libre === null ? '' : formato.bytes(p.libre);
    if (p.descarga_necesaria) {
      return p.tamano === null
        ? texto('configuracion.esfera.propuesta.descarga_si_sin_tamano', { libre })
        : texto('configuracion.esfera.propuesta.descarga_si', {
            tamano: formato.bytes(p.tamano),
            libre,
          });
    }
    const base = texto('configuracion.esfera.propuesta.descarga_no');
    return p.tamano === null
      ? base
      : `${base} ${texto('configuracion.esfera.propuesta.descarga_no_repetir', {
          tamano: formato.bytes(p.tamano),
        })}`;
  }

  function avisoDe(p) {
    if (p.ocupado) return mensajeDeError('ocupado');
    if (!p.descargable) return texto('configuracion.esfera.propuesta.sin_descarga');
    const justo = p.tamano !== null && p.libre !== null && p.libre < p.tamano * MARGEN_DE_ESPACIO;
    return justo && p.descarga_necesaria ? texto('configuracion.esfera.propuesta.espacio_justo') : null;
  }

  function pintarPropuesta(p) {
    propuesta = p;
    c.propuesta_resumen.textContent = texto('configuracion.esfera.propuesta.resumen', {
      centro: p.esfera.nombre,
      radio: formato.cantidad(p.esfera.radio),
    });
    c.propuesta_descarga.textContent = textoDeDescarga(p);
    // Si no hace falta descargar, el propio texto de arriba ya avisa del borrado.
    mostrarTexto(
      c.propuesta_borrado,
      p.descarga_necesaria && p.borra_lo_de_fuera
        ? texto('configuracion.esfera.propuesta.borra_fuera')
        : null,
    );
    mostrarTexto(c.propuesta_aviso, avisoDe(p));
    const puedeDescargar = p.descargable && !p.ocupado;
    if (p.descarga_necesaria) {
      botones(
        puedeDescargar
          ? { texto: texto('configuracion.esfera.propuesta.aplicar_descargar'), descargar: true }
          : { texto: texto('configuracion.esfera.propuesta.aplicar'), descargar: false },
        puedeDescargar
          ? { texto: texto('configuracion.esfera.propuesta.aplicar'), descargar: false }
          : null,
      );
    } else {
      botones(
        { texto: texto('configuracion.esfera.propuesta.aplicar'), descargar: false },
        puedeDescargar
          ? { texto: texto('configuracion.esfera.propuesta.descargar_de_nuevo'), descargar: true }
          : null,
      );
    }
    c.propuesta_confirmar.disabled = p.ocupado;
    c.propuesta_alternativa.disabled = p.ocupado;
    c.esfera_propuesta.hidden = false;
  }

  async function revisar(evento) {
    evento.preventDefault();
    mostrarTexto(c.esfera_error, null);
    mostrarTexto(c.esfera_resultado, null);
    cerrarPropuesta();
    c.esfera_revisar.disabled = true;
    c.esfera_revisar.textContent = texto('configuracion.esfera.comprobando');
    try {
      const respuesta = await api.proponerEsfera(
        c.esfera_centro.value.trim(),
        c.esfera_radio.valueAsNumber,
      );
      if (respuesta.error) mostrarTexto(c.esfera_error, mensajeDeError(respuesta.error));
      else pintarPropuesta(respuesta);
    } finally {
      c.esfera_revisar.disabled = false;
      c.esfera_revisar.textContent = texto('configuracion.esfera.revisar');
    }
  }

  async function aplicar(boton) {
    if (!propuesta) return;
    const nueva = propuesta.esfera;
    const { nombre, radio } = nueva;
    const respuesta = await api.aplicarEsfera(nombre, radio, boton.dataset.descargar === 'true');
    cerrarPropuesta();
    if (respuesta.error) {
      mostrarTexto(c.esfera_error, mensajeDeError(respuesta.error));
      return;
    }
    pintarActual(nueva);
    c.esfera_centro.value = nombre;
    c.esfera_radio.value = String(radio);
    mostrarTexto(
      c.esfera_resultado,
      texto(
        respuesta.descargando
          ? 'configuracion.esfera.aplicada_descargando'
          : 'configuracion.esfera.aplicada',
      ),
    );
    alAplicar();
  }

  c.esfera_formulario.addEventListener('submit', revisar);
  c.propuesta_confirmar.addEventListener('click', () => aplicar(c.propuesta_confirmar));
  c.propuesta_alternativa.addEventListener('click', () => aplicar(c.propuesta_alternativa));
  c.propuesta_cancelar.addEventListener('click', cerrarPropuesta);

  return {
    /** Abre la confirmación con los valores del formulario (la esfera actual, si no se tocaron). */
    revisarActual() {
      c.esfera_formulario.requestSubmit();
      c.esfera_formulario.scrollIntoView({ block: 'center' });
    },
    cargar(esfera) {
      pintarActual(esfera);
      c.esfera_centro.value = esfera.nombre;
      c.esfera_radio.value = String(esfera.radio);
    },
  };
}
