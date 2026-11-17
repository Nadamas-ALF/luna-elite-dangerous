// Tabla de resultados que comparten Rutas, Ahora, Alertas y Rendimiento. Cada columna es
// [nombre, prioridad, valor, clave]; el rótulo sale de `${claves}.${nombre}`. `clave` es lo que
// se compara al ordenar por esa cabecera (un número, un texto o null); sin ella la columna no
// se puede ordenar.
import { crear } from './celdas.js';
import { texto } from './i18n.js';

// Las esenciales van primero, para que se vean aunque la tabla tenga que desplazarse,
// y las secundarias son las primeras en ocultarse al estrechar (§9.3).
export const ESENCIAL = 'esencial';
export const SECUNDARIA = 'secundaria';

// Columnas de texto; las demás llevan cifras, a la derecha y con números tabulares.
const DE_TEXTO = new Set([
  'mercancia', 'comprar', 'vender', 'ida', 'vuelta', 'estacion_a', 'estacion_b', 'origen',
  'ruta', 'mercancias', 'sesion', 'estado_sesion', 'cuando', 'modo', 'estado_ruta',
]);

// Al ordenar por primera vez, lo mejor va arriba: los textos de la A a la Z, lo que conviene que
// sea pequeño de menor a mayor y el resto (ganancias, toneladas, precios de venta) de mayor a menor.
const MEJOR_PEQUENO = new Set([
  'antiguedad', 'tiempo', 'saltos', 'distancia_ly', 'distancia_ls', 'precio_compra',
]);

const OPCIONES_DE_FILAS_DE_FABRICA = [10];

function clasesDe(nombre, prioridad) {
  return [DE_TEXTO.has(nombre) ? null : 'cifra', prioridad && `col--${prioridad}`]
    .filter(Boolean)
    .join(' ');
}

// Lo más reciente es lo que se quiere ver arriba, aunque la columna se alinee como texto.
const MEJOR_RECIENTE = new Set(['sesion']);

const ordenaPrimeroAscendente = (nombre) =>
  !MEJOR_RECIENTE.has(nombre) && (DE_TEXTO.has(nombre) || MEJOR_PEQUENO.has(nombre));

/** Los datos sin clave (null) quedan siempre al final, sea cual sea el sentido. */
function comparar(a, b, sentido) {
  if (a === null || a === undefined) return b === null || b === undefined ? 0 : 1;
  if (b === null || b === undefined) return -1;
  const orden =
    typeof a === 'number' && typeof b === 'number'
      ? a - b
      : String(a).localeCompare(String(b), 'es', { numeric: true, sensitivity: 'base' });
  return orden * sentido;
}

function ordenados(estado) {
  const { orden, datos, columnas } = estado;
  const columna = orden && columnas.find(([nombre]) => nombre === orden.nombre);
  if (!columna) return datos;
  const clave = columna[3];
  // La clave de algunas columnas recorre listas: se calcula una vez por fila, no por comparación.
  return datos
    .map((dato) => ({ dato, clave: clave(dato) }))
    .sort((a, b) => comparar(a.clave, b.clave, orden.sentido))
    .map(({ dato }) => dato);
}


function cabecera(estado) {
  const { columnas, claves, orden } = estado;
  const fila = crear('tr');
  for (const [nombre, prioridad, , clave] of columnas) {
    const celda = crear('th', clasesDe(nombre, prioridad));
    celda.scope = 'col';
    const rotulo = texto(`${claves}.${nombre}`);
    celda.title = texto(`comercio.columnas_ayuda.${nombre}`);
    if (clave) {
      const boton = crear('button', 'orden', rotulo);
      boton.type = 'button';
      boton.dataset.columna = nombre;
      boton.addEventListener('click', () => ordenarPor(estado, nombre));
      celda.append(boton);
      if (orden?.nombre === nombre) {
        celda.setAttribute('aria-sort', orden.sentido === 1 ? 'ascending' : 'descending');
      }
    } else {
      celda.textContent = rotulo;
    }
    fila.append(celda);
  }
  return fila;
}

function ordenarPor(estado, nombre) {
  const { orden } = estado;
  if (orden?.nombre === nombre) estado.orden = { nombre, sentido: -orden.sentido };
  else estado.orden = { nombre, sentido: ordenaPrimeroAscendente(nombre) ? 1 : -1 };
  estado.pagina = 0;
  dibujar(estado);
  // La cabecera se rehace entera: sin esto, quien ordena con el teclado perdería el foco.
  estado.tabla.tHead.querySelector(`button[data-columna="${nombre}"]`)?.focus();
}


