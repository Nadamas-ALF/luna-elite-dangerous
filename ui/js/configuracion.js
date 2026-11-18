// Pantalla Configuración. La carpeta del journal se elige con el diálogo nativo
// de Windows; esta página nunca escribe una ruta. El resto de los paneles
// (esfera, Spansh, retención, búsqueda de rutas, sesiones, sonido, datos y EDDN) tienen su
// propio módulo. Cada sección se pliega y la pantalla recuerda cuáles dejaste abiertas.
import {
  crearPanelComercio,
  crearPanelEddn,
  crearPanelRetencion,
  crearPanelSesiones,
  crearPanelSonido,
  crearPanelVentana,
} from './ajustes.js';
import * as api from './api.js';
import { crearPanelDatos } from './datos.js';
import { crearPanelEsfera } from './esfera.js';
import { texto } from './i18n.js';
import { crearPanelLectura } from './lectura.js';
import { crearPanelSpansh } from './spansh.js';

function panel(raiz, nombre) {
  return raiz.querySelector(`[data-panel="${nombre}"]`);
}

export function crearVistaConfiguracion(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) {
    c[elemento.dataset.campo] = elemento;
  }

  const secciones = [...raiz.querySelectorAll('details[data-seccion]')];
  let abiertasGuardadas = null;

  function abrirSeccion(nombre) {
    const seccion = secciones.find((s) => s.dataset.seccion === nombre);
    if (seccion) seccion.open = true;
  }

  function abiertas() {
    return secciones.filter((s) => s.open).map((s) => s.dataset.seccion);
  }

  async function recordarSecciones() {
    const lista = abiertas();
    const clave = JSON.stringify(lista);
    // Aplicar lo guardado también dispara «toggle»: si no cambió nada, no hay nada que guardar.
    if (clave === abiertasGuardadas) return;
    abiertasGuardadas = clave;
    const respuesta = await api.guardarSeccionesAbiertas(lista);
    if (respuesta.error) console.error(`no se guardaron las secciones: ${respuesta.error}`);
  }

  async function aplicarSecciones() {
    const ventana = await api.ajustesDeVentana();
    if (ventana.error) return;
    for (const seccion of secciones) {
      seccion.open = ventana.secciones_abiertas.includes(seccion.dataset.seccion);
    }
    abiertasGuardadas = JSON.stringify(abiertas());
  }

  for (const seccion of secciones) seccion.addEventListener('toggle', recordarSecciones);

  let spansh = null;
  const esfera = crearPanelEsfera(panel(raiz, 'esfera'), () => spansh.refrescar());
  spansh = crearPanelSpansh(panel(raiz, 'spansh'), () => {
    abrirSeccion('esfera');
    esfera.prepararDescarga();
  });
  const datosGuardados = crearPanelDatos(panel(raiz, 'datos'), () => spansh.refrescar());
  const retencion = crearPanelRetencion(panel(raiz, 'retencion'));
  const comercio = crearPanelComercio(panel(raiz, 'comercio'));
  const sesiones = crearPanelSesiones(panel(raiz, 'sesiones'));
  const sonido = crearPanelSonido(panel(raiz, 'sonido'));
  const lectura = crearPanelLectura(panel(raiz, 'lectura'));
  const ventana = crearPanelVentana(panel(raiz, 'ventana'));
  const eddn = crearPanelEddn(panel(raiz, 'eddn'));

  function pintar(datos) {
    const { journal, datos: almacen } = datos;
    c.config_journal.textContent = journal.carpeta ?? texto('configuracion.journal.sin_carpeta');
    c.config_origen.textContent = texto(
      journal.automatica
        ? 'configuracion.journal.origen_automatico'
        : 'configuracion.journal.origen_manual',
    );
    c.config_no_existe.hidden = !journal.elegida_no_existe;
    c.config_no_existe.textContent = journal.elegida_no_existe
      ? texto('configuracion.journal.no_existe')
      : '';
    c.config_datos.textContent = almacen.carpeta;
    c.config_version.textContent = texto('configuracion.datos.version_valor', { version: almacen.version });
    c.config_no_guardado.hidden = !datos.no_guardado;
    c.config_no_guardado.textContent = datos.no_guardado
      ? texto('configuracion.journal.no_guardado')
      : '';
  }

  c.elegir_carpeta.addEventListener('click', async () => pintar(await api.elegirCarpetaJournal()));
  c.carpeta_automatica.addEventListener('click', async () =>
    pintar(await api.usarCarpetaAutomatica()),
  );

  let carga = Promise.resolve();

  async function cargar() {
    await aplicarSecciones();
    const datos = await api.configuracion();
    pintar(datos);
    if (datos.esfera) esfera.cargar(datos.esfera);
    if (datos.retencion) retencion.cargar(datos.retencion);
    if (datos.eddn) eddn.cargar(datos.eddn);
    comercio.cargar();
    sesiones.cargar();
    sonido.cargar();
    lectura.cargar();
    ventana.cargar();
    datosGuardados.cargar();
    spansh.empezar();
  }

  return {
    cargar() {
      carga = cargar();
      return carga;
    },
    salir() {
      spansh.parar();
      datosGuardados.parar();
    },
    /**
     * Desde la bienvenida: abre Esfera y deja el foco en el radio, con `centro` propuesto. Espera
     * a la carga en curso, que si no pisaría el centro con el de la esfera guardada.
     */
    async prepararDescarga(centro) {
      try {
        await carga;
      } catch (error) {
        console.error(error);
      }
      abrirSeccion('esfera');
      esfera.prepararDescarga(centro);
    },
  };
}
