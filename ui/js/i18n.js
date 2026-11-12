// Los textos viven solo en i18n/es.json. WebView2 permite importarlo como
// módulo JSON incluso desde file:// (docs/verificaciones.md, verificación 3).
import textos from '../i18n/es.json' with { type: 'json' };

// Atributos que el HTML puede traducir con data-i18n-<nombre>. Lista cerrada:
// el nombre del atributo nunca se lee del HTML (DESIGN.md §6).
const ATRIBUTOS = new Set(['placeholder', 'aria-label', 'title']);
const PREFIJO = 'data-i18n-';

const faltantes = new Set();

function buscar(clave) {
  return clave.split('.').reduce((nodo, parte) => (nodo == null ? null : nodo[parte]), textos);
}

/**
 * Texto de una clave con puntos. Los marcadores {nombre} se sustituyen por los
 * valores dados; el resultado se escribe siempre con textContent o setAttribute,
 * nunca como HTML. Una clave ausente se anota y devuelve cadena vacía.
 */
export function texto(clave, valores = {}) {
  const plantilla = buscar(clave);
  if (typeof plantilla !== 'string') {
    faltantes.add(clave);
    console.warn(`Falta el texto "${clave}" en es.json`);
    return '';
  }
  return plantilla.replace(/\{(\w+)\}/g, (marcador, nombre) =>
    nombre in valores ? String(valores[nombre]) : marcador,
  );
}

export function textosFaltantes() {
  return [...faltantes];
}

function claveDeAtributo(nombre) {
  return nombre.startsWith(PREFIJO) ? nombre.slice(PREFIJO.length) : null;
}

export function aplicarTextos(raiz) {
  for (const elemento of raiz.querySelectorAll('[data-i18n]')) {
    elemento.textContent = texto(elemento.dataset.i18n);
  }
  for (const elemento of raiz.querySelectorAll('*')) {
    for (const atributo of elemento.attributes) {
      const destino = claveDeAtributo(atributo.name);
      if (destino && ATRIBUTOS.has(destino)) {
        elemento.setAttribute(destino, texto(atributo.value));
      }
    }
  }
}
