// Perfil de búsqueda (SPEC.md §7.1). La interfaz no valida rangos: manda lo que
// hay en el formulario y, si Python rechaza un campo, lo señala aquí.
// Un campo de los que salen de la nave va marcado «De tu nave» mientras su valor
// sea el detectado; si el usuario lo cambia pasa a «Manual».
import * as api from './api.js';
import { activarMiles, escribirMiles, leerMiles } from './campo-numerico.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';

const NUMEROS = ['capacidad', 'rango', 'distancia_max_ly', 'distancia_max_ls', 'horas_sesion'];
// Cifras grandes: se escriben con separador de miles (campo-numerico.js).
const MILES = ['stock_minimo', 'ganancia_min'];
const CASILLAS = ['raras', 'limitar_saldo'];
// Paradas del deslizador de antigüedad, en horas; el tope de Configuración las recorta.
const PARADAS_DE_ANTIGUEDAD = [1, 2, 4, 8, 12, 24, 48, 72, 120, 168, 240, 336, 504, 720];
let paradas = PARADAS_DE_ANTIGUEDAD.slice(0, 10);
const TEXTOS = ['plataforma', 'origen', 'orden'];
// Campos que al cargar un perfil se llevan al valor admitido más cercano.
const AJUSTABLES = ['antiguedad_max_h', 'horas_sesion'];
const SELECCIONES = ['tipos', 'origenes'];
// SPEC.md §9.3: por debajo de 1000 px el perfil se pliega encima de los resultados.
const ANCHO_PLEGADO = '(max-width: 999.98px)';

function campos(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  return c;
}

function mostrarTexto(elemento, mensaje) {
  elemento.hidden = !mensaje;
  elemento.textContent = mensaje ?? '';
}

function leerNumero(entrada) {
  return entrada.value.trim() === '' || Number.isNaN(entrada.valueAsNumber)
    ? null
    : entrada.valueAsNumber;
}

function marcadas(formulario, nombre) {
  return [...formulario.querySelectorAll(`input[name="${nombre}"]`)]
    .filter((casilla) => casilla.checked)
    .map((casilla) => casilla.value);
}

/** Las paradas hasta el tope, con el tope como última si no coincide con ninguna. */
export function paradasHasta(topeHoras) {
  const hasta = PARADAS_DE_ANTIGUEDAD.filter((horas) => horas <= topeHoras);
  if (hasta.length === 0 || hasta[hasta.length - 1] !== topeHoras) hasta.push(topeHoras);
  return hasta;
}

const paradaMasCercana = (horas) =>
  paradas.reduce(
    (mejor, parada, i) => (Math.abs(parada - horas) < Math.abs(paradas[mejor] - horas) ? i : mejor),
    0,
  );

function textoDeAntiguedad(horas) {
  return horas >= 48 && horas % 24 === 0
    ? texto('comercio.perfil.antiguedad_valor_dias', { n: horas / 24 })
    : texto('comercio.perfil.antiguedad_valor_horas', { n: horas });
}

export function leerPerfil(formulario) {
  const e = formulario.elements;
  const perfil = {};
  for (const nombre of NUMEROS) perfil[nombre] = leerNumero(e[nombre]);
  for (const nombre of MILES) perfil[nombre] = leerMiles(e[nombre]);
  perfil.antiguedad_max_h = paradas[Number(e.antiguedad_max_h.value)] ?? null;
  for (const nombre of TEXTOS) perfil[nombre] = e[nombre].value.trim();
  for (const nombre of SELECCIONES) perfil[nombre] = marcadas(formulario, nombre);
  for (const nombre of CASILLAS) perfil[nombre] = e[nombre].checked;
  return perfil;
}

