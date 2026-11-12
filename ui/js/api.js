// Puente con Python (js_api de pywebview). La API solo existe cuando se
// dispara pywebviewready; llamarla antes lanza (SPEC.md §10.2).

let listo = null;

export function esperarPuente() {
  if (listo) return listo;
  listo = new Promise((resolver) => {
    if (window.pywebview && window.pywebview.api) {
      resolver(window.pywebview.api);
    } else {
      window.addEventListener('pywebviewready', () => resolver(window.pywebview.api), {
        once: true,
      });
    }
  });
  return listo;
}

async function llamar(nombre) {
  const api = await esperarPuente();
  return api[nombre]();
}

export const estado = () => llamar('estado');
export const configuracion = () => llamar('configuracion');
export const elegirCarpetaJournal = () => llamar('elegir_carpeta_journal');
export const usarCarpetaAutomatica = () => llamar('usar_carpeta_automatica');
