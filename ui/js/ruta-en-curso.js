// Panel «Ruta en curso» de Alertas (prefase 8, bloque 5): el aviso de «hay una ruta mejor que la
// que haces» y copiar al portapapeles el sistema de la siguiente parada al despegar. Los valores
// viven en config.json; Python los valida y aquí solo se pintan y se mandan.
import * as api from './api.js';
import { texto } from './i18n.js';

const clave = (nombre) => `comercio.alertas.en_curso.${nombre}`;

function mostrarTexto(elemento, mensaje) {
  elemento.hidden = !mensaje;
  elemento.textContent = mensaje ?? '';
}

export function crearPanelRutaEnCurso(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo^="en_curso_"]')) c[elemento.dataset.campo] = elemento;
  const formulario = c.en_curso_formulario;
  const entrada = (nombre) => formulario.elements.namedItem(nombre);
  let limites = { margen_minimo: 1, margen_maximo: 1000 };

  function pintar(ajustes) {
    limites = { margen_minimo: ajustes.margen_minimo, margen_maximo: ajustes.margen_maximo };
    entrada('aviso_mejor').checked = ajustes.aviso_mejor;
    entrada('margen_pct').value = String(ajustes.margen_pct);
    entrada('portapapeles').checked = ajustes.portapapeles;
  }

  function limpiar() {
    mostrarTexto(c.en_curso_error, null);
    mostrarTexto(c.en_curso_resultado, null);
    entrada('margen_pct').removeAttribute('aria-invalid');
  }

  function rechazar(respuesta) {
    if (respuesta.campo === 'margen_pct') {
      entrada('margen_pct').setAttribute('aria-invalid', 'true');
      entrada('margen_pct').focus();
      mostrarTexto(c.en_curso_error, texto(clave('errores.margen'), limites));
      return;
    }
    mostrarTexto(c.en_curso_error, texto(clave(`errores.${respuesta.error}`)));
  }

  formulario.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    limpiar();
    const margen = entrada('margen_pct').valueAsNumber;
    let respuesta;
    try {
      respuesta = await api.guardarAjustesDeRutaEnCurso(
        entrada('aviso_mejor').checked,
        Number.isNaN(margen) ? null : margen,
        entrada('portapapeles').checked,
      );
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (respuesta.error) {
      rechazar(respuesta);
      return;
    }
    pintar(respuesta);
    mostrarTexto(c.en_curso_resultado, texto(clave('guardado')));
  });

  return {
    async cargar() {
      limpiar();
      let respuesta;
      try {
        respuesta = await api.ajustesDeRutaEnCurso();
      } catch (error) {
        console.error(error);
        respuesta = { error: 'sin_respuesta' };
      }
      if (respuesta.error) mostrarTexto(c.en_curso_error, texto(clave(`errores.${respuesta.error}`)));
      else pintar(respuesta);
    },
  };
}
