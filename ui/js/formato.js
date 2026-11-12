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
