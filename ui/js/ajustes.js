// Paneles «Retención de precios», «Búsqueda de rutas», «Sesiones de Rendimiento»,
// «Sonido de las alertas» y «EDDN» de Configuración.
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

/** Cuándo una pausa parte una sesión; con «por partida», solo el cierre del juego. */
export function crearPanelSesiones(raiz) {
  const c = campos(raiz);
  let limites = { minimo: 1, maximo: 12 };

  function reflejar() {
    c.sesiones_pausa.disabled = c.sesiones_por_partida.checked;
    c.sesiones_pausa_valor.textContent = texto('configuracion.sesiones.pausa_valor', {
      horas: c.sesiones_pausa.value,
    });
  }

  function pintar(datos) {
    limites = { minimo: datos.minimo, maximo: datos.maximo };
    c.sesiones_pausa.min = String(datos.minimo);
    c.sesiones_pausa.max = String(datos.maximo);
    c.sesiones_pausa.value = String(datos.pausa_horas);
    c.sesiones_por_partida.checked = datos.por_partida;
    reflejar();
  }

  function limpiar() {
    mostrarTexto(c.sesiones_error, null);
    mostrarTexto(c.sesiones_resultado, null);
  }

  c.sesiones_pausa.addEventListener('input', reflejar);
  c.sesiones_por_partida.addEventListener('change', reflejar);
  c.sesiones_formulario.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    limpiar();
    const horas = c.sesiones_pausa.valueAsNumber;
    const respuesta = await api.guardarAjustesDeSesiones(horas, c.sesiones_por_partida.checked);
    if (respuesta.error === 'parametro') {
      mostrarTexto(c.sesiones_error, texto(`configuracion.sesiones.errores.${respuesta.campo}`, limites));
    } else if (respuesta.error) {
      mostrarTexto(c.sesiones_error, mensajeDeError(respuesta.error));
    } else {
      pintar(respuesta);
      mostrarTexto(c.sesiones_resultado, texto('configuracion.sesiones.guardado'));
    }
  });

  return {
    async cargar() {
      limpiar();
      const datos = await api.ajustesDeSesiones();
      if (datos.error) mostrarTexto(c.sesiones_error, mensajeDeError(datos.error));
      else pintar(datos);
    },
  };
}

/** Si las alertas suenan y a qué volumen; «Probar» suena con el volumen elegido aunque no se guarde. */
export function crearPanelSonido(raiz) {
  const c = campos(raiz);

  function reflejar() {
    c.sonido_volumen.disabled = !c.sonido_activado.checked;
    c.sonido_volumen_valor.textContent = texto('configuracion.sonido.volumen_valor', {
      volumen: c.sonido_volumen.value,
    });
  }

  function pintar(datos) {
    c.sonido_activado.checked = datos.activado;
    c.sonido_volumen.value = String(datos.volumen);
    reflejar();
  }

  function limpiar() {
    mostrarTexto(c.sonido_error, null);
    mostrarTexto(c.sonido_resultado, null);
  }

  function mostrarRespuesta(respuesta, alAcertar) {
    if (respuesta.error) mostrarTexto(c.sonido_error, mensajeDeError(respuesta.error));
    else alAcertar(respuesta);
  }

  c.sonido_volumen.addEventListener('input', reflejar);
  c.sonido_activado.addEventListener('change', reflejar);
  c.sonido_probar.addEventListener('click', async () => {
    limpiar();
    mostrarRespuesta(await api.probarSonido(c.sonido_volumen.valueAsNumber), () => {});
  });
  c.sonido_formulario.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    limpiar();
    const respuesta = await api.guardarAjustesDeSonido(
      c.sonido_activado.checked,
      c.sonido_volumen.valueAsNumber,
    );
    mostrarRespuesta(respuesta, (datos) => {
      pintar(datos);
      mostrarTexto(c.sonido_resultado, texto('configuracion.sonido.guardado'));
    });
  });

  return {
    async cargar() {
      limpiar();
      mostrarRespuesta(await api.ajustesDeSonido(), pintar);
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
