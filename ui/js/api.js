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

async function llamar(nombre, ...argumentos) {
  const api = await esperarPuente();
  return api[nombre](...argumentos);
}

export const estado = () => llamar('estado');
export const configuracion = () => llamar('configuracion');
export const elegirCarpetaJournal = () => llamar('elegir_carpeta_journal');
export const usarCarpetaAutomatica = () => llamar('usar_carpeta_automatica');
export const spansh = () => llamar('spansh');
export const proponerEsfera = (nombre, radio) => llamar('proponer_esfera', nombre, radio);
export const aplicarEsfera = (nombre, radio, descargar) =>
  llamar('aplicar_esfera', nombre, radio, descargar);
export const guardarRetencion = (visitados, antiguedad) =>
  llamar('guardar_retencion', visitados, antiguedad);
export const establecerEddn = (activado) => llamar('establecer_eddn', activado);
export const reanudarDescarga = () => llamar('reanudar_descarga');
export const pausarDescarga = () => llamar('pausar_descarga');
export const cancelarDescarga = () => llamar('cancelar_descarga');
export const perfilInicial = () => llamar('perfil_inicial');
export const perfilesGuardados = () => llamar('perfiles_guardados');
export const guardarPerfil = (nombre, perfil) => llamar('guardar_perfil', nombre, perfil);
export const borrarPerfil = (nombre) => llamar('borrar_perfil', nombre);
export const buscarRutas = (modo, perfil) => llamar('buscar_rutas', modo, perfil);
export const ahora = (perfil) => llamar('ahora', perfil);
export const ajustesDeBusqueda = () => llamar('ajustes_de_busqueda');
export const guardarAjustesDeBusqueda = (tope, tipos) =>
  llamar('guardar_ajustes_de_busqueda', tope, tipos);