function filaDe(columnas, dato) {
  const fila = crear('tr');
  for (const [nombre, prioridad, valor] of columnas) {
    const celda = crear('td', clasesDe(nombre, prioridad));
    const contenido = valor(dato);
    if (typeof contenido === 'string') celda.textContent = contenido;
    else celda.append(contenido);
    fila.append(celda);
  }
  return fila;
}

// La fila elegida sobrevive a ordenar y paginar: se vuelve a marcar si sigue en la página.
let elegida = null;

// `aria-selected` solo vale en filas de una rejilla (`grid`); en una tabla normal la
// fila elegida se anuncia con `aria-current`.
function seleccionable(fila, cuerpo, estado, dato, alElegir) {
  fila.classList.add('resultado');
  fila.tabIndex = 0;
  const elegir = () => {
    // Una pantalla puede tener varias tablas (Ahora) y un solo detalle: elegida, solo una fila.
    const pantalla = fila.closest('.vista') ?? cuerpo;
    for (const otra of pantalla.querySelectorAll('tr[aria-current]')) otra.removeAttribute('aria-current');
    fila.setAttribute('aria-current', 'true');
    elegida = { estado, dato };
    alElegir();
  };
  fila.addEventListener('click', elegir);
  fila.addEventListener('keydown', (evento) => {
    // Un botón dentro de la fila (copiar un sistema) usa su propio Enter y espacio.
    if (evento.target !== fila || (evento.key !== 'Enter' && evento.key !== ' ')) return;
    evento.preventDefault();
    elegir();
  });
}

// Python devuelve hasta 50 resultados; aquí solo se reparten en páginas. El tamaño de página es
// el mismo para todas las tablas y se recuerda en config.json (lo guarda quien llama a `configurar`).

let filasPorPagina = OPCIONES_DE_FILAS_DE_FABRICA[0];
let opcionesDeFilas = OPCIONES_DE_FILAS_DE_FABRICA;
let alCambiarFilas = () => {};
let siguienteSelector = 0;
// Referencias débiles: Ahora rehace sus tablas en cada recálculo y no deben quedarse retenidas.
const vivas = new Set();

function repintarTodas() {
  for (const referencia of vivas) {
    const estado = referencia.deref();
    if (estado) dibujar(estado);
    else vivas.delete(referencia);
  }
}

/** Fija las opciones del selector y el tamaño de página; `alCambiar(filas)` guarda la elección. */
export function configurarPaginacion({ filas, opciones, alCambiar }) {
  filasPorPagina = filas;
  opcionesDeFilas = opciones;
  alCambiarFilas = alCambiar;
  repintarTodas();
}

const paginasDe = (total) => Math.max(1, Math.ceil(total / filasPorPagina));

function controlesDe(estado) {
  const barra = crear('div', 'paginacion');
  const resumen = crear('p', 'paginacion__resumen');
  resumen.setAttribute('role', 'status');
  const selector = crear('select', 'entrada entrada--corta');
  selector.id = `filas-por-pagina-${siguienteSelector++}`;
  const etiqueta = crear('label', 'paginacion__filas', texto('comercio.paginacion.filas'));
  etiqueta.htmlFor = selector.id;
  const anterior = crear('button', 'boton boton--vidrio boton--pequeno', texto('comercio.paginacion.anterior'));
  const siguiente = crear('button', 'boton boton--vidrio boton--pequeno', texto('comercio.paginacion.siguiente'));
  anterior.type = 'button';
  siguiente.type = 'button';
  anterior.addEventListener('click', () => irA(estado, estado.pagina - 1));
  siguiente.addEventListener('click', () => irA(estado, estado.pagina + 1));
  selector.addEventListener('change', () => {
    filasPorPagina = Number(selector.value);
    repintarTodas();
    alCambiarFilas(filasPorPagina);
  });
  barra.append(resumen, etiqueta, selector, anterior, siguiente);
  return { barra, resumen, selector, anterior, siguiente };
}

function irA(estado, pagina) {
  const { anterior, siguiente } = estado.controles;
  const pulsado = pagina > estado.pagina ? siguiente : anterior;
  estado.pagina = pagina;
  dibujar(estado);
  // El botón que acaba de agotar su sentido se desactiva: el foco pasa al otro.
  if (pulsado.disabled) (pulsado === siguiente ? anterior : siguiente).focus();
}

