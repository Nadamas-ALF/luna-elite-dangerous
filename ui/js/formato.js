// Formato de cifras en español. Las unidades y la frase de «hace N» salen de
// es.json; aquí solo se decide cuántos decimales y cuándo cambia la unidad.
import { texto } from './i18n.js';

const LOCALE = 'es-ES';

function numero(valor, decimales) {
  return new Intl.NumberFormat(LOCALE, {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
    useGrouping: 'always',
  }).format(valor);
}

export const decimales = (valor, cifras) => numero(valor, cifras);
export const creditos = (valor) => texto('formato.creditos', { valor: numero(valor, 0) });
export const toneladas = (valor) => texto('formato.toneladas', { valor: numero(valor, 0) });
export const toneladasConDecimales = (valor) =>
  texto('formato.toneladas', { valor: numero(valor, 1) });
export const anosLuz = (valor) => texto('formato.ly', { valor: numero(valor, 2) });
export const proporcion = (parte, total) => texto('formato.proporcion', { parte, total });

const BYTES_POR_MIB = 1024 * 1024;
const BYTES_POR_GIB = 1024 * BYTES_POR_MIB;

export function bytes(valor) {
  if (valor >= BYTES_POR_GIB) return texto('formato.gib', { valor: numero(valor / BYTES_POR_GIB, 2) });
  if (valor >= BYTES_POR_MIB) return texto('formato.mib', { valor: numero(valor / BYTES_POR_MIB, 1) });
  return texto('formato.kib', { valor: numero(valor / 1024, 1) });
}

export const porcentaje = (parte, total) =>
  texto('formato.porcentaje', { valor: numero((100 * parte) / total, 0) });

/** «+12 %» o «−8 %»: una desviación, con su signo siempre. */
export function porcentajeConSigno(fraccion) {
  const valor = new Intl.NumberFormat(LOCALE, {
    maximumFractionDigits: 0,
    signDisplay: 'always',
  }).format(100 * fraccion);
  return texto('formato.porcentaje', { valor });
}

/** Sin decimales si el número es entero: «100», pero «37,5». */
export const cantidad = (valor) => numero(valor, Number.isInteger(valor) ? 0 : 1);

export function coordenadas([x, y, z]) {
  return texto('formato.coordenadas', { x: numero(x, 2), y: numero(y, 2), z: numero(z, 2) });
}

/** «hace 4 s», «hace 3 min»… desde una marca ISO del journal (UTC). */
export function hace(marcaIso, ahora = Date.now()) {
  const instante = Date.parse(marcaIso);
  if (Number.isNaN(instante)) return texto('formato.sin_dato');
  const segundos = Math.max(0, Math.round((ahora - instante) / 1000));
  if (segundos < 60) return texto('formato.hace_segundos', { n: segundos });
  const minutos = Math.floor(segundos / 60);
  if (minutos < 60) return texto('formato.hace_minutos', { n: minutos });
  const horas = Math.floor(minutos / 60);
  if (horas < 48) return texto('formato.hace_horas', { n: horas });
  return texto('formato.hace_dias', { n: Math.floor(horas / 24) });
}

export const creditosPorTonelada = (valor) => texto('formato.cr_t', { valor: numero(valor, 0) });

/** Una ganancia siempre con su signo («+216.000 Cr»): el color nunca es la única señal. */
function conSigno(valor) {
  return new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0, signDisplay: 'exceptZero', useGrouping: 'always' }).format(valor);
}

export const gananciaEnCreditos = (valor) => texto('formato.creditos', { valor: conSigno(valor) });
export const gananciaPorTonelada = (valor) => texto('formato.cr_t', { valor: conSigno(valor) });
export const creditosPorHora = (valor) => texto('formato.cr_h', { valor: numero(valor, 0) });
export const segundosLuz = (valor) => texto('formato.ls', { valor: numero(valor, 0) });

/** «45 s», «12 min», «1 h 5 min». */
export function duracion(segundos) {
  if (segundos < 60) return texto('formato.segundos', { n: Math.round(segundos) });
  const minutos = Math.round(segundos / 60);
  if (minutos < 60) return texto('formato.minutos', { n: minutos });
  return texto('formato.horas_minutos', { h: Math.floor(minutos / 60), m: minutos % 60 });
}

/** «14:05»: la hora local, para decir cuándo se calculó algo. */
export const hora = (fecha) =>
  new Intl.DateTimeFormat(LOCALE, { hour: '2-digit', minute: '2-digit' }).format(fecha);

/** «15 nov, 07:53»: una marca ISO del journal en la hora local. */
export function fechaHora(marcaIso) {
  const instante = Date.parse(marcaIso);
  if (Number.isNaN(instante)) return texto('formato.sin_dato');
  return new Intl.DateTimeFormat(LOCALE, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(instante);
}
