// Panel «Datos de Spansh»: estado del trabajo (descarga e importación) y sus
// controles. Mientras la pantalla está abierta se consulta cada segundo.
import * as api from './api.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';

const INTERVALO_DE_CONSULTA = 1000;
const TIEMPO_DE_CONFIRMACION = 4000;

function campos(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  return c;
}

/** Leer el archivo es lo largo y tiene avance real; guardar en la base es lo corto. */
function pintarImportacion(c, s) {
  const encontrados = formato.decimales(s.encontrados, 0);
  if (s.etapa === 'leyendo' && s.tamano_archivo) {
    c.spansh_barra.max = s.tamano_archivo;
    c.spansh_barra.value = s.leido;
    c.spansh_progreso.textContent = texto('configuracion.spansh.progreso_lectura', {
      porcentaje: formato.porcentaje(s.leido, s.tamano_archivo),
      encontrados,
    });
    return;
  }
  c.spansh_barra.removeAttribute('value');
  c.spansh_progreso.textContent = texto('configuracion.spansh.progreso_guardado', {
    guardados: formato.decimales(s.guardados, 0),
    encontrados,
  });
}

function pintarProgreso(c, s) {
  const descarga = s.fase === 'descargando' || s.fase === 'pausada';
  c.spansh_barra.hidden = !(descarga || s.fase === 'importando');
  c.spansh_progreso.hidden = c.spansh_barra.hidden;
  if (s.fase === 'importando') {
    pintarImportacion(c, s);
  } else if (descarga && s.total) {
    c.spansh_barra.max = s.total;
    c.spansh_barra.value = s.descargado;
    c.spansh_progreso.textContent =
      s.descargado >= s.total
        ? texto('configuracion.spansh.descarga_completa')
        : texto('configuracion.spansh.progreso_descarga', {
            descargado: formato.bytes(s.descargado),
            total: formato.bytes(s.total),
            porcentaje: formato.porcentaje(s.descargado, s.total),
          });
  } else {
    c.spansh_barra.hidden = true;
    c.spansh_progreso.hidden = true;
  }
}

function pintar(c, s) {
  c.spansh_fase.textContent = texto(`configuracion.spansh.fase.${s.fase}`);
  c.spansh_fase.classList.toggle('indicador--apagado', s.fase === 'inactiva' || s.fase === 'pausada');
  c.spansh_fase.classList.toggle('indicador--alerta', s.fase === 'error');
  c.spansh_ultima.textContent = s.ultima
    ? texto('configuracion.spansh.ultima', {
        hace: formato.hace(s.ultima.fecha),
        centro: s.ultima.centro,
        radio: formato.cantidad(s.ultima.radio),
      })
    : texto('configuracion.spansh.nunca');
  pintarProgreso(c, s);
  const error = s.fase === 'error' && s.error ? texto(`configuracion.spansh.errores.${s.error}`) : '';
  c.spansh_error.hidden = !error;
  c.spansh_error.textContent = error;
  const enMarcha = s.fase === 'descargando' || s.fase === 'importando';
  c.spansh_descargar.hidden = s.fase !== 'inactiva';
  c.spansh_pausar.hidden = !enMarcha;
  c.spansh_reanudar.hidden = !(s.fase === 'pausada' || s.fase === 'error');
  c.spansh_cancelar.hidden = s.fase === 'inactiva';
}

export function crearPanelSpansh(raiz, alDescargar) {
  const c = campos(raiz);
  let temporizador = null;
  let enCurso = false;
  let esperandoConfirmacion = null;

  async function refrescar() {
    if (enCurso) return;
    enCurso = true;
    try {
      pintar(c, await api.spansh());
    } catch (error) {
      console.error(error);
    } finally {
      enCurso = false;
    }
  }

  function olvidarConfirmacion() {
    clearTimeout(esperandoConfirmacion);
    esperandoConfirmacion = null;
    c.spansh_cancelar.textContent = texto('configuracion.spansh.cancelar');
  }

  c.spansh_descargar.addEventListener('click', alDescargar);

  c.spansh_pausar.addEventListener('click', async () => {
    await api.pausarDescarga();
    refrescar();
  });

  c.spansh_reanudar.addEventListener('click', async () => {
    await api.reanudarDescarga();
    refrescar();
  });

  // Cancelar borra varios GiB: se pide un segundo clic.
  c.spansh_cancelar.addEventListener('click', async () => {
    if (esperandoConfirmacion === null) {
      c.spansh_cancelar.textContent = texto('configuracion.spansh.cancelar_confirmar');
      esperandoConfirmacion = setTimeout(olvidarConfirmacion, TIEMPO_DE_CONFIRMACION);
      return;
    }
    olvidarConfirmacion();
    await api.cancelarDescarga();
    refrescar();
  });

  return {
    empezar() {
      refrescar();
      temporizador ??= setInterval(refrescar, INTERVALO_DE_CONSULTA);
    },
    parar() {
      clearInterval(temporizador);
      temporizador = null;
      olvidarConfirmacion();
    },
    refrescar,
  };
}
