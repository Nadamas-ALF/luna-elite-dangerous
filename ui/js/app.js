// Los textos viven solo en i18n/es.json. WebView2 permite importarlo como
// módulo JSON incluso desde file:// (docs/verificaciones.md, verificación 3).
import textos from '../i18n/es.json' with { type: 'json' };

/** Devuelve el texto de una clave con puntos, o null si no existe. */
function texto(clave) {
  return clave.split('.').reduce((nodo, parte) => (nodo == null ? null : nodo[parte]), textos);
}

function aplicarTextos(raiz) {
  const faltantes = [];
  for (const elemento of raiz.querySelectorAll('[data-texto]')) {
    const clave = elemento.dataset.texto;
    const valor = texto(clave);
    if (typeof valor === 'string') {
      // textContent y nunca innerHTML: WebView2 corre con
      // --allow-file-access-from-files, así que inyectar HTML ajeno daría
      // acceso de lectura a archivos locales.
      elemento.textContent = valor;
    } else {
      faltantes.push(clave);
    }
  }
  return faltantes;
}

function mostrarMedidas() {
  const ventana = document.getElementById('medida-ventana');
  const escala = document.getElementById('medida-escala');
  ventana.textContent = `${window.innerWidth} x ${window.innerHeight}`;
  escala.textContent = `${Math.round(window.devicePixelRatio * 100)} %`;
}

// El título de la ventana nativa lo pone Python desde es.json; cambiar
// document.title no llega a la barra de título.
const faltantes = aplicarTextos(document);
mostrarMedidas();
window.addEventListener('resize', mostrarMedidas);

// Lo lee main.py al verificar la fase 0; no afecta al funcionamiento normal.
window.__luna = { textosFaltantes: faltantes, modulosEs: true };