function escribirCampo(formulario, nombre, valor) {
  if (SELECCIONES.includes(nombre)) {
    for (const casilla of formulario.querySelectorAll(`input[name="${nombre}"]`)) {
      casilla.checked = valor.includes(casilla.value);
    }
  } else if (CASILLAS.includes(nombre)) {
    formulario.elements[nombre].checked = valor;
  } else if (MILES.includes(nombre)) {
    escribirMiles(formulario.elements[nombre], valor);
  } else if (nombre === 'antiguedad_max_h') {
    formulario.elements[nombre].value = String(paradaMasCercana(valor));
  } else if (nombre === 'horas_sesion') {
    formulario.elements[nombre].value = String(Math.min(12, Math.max(1, Math.round(valor))));
  } else {
    formulario.elements[nombre].value = valor === null ? '' : String(valor);
  }
}

export function crearPanelPerfil(raiz) {
  const c = campos(raiz);
  const formulario = raiz.querySelector('[data-panel="perfil"]');
  const guardados = raiz.querySelector('[data-panel="guardados"]');
  // Lo que se detectó de la nave la última vez; solo lo que se pudo detectar.
  let deLaNave = {};
  let tiposDeConfig = [];
  let lista = [];
  let ultimoSaldo = null;

  const iguales = (nombre) => leerPerfil(formulario)[nombre] === deLaNave[nombre];

  function pintarMarcas() {
    for (const marca of formulario.querySelectorAll('[data-marca]')) {
      const nombre = marca.dataset.marca;
      marca.hidden = !(nombre in deLaNave);
      const automatico = !marca.hidden && iguales(nombre);
      marca.textContent = texto(automatico ? 'comercio.perfil.de_la_nave' : 'comercio.perfil.manual');
      marca.classList.toggle('marca--manual', !automatico);
    }
  }

  function pintarValores(saldo) {
    const e = formulario.elements;
    c.perfil_antiguedad_valor.textContent = textoDeAntiguedad(paradas[Number(e.antiguedad_max_h.value)]);
    c.perfil_horas_valor.textContent = texto('comercio.perfil.horas_valor', { n: e.horas_sesion.value });
    const { stock_minimo: stock, capacidad } = leerPerfil(formulario);
    const equivale = stock !== null && capacidad ? Math.floor(stock / capacidad) : null;
    c.perfil_stock_equivale.hidden = equivale === null;
    c.perfil_stock_equivale.textContent =
      equivale === null
        ? ''
        : texto(equivale === 1 ? 'comercio.perfil.stock_equivale_una' : 'comercio.perfil.stock_equivale', {
            n: formato.cantidad(equivale),
          });
    if (saldo !== undefined) ultimoSaldo = saldo;
    c.perfil_saldo.textContent =
      ultimoSaldo === null
        ? texto('comercio.perfil.saldo_desconocido')
        : texto('comercio.perfil.saldo', { valor: formato.creditos(ultimoSaldo) });
  }

  function limpiarError() {
    mostrarTexto(c.perfil_error, null);
    for (const invalido of formulario.querySelectorAll('[aria-invalid]')) {
      invalido.removeAttribute('aria-invalid');
    }
  }

  function escribir(perfil) {
    for (const [nombre, valor] of Object.entries(perfil)) escribirCampo(formulario, nombre, valor);
    limpiarError();
    pintarMarcas();
    pintarValores();
  }

  const detectados = (inicial) =>
    Object.fromEntries(inicial.automaticos.map((nombre) => [nombre, inicial.perfil[nombre]]));

  /** Los campos que siguen siendo de la nave toman el valor nuevo; los manuales se quedan. */
  function seguirALaNave(inicial) {
    const nuevos = detectados(inicial);
    for (const [nombre, valor] of Object.entries(nuevos)) {
      if (!(nombre in deLaNave) || iguales(nombre)) escribirCampo(formulario, nombre, valor);
    }
    deLaNave = nuevos;
  }

  /** Los tipos siguen a Configuración mientras no los cambies aquí, como los de la nave. */
  function seguirALaConfiguracion(tipos) {
    const actuales = marcadas(formulario, 'tipos');
    const sinTocar =
      actuales.length === tiposDeConfig.length && actuales.every((t) => tiposDeConfig.includes(t));
    if (sinTocar) escribirCampo(formulario, 'tipos', tipos);
    tiposDeConfig = tipos;
  }

  function pintarLimites(limites) {
    const horas = limites.antiguedad_max_h;
    const antiguedad = formulario.elements.antiguedad_max_h;
    const pedida = leerPerfil(formulario).antiguedad_max_h;
    paradas = paradasHasta(horas);
    antiguedad.max = String(paradas.length - 1);
    // Bajar el tope en Configuración recorta lo pedido, igual que a un perfil guardado.
    antiguedad.value = String(paradaMasCercana(Math.min(pedida ?? horas, horas)));
  }

  function pintarGuardados() {
    const opciones = lista.map(({ nombre }) => {
      const opcion = document.createElement('option');
      opcion.value = nombre;
      opcion.textContent = nombre;
      return opcion;
    });
    const elegido = c.guardados_lista.value;
    c.guardados_lista.replaceChildren(...opciones);
    if (lista.some(({ nombre }) => nombre === elegido)) c.guardados_lista.value = elegido;
    c.guardados_ninguno.hidden = lista.length > 0;
    c.guardados_eleccion.hidden = lista.length === 0;
  }

  const mensajeDeError = (codigo) => texto(`comercio.perfil.errores.${codigo}`);

  async function refrescarGuardados() {
    const respuesta = await api.perfilesGuardados();
    if (respuesta.error) {
      mostrarTexto(c.guardados_error, mensajeDeError(respuesta.error));
      return;
    }
    lista = respuesta.perfiles;
    pintarGuardados();
  }

  function resultadoDeGuardados(mensaje) {
    mostrarTexto(c.guardados_error, null);
    mostrarTexto(c.guardados_resultado, mensaje);
  }

  /** Pinta la respuesta de Python a un perfil: `{error: 'perfil', campo}` señala el campo. */
  function rechazar(respuesta) {
    if (respuesta.error !== 'perfil' || respuesta.campo === 'nombre') return false;
    const nombre = respuesta.campo;
    const entrada = formulario.elements[nombre];
    const elemento = entrada instanceof RadioNodeList ? entrada[0] : entrada;
    elemento?.setAttribute('aria-invalid', 'true');
    mostrarTexto(
      c.perfil_error,
      texto('comercio.perfil.campo_invalido', { campo: texto(`comercio.perfil.${nombre}`) }),
    );
    c.perfil_plegable.open = true;
    // Datos y Nave van plegados: sin abrir su grupo, el foco caería en un campo oculto.
    const grupo = elemento?.closest('details');
    if (grupo) grupo.open = true;
    elemento?.focus();
    return true;
  }

  async function guardar(evento) {
    evento.preventDefault();
    limpiarError();
    const nombre = c.guardados_nombre.value.trim();
    const respuesta = await api.guardarPerfil(nombre, leerPerfil(formulario));
    if (rechazar(respuesta)) {
      resultadoDeGuardados(null);
      return;
    }
    if (respuesta.error) {
      const codigo = respuesta.error === 'perfil' ? 'nombre' : respuesta.error;
      mostrarTexto(c.guardados_resultado, null);
      mostrarTexto(c.guardados_error, mensajeDeError(codigo));
      return;
    }
    resultadoDeGuardados(
      respuesta.pendiente
        ? texto('comercio.perfil.guardados.pendiente')
        : texto('comercio.perfil.guardados.guardado', { nombre }),
    );
    await refrescarGuardados();
    c.guardados_lista.value = nombre;
  }

  function cargarGuardado() {
    const elegido = lista.find(({ nombre }) => nombre === c.guardados_lista.value);
    if (!elegido) return;
    escribir(elegido.perfil);
    c.guardados_nombre.value = elegido.nombre;
    resultadoDeGuardados(texto('comercio.perfil.guardados.cargado', { nombre: elegido.nombre }));
    avisarDeAjustes(elegido.perfil);
  }

  /** El deslizador de antigüedad y las horas de sesión solo admiten ciertos valores. */
  function avisarDeAjustes(pedido) {
    const leido = leerPerfil(formulario);
    const ajustados = AJUSTABLES.filter(
      (nombre) => pedido[nombre] != null && pedido[nombre] !== leido[nombre],
    );
    if (ajustados.length === 0) return;
    const nombres = ajustados.map((nombre) =>
      texto('comercio.perfil.campo_citado', { campo: texto(`comercio.perfil.${nombre}`) }),
    );
    mostrarTexto(
      c.perfil_aviso,
      texto('comercio.perfil.ajustado', { campos: new Intl.ListFormat('es').format(nombres) }),
    );
  }

  async function borrarGuardado() {
    const nombre = c.guardados_lista.value;
    if (!nombre) return;
    const respuesta = await api.borrarPerfil(nombre);
    if (respuesta.error) {
      const codigo = respuesta.error === 'perfil' ? 'nombre' : respuesta.error;
      mostrarTexto(c.guardados_error, mensajeDeError(codigo));
      return;
    }
    resultadoDeGuardados(
      respuesta.pendiente
        ? texto('comercio.perfil.guardados.pendiente')
        : texto('comercio.perfil.guardados.borrado', { nombre }),
    );
    await refrescarGuardados();
  }

  async function restaurar() {
    const inicial = await api.perfilInicial();
    if (inicial.error) return;
    deLaNave = detectados(inicial);
    for (const [nombre, valor] of Object.entries(deLaNave)) escribirCampo(formulario, nombre, valor);
    limpiarError();
    pintarMarcas();
    pintarValores();
    mostrarTexto(c.perfil_aviso, texto('comercio.perfil.restaurado'));
  }

  // A lo ancho la barra está siempre a la vista. Estrecha es un panel encima de la tabla: empieza
  // plegada y se pliega al buscar, o taparía los resultados (SPEC.md §9.3).
  function plegarSegunAncho(consulta) {
    c.perfil_plegable.open = !consulta.matches;
  }

  formulario.addEventListener('input', () => {
    limpiarError();
    mostrarTexto(c.perfil_aviso, null);
    pintarMarcas();
    pintarValores();
  });
  for (const nombre of MILES) activarMiles(formulario.elements[nombre]);
  formulario.addEventListener('submit', (evento) => evento.preventDefault());
  c.perfil_restaurar.addEventListener('click', restaurar);
  guardados.querySelector('form').addEventListener('submit', guardar);
  c.guardados_cargar.addEventListener('click', cargarGuardado);
  c.guardados_borrar.addEventListener('click', borrarGuardado);
  const plegado = window.matchMedia(ANCHO_PLEGADO);
  plegado.addEventListener('change', plegarSegunAncho);
  plegarSegunAncho(plegado);

  let cargado = false;

  return {
    /**
     * La primera vez trae el perfil entero; después sigue a la nave. Devuelve el
     * código de error si no se pudo traer, para que Ahora no busque con un formulario vacío.
     */
    async cargar() {
      const inicial = await api.perfilInicial();
      if (inicial.error) {
        mostrarTexto(c.perfil_error, mensajeDeError(inicial.error));
        return inicial.error;
      }
      pintarLimites(inicial.limites);
      if (cargado) {
        seguirALaNave(inicial);
        seguirALaConfiguracion(inicial.perfil.tipos);
      } else {
        deLaNave = detectados(inicial);
        tiposDeConfig = inicial.perfil.tipos;
        escribir(inicial.perfil);
        cargado = true;
      }
      c.perfil_sin_nave.hidden = inicial.automaticos.includes('capacidad');
      pintarMarcas();
      pintarValores(inicial.saldo);
      await refrescarGuardados();
      return null;
    },
    leer: () => leerPerfil(formulario),
    plegarSiEstrecho() {
      if (plegado.matches) c.perfil_plegable.open = false;
    },
    fijarOrigen(nombre) {
      formulario.elements.origen.value = nombre;
      formulario.dispatchEvent(new Event('input', { bubbles: true }));
    },
    rechazar,
  };
}
