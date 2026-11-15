// Copiar el nombre de un sistema para pegarlo en el mapa de la galaxia (SPEC.md §9.4).
import { texto } from './i18n.js';

const TIEMPO_COPIADO = 1500;
const temporizadores = new WeakMap();

/** `fuente` es el elemento con el nombre: sin permiso del portapapeles se deja seleccionado. */
export async function copiar(boton, nombre, fuente) {
  try {
    await navigator.clipboard.writeText(nombre);
  } catch {
    window.getSelection().selectAllChildren(fuente);
    return;
  }
  boton.textContent = texto('estado.ubicacion.copiado');
  clearTimeout(temporizadores.get(boton));
  temporizadores.set(
    boton,
    setTimeout(() => {
      boton.textContent = texto('estado.ubicacion.copiar');
    }, TIEMPO_COPIADO),
  );
}
