// Copiar el nombre de un sistema para pegarlo en el mapa de la galaxia (SPEC.md §9.4).
import { texto } from './i18n.js';

const TIEMPO_COPIADO = 1500;
// WebView2 puede dejar `writeText` pendiente sin resolver ni fallar, por ejemplo sin el foco
// de la ventana (E-36): pasado este plazo se cae a la selección, como sin permiso.
const PLAZO_DEL_PORTAPAPELES = 1000;
const temporizadores = new WeakMap();

function escribirConPlazo(nombre) {
  let plazo;
  const vencido = new Promise((_, rechazar) => {
    plazo = setTimeout(() => rechazar(new Error('plazo')), PLAZO_DEL_PORTAPAPELES);
  });
  return Promise.race([navigator.clipboard.writeText(nombre), vencido]).finally(() =>
    clearTimeout(plazo),
  );
}

/**
 * `fuente` es el elemento con el nombre: sin permiso del portapapeles se deja seleccionado.
 * `volverA` es el texto que recupera el botón tras «Copiado» (un enlace vuelve a su nombre).
 */
export async function copiar(boton, nombre, fuente, volverA = texto('estado.ubicacion.copiar')) {
  try {
    await escribirConPlazo(nombre);
  } catch {
    window.getSelection().selectAllChildren(fuente);
    return;
  }
  boton.textContent = texto('estado.ubicacion.copiado');
  clearTimeout(temporizadores.get(boton));
  temporizadores.set(
    boton,
    setTimeout(() => {
      boton.textContent = volverA;
    }, TIEMPO_COPIADO),
  );
}
