// Panel «Lectura» de Configuración: tamaño de letra, densidad, tema y columnas de Rutas. Cada cambio se
// aplica al momento y se guarda sin botón; si Python no lo guarda, la elección vuelve a como estaba.
import * as api from './api.js';
import * as aspecto from './aspecto.js';
import { crear } from './celdas.js';
import { texto } from './i18n.js';

const MODOS_DE_COLUMNAS = ['un_salto', 'bucle', 'cadena', 'circuito'];

function campos(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  return c;
}

function mostrarTexto(elemento, mensaje) {
  elemento.hidden = !mensaje;
  elemento.textContent = mensaje ?? '';
}

let siguienteId = 0;

function opcionDeRadio(nombre, valor, rotulo) {
  const etiqueta = crear('label', 'modo');
  const entrada = crear('input');
  entrada.type = 'radio';
  entrada.name = nombre;
  entrada.value = valor;
  etiqueta.append(entrada, crear('span', null, rotulo));
  return { etiqueta, entrada };
}

function opcionDeColumna(modo, nombre) {
  const etiqueta = crear('label', 'casilla');
  const entrada = crear('input');
  entrada.type = 'checkbox';
  entrada.value = nombre;
  entrada.id = `columna-${modo}-${siguienteId++}`;
  etiqueta.htmlFor = entrada.id;
  etiqueta.append(entrada, crear('span', null, texto(`comercio.rutas.columnas.${nombre}`)));
  return { etiqueta, entrada };
}

export function crearPanelLectura(raiz) {
  const c = campos(raiz);
  const ajustes = {};
  const columnas = {};
  const cambios = {};
  let construido = false;

  function limpiar() {
    mostrarTexto(c.lectura_error, null);
    mostrarTexto(c.lectura_resultado, null);
  }

  /** Llama a Python y dice si lo guardó, dejando el motivo a la vista si no. */
  async function guardar(guardarEnPython) {
    limpiar();
    let respuesta;
    try {
      respuesta = await guardarEnPython();
    } catch (error) {
      console.error(error);
      respuesta = { error: 'no_disponible' };
    }
    if (respuesta.error) {
      mostrarTexto(c.lectura_error, texto(`configuracion.errores.${respuesta.error}`));
      return false;
    }
    mostrarTexto(c.lectura_resultado, texto('configuracion.lectura.guardado'));
    return true;
  }

  /** El vidrio liso solo tiene sentido con el tema Lunar: con el Sobrio no hay vidrio que alisar. */
  function mostrarVidrio() {
    c.lectura_vidrio_campo.hidden = ajustes.tema?.actual !== 'lunar';
  }

  /** Un control segmentado (tamaño o densidad) que se aplica al elegir y se deshace si no se guarda. */
  function construirAjuste(campo, contenedor, valores, guardarEnPython) {
    const entradas = new Map();
    // Las llamadas de un mismo ajuste van en fila: pywebview atiende cada una en un hilo propio y
    // sin la fila un clic viejo podría llegar a Python después del último.
    // `confirmado` es lo último que Python guardó: a eso se vuelve si falla un guardado.
    const ajuste = { actual: null, confirmado: null, cambios: 0, enCamino: 0, entradas, fila: Promise.resolve() };
    for (const valor of valores) {
      const { etiqueta, entrada } = opcionDeRadio(`lectura_${campo}`, valor, texto(`configuracion.lectura.${campo}.${valor}`));
      entrada.addEventListener('change', async () => {
        const mio = ++ajuste.cambios;
        ajuste.enCamino += 1;
        ajuste.actual = valor;
        aspecto.aplicar({ [campo]: valor });
        mostrarVidrio();
        const guardado = ajuste.fila.then(() => guardar(() => guardarEnPython(valor)));
        ajuste.fila = guardado;
        const bien = await guardado;
        ajuste.enCamino -= 1;
        if (bien) ajuste.confirmado = valor;
        // Si ya se eligió otra cosa después, ese cambio manda: no se deshace por uno viejo.
        if (bien || mio !== ajuste.cambios) return;
        ajuste.actual = ajuste.confirmado;
        aspecto.aplicar({ [campo]: ajuste.confirmado });
        mostrarVidrio();
        entradas.get(ajuste.confirmado).checked = true;
      });
      entradas.set(valor, entrada);
      contenedor.append(etiqueta);
    }
    return ajuste;
  }

  function construirColumnas(modo, disponibles) {
    const casillas = new Map();
    for (const nombre of disponibles) {
      const { etiqueta, entrada } = opcionDeColumna(modo, nombre);
      entrada.addEventListener('change', () => elegirColumnas(modo, casillas, entrada));
      casillas.set(nombre, entrada);
      c[`lectura_columnas_${modo}`].append(etiqueta);
    }
    return casillas;
  }

  async function elegirColumnas(modo, casillas, tocada) {
    const marcadas = [...casillas].filter(([, entrada]) => entrada.checked).map(([nombre]) => nombre);
    if (marcadas.length === 0) {
      tocada.checked = true;
      limpiar();
      mostrarTexto(c.lectura_error, texto('configuracion.lectura.errores.columnas'));
      return;
    }
    const mio = (cambios[modo] = (cambios[modo] ?? 0) + 1);
    if (await guardar(() => api.guardarColumnas(modo, marcadas))) aspecto.fijarColumnas(modo, marcadas);
    else if (mio === cambios[modo]) tocada.checked = !tocada.checked;
  }

  function construir(datos) {
    const { opciones } = datos;
    ajustes.tamano_letra = construirAjuste('tamano_letra', c.lectura_letra, opciones.tamanos, api.guardarTamanoDeLetra);
    ajustes.densidad = construirAjuste('densidad', c.lectura_densidad, opciones.densidades, api.guardarDensidad);
    ajustes.tema = construirAjuste('tema', c.lectura_tema, opciones.temas, api.guardarTema);
    ajustes.vidrio = construirAjuste('vidrio', c.lectura_vidrio, opciones.vidrios, api.guardarVidrio);
    for (const modo of MODOS_DE_COLUMNAS) columnas[modo] = construirColumnas(modo, datos.columnas[modo].disponibles);
  }

  function reflejar(datos) {
    for (const [campo, ajuste] of Object.entries(ajustes)) {
      // Con un guardado en camino, lo leído es anterior a él: la elección en pantalla manda.
      if (ajuste.enCamino > 0) continue;
      ajuste.actual = ajuste.confirmado = datos[campo];
      ajuste.entradas.get(datos[campo]).checked = true;
      aspecto.aplicar({ [campo]: datos[campo] });
    }
    mostrarVidrio();
    for (const modo of MODOS_DE_COLUMNAS) {
      for (const [nombre, entrada] of columnas[modo]) {
        entrada.checked = datos.columnas[modo].elegidas.includes(nombre);
      }
    }
  }

  return {
    async cargar() {
      limpiar();
      let datos;
      try {
        datos = await api.ajustesDeAspecto();
      } catch (error) {
        console.error(error);
        datos = { error: 'no_disponible' };
      }
      if (datos.error) {
        mostrarTexto(c.lectura_error, texto(`configuracion.errores.${datos.error}`));
        return;
      }
      if (!construido) {
        construir(datos);
        construido = true;
      }
      reflejar(datos);
    },
  };
}
