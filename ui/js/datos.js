// Sección «Datos de LUNA» de Configuración: cuánto ocupan la base y las descargas, y el borrado
// de los datos de mercado. Borrar pide confirmación y dice qué se pierde; Python no borra con
// una descarga en marcha.
import * as api from './api.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';

const INTERVALO_DE_CONSULTA = 1000;

function campos(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  return c;
}

function mostrarTexto(elemento, mensaje) {
  elemento.hidden = !mensaje;
  elemento.textContent = mensaje ?? '';
}

function bytes(valor) {
  return valor === null ? texto('configuracion.datos.sin_dato') : formato.bytes(valor);
}

export function crearPanelDatos(raiz, alBorrar) {
  const c = campos(raiz);
  let temporizador = null;
  let tamanoAntes = null;

  function pintarEspacio(e) {
    c.espacio_base.textContent = bytes(e.base);
    c.espacio_descargas.textContent = bytes(e.descargas);
    c.espacio_libre.textContent = bytes(e.libre);
    c.borrar_pedir.disabled = e.borrando || e.descarga_en_marcha;
    c.borrar_ocupado.hidden = !e.descarga_en_marcha;
    if (e.borrando) c.borrar_confirmacion.hidden = true;
  }

  async function consultar() {
    const espacio = await api.espacioEnDisco();
    if (!espacio.error) pintarEspacio(espacio);
    return espacio;
  }

  function dejarDeConsultar() {
    clearInterval(temporizador);
    temporizador = null;
  }

  function terminar(espacio) {
    dejarDeConsultar();
    if (espacio.borrado_fallido) {
      mostrarTexto(c.borrar_error, texto('configuracion.borrar.errores.fallo'));
      mostrarTexto(c.borrar_resultado, null);
      return;
    }
    mostrarTexto(
      c.borrar_resultado,
      texto('configuracion.borrar.terminado', {
        antes: bytes(tamanoAntes),
        ahora: bytes(espacio.base),
      }),
    );
    alBorrar();
  }

  async function seguirElBorrado() {
    try {
      const espacio = await consultar();
      if (!espacio.error && !espacio.borrando) terminar(espacio);
    } catch (error) {
      console.error(error);
    }
  }

  function empezarASeguir() {
    mostrarTexto(c.borrar_resultado, texto('configuracion.borrar.borrando'));
    c.borrar_pedir.disabled = true;
    temporizador ??= setInterval(seguirElBorrado, INTERVALO_DE_CONSULTA);
  }

  c.borrar_pedir.addEventListener('click', () => {
    mostrarTexto(c.borrar_error, null);
    mostrarTexto(c.borrar_resultado, null);
    c.borrar_confirmacion.hidden = false;
    c.borrar_cancelar.focus();
  });

  c.borrar_cancelar.addEventListener('click', () => {
    c.borrar_confirmacion.hidden = true;
    c.borrar_pedir.focus();
  });

  c.borrar_confirmar.addEventListener('click', async () => {
    c.borrar_confirmacion.hidden = true;
    mostrarTexto(c.borrar_error, null);
    const antes = await api.espacioEnDisco();
    tamanoAntes = antes.error ? null : antes.base;
    const respuesta = await api.borrarDatosDeMercado();
    if (respuesta.error) {
      mostrarTexto(c.borrar_error, texto(`configuracion.borrar.errores.${respuesta.error}`));
      return;
    }
    empezarASeguir();
    seguirElBorrado();
  });

  return {
    async cargar() {
      const espacio = await consultar();
      if (!espacio.error && espacio.borrando) empezarASeguir();
    },
    parar: dejarDeConsultar,
  };
}
