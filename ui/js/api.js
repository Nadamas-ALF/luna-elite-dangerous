// Puente con Python (las funciones que expone pywebview). La API solo existe cuando se
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
export const buscarRutas = (modo, perfil, paradas = null) =>
  llamar('buscar_rutas', modo, perfil, paradas);
export const explicarBusqueda = (perfil) => llamar('explicar_busqueda', perfil);
export const buscarEstaciones = (texto) => llamar('buscar_estaciones', texto);
export const ahora = (perfil) => llamar('ahora', perfil);
export const ajustesDeBusqueda = () => llamar('ajustes_de_busqueda');
export const guardarAjustesDeBusqueda = (tope, tipos, limite) =>
  llamar('guardar_ajustes_de_busqueda', tope, tipos, limite);
export const rendimiento = (sesion) => llamar('rendimiento', sesion);
export const ajustesDeSesiones = () => llamar('ajustes_de_sesiones');
export const guardarAjustesDeSesiones = (horas, porPartida) =>
  llamar('guardar_ajustes_de_sesiones', horas, porPartida);
export const guardarOmitirSesionesVacias = (omitir) =>
  llamar('guardar_omitir_sesiones_vacias', omitir);
export const importarHistorial = () => llamar('importar_historial');
export const estadoDeLaImportacion = () => llamar('estado_de_la_importacion');
export const cancelarImportacion = () => llamar('cancelar_importacion');
export const reglasDeAlertas = () => llamar('reglas_de_alertas');
export const guardarReglasDeAlertas = (reglas) => llamar('guardar_reglas_de_alertas', reglas);
export const avisos = (desdeId) => llamar('avisos', desdeId);
export const ajustesDeSonido = () => llamar('ajustes_de_sonido');
export const guardarAjustesDeSonido = (activado, volumen) =>
  llamar('guardar_ajustes_de_sonido', activado, volumen);
export const probarSonido = (volumen) => llamar('probar_sonido', volumen);
export const rutasFijadas = () => llamar('rutas_fijadas');
export const estimarRuta = (ruta) => llamar('estimar_ruta', ruta);
export const fijarRuta = (ruta) => llamar('fijar_ruta', ruta);
export const desfijarRuta = (id) => llamar('desfijar_ruta', id);
export const ajustesDeRutaEnCurso = () => llamar('ajustes_de_ruta_en_curso');
export const guardarAjustesDeRutaEnCurso = (aviso, margen, portapapeles) =>
  llamar('guardar_ajustes_de_ruta_en_curso', aviso, margen, portapapeles);
export const ajustesDeVentana = () => llamar('ajustes_de_ventana');
export const guardarSiempreEncima = (activado) => llamar('guardar_siempre_encima', activado);
export const guardarLateralPlegado = (plegado) => llamar('guardar_lateral_plegado', plegado);
export const guardarSeccionesAbiertas = (secciones) =>
  llamar('guardar_secciones_abiertas', secciones);
export const borrarDatosDeMercado = () => llamar('borrar_datos_de_mercado');
export const espacioEnDisco = () => llamar('espacio_en_disco');
export const bienvenida = () => llamar('bienvenida');
export const terminarBienvenida = () => llamar('terminar_bienvenida');
export const ajustesDeAspecto = () => llamar('ajustes_de_aspecto');
export const guardarTamanoDeLetra = (tamano) => llamar('guardar_tamano_de_letra', tamano);
export const guardarDensidad = (densidad) => llamar('guardar_densidad', densidad);
export const guardarTema = (tema) => llamar('guardar_tema', tema);
export const guardarVidrio = (vidrio) => llamar('guardar_vidrio', vidrio);
export const guardarFilasPorPagina = (filas) => llamar('guardar_filas_por_pagina', filas);
export const guardarColumnas = (modo, columnas) => llamar('guardar_columnas', modo, columnas);