function pintarControles(estado, total) {
  const { controles } = estado;
  // Con menos filas que la página más corta no hay nada que paginar.
  controles.barra.hidden = total <= Math.min(...opcionesDeFilas);
  if (controles.barra.hidden) return;
  const paginas = paginasDe(total);
  const desde = estado.pagina * filasPorPagina + 1;
  const hasta = Math.min(total, desde + filasPorPagina - 1);
  controles.resumen.textContent = texto('comercio.paginacion.resumen', { desde, hasta, total });
  controles.selector.replaceChildren(
    ...opcionesDeFilas.map((n) => {
      const opcion = crear('option', null, String(n));
      opcion.value = String(n);
      return opcion;
    }),
  );
  controles.selector.value = String(filasPorPagina);
  controles.anterior.disabled = estado.pagina === 0;
  controles.siguiente.disabled = estado.pagina >= paginas - 1;
}


// Una tabla que cabe se recorta (así su cabecera se queda fija al desplazar la pantalla); una
// que no cabe vuelve a desplazarse en horizontal para no perder columnas a la vista, y entonces
// su cabecera ya no se queda fija (E-21).
const vigiladas = new WeakSet();
// El cambio de clase añade o quita una barra horizontal, que cambia el alto del contenedor
// observado: hecho dentro del aviso daría el error «ResizeObserver loop», así que va al cuadro
// siguiente.
const desborde = new ResizeObserver((entradas) => {
  const contenedores = new Set(entradas.map(({ target }) => target.closest('.tabla-contenedor')));
  requestAnimationFrame(() => {
    for (const contenedor of contenedores) {
      // Ahora rehace sus tablas en cada recálculo: el observador retendría las viejas.
      if (!contenedor.isConnected) {
        desborde.unobserve(contenedor);
        for (const tabla of contenedor.querySelectorAll('table')) desborde.unobserve(tabla);
        continue;
      }
      const excede = contenedor.scrollWidth > contenedor.clientWidth + 1;
      contenedor.classList.toggle('tabla-contenedor--desborda', excede);
    }
  });
});

function vigilarDesborde(tabla) {
  const contenedor = tabla.closest('.tabla-contenedor');
  if (!contenedor || vigiladas.has(contenedor)) return;
  vigiladas.add(contenedor);
  desborde.observe(contenedor);
  desborde.observe(tabla);
}


const estados = new WeakMap();

function dibujar(estado) {
  const { tabla, columnas, alElegir } = estado;
  const filas = ordenados(estado);
  estado.pagina = Math.min(estado.pagina, paginasDe(filas.length) - 1);
  const desde = estado.pagina * filasPorPagina;
  tabla.tHead.replaceChildren(cabecera(estado));
  const cuerpo = tabla.tBodies[0];
  cuerpo.replaceChildren(
    ...filas.slice(desde, desde + filasPorPagina).map((dato) => {
      const fila = filaDe(columnas, dato);
      if (alElegir) {
        seleccionable(fila, cuerpo, estado, dato, () => alElegir(dato));
        if (elegida?.estado === estado && elegida.dato === dato) fila.setAttribute('aria-current', 'true');
      }
      return fila;
    }),
  );
  pintarControles(estado, filas.length);
}

function estadoDe(tabla) {
  let estado = estados.get(tabla);
  if (!estado) {
    estado = { tabla, orden: null, pagina: 0 };
    estado.controles = controlesDe(estado);
    tabla.closest('.tabla-contenedor').append(estado.controles.barra);
    estados.set(tabla, estado);
    for (const referencia of vivas) if (!referencia.deref()) vivas.delete(referencia);
    vivas.add(new WeakRef(estado));
  }
  return estado;
}

/**
 * Rellena `tabla` (con su thead y tbody). Con `alElegir`, las filas se pueden seleccionar.
 * Datos nuevos vuelven a la primera página; el orden elegido se conserva si su columna sigue.
 */
export function pintarTabla(tabla, columnas, datos, claves, alElegir) {
  vigilarDesborde(tabla);
  const estado = estadoDe(tabla);
  const mismosDatos = estado.datos === datos;
  // Se conserva el orden mientras su columna siga a la vista; la página, si los datos son los mismos.
  const sigue = estado.orden && columnas.some(([nombre]) => nombre === estado.orden.nombre);
  Object.assign(estado, {
    columnas,
    datos,
    claves,
    alElegir,
    orden: sigue ? estado.orden : null,
    pagina: mismosDatos ? estado.pagina : 0,
  });
  dibujar(estado);
}

/** Una tabla nueva dentro de su contenedor, que se desplaza en horizontal si no cabe. */
export function crearTabla(titulo) {
  const contenedor = crear('div', 'tabla-contenedor');
  const tabla = crear('table', 'tabla');
  tabla.append(crear('caption', 'solo-lectores', titulo), crear('thead'), crear('tbody'));
  contenedor.append(tabla);
  return { contenedor, tabla };
}
