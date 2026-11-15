// Pantalla Configuración. La carpeta del journal se elige con el diálogo nativo
// de Windows; esta página nunca escribe una ruta. El resto de los paneles
// (esfera, Spansh, retención, búsqueda de rutas y EDDN) tienen su propio módulo.
import { crearPanelComercio, crearPanelEddn, crearPanelRetencion } from './ajustes.js';
import * as api from './api.js';
import { crearPanelEsfera } from './esfera.js';
import { texto } from './i18n.js';
import { crearPanelSpansh } from './spansh.js';

function panel(raiz, nombre) {
  return raiz.querySelector(`[data-panel="${nombre}"]`);
}

export function crearVistaConfiguracion(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) {
    c[elemento.dataset.campo] = elemento;
  }

  let spansh = null;
  const esfera = crearPanelEsfera(panel(raiz, 'esfera'), () => spansh.refrescar());
  spansh = crearPanelSpansh(panel(raiz, 'spansh'), () => esfera.revisarActual());
  const retencion = crearPanelRetencion(panel(raiz, 'retencion'));
  const comercio = crearPanelComercio(panel(raiz, 'comercio'));
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
    c.config_no_guardado.hidden = !datos.no_guardado;
    c.config_no_guardado.textContent = datos.no_guardado
      ? texto('configuracion.journal.no_guardado')
      : '';
  }

  c.elegir_carpeta.addEventListener('click', async () => pintar(await api.elegirCarpetaJournal()));
  c.carpeta_automatica.addEventListener('click', async () =>
    pintar(await api.usarCarpetaAutomatica()),
  );

  return {
    async cargar() {
      const datos = await api.configuracion();
      pintar(datos);
      if (datos.esfera) esfera.cargar(datos.esfera);
      if (datos.retencion) retencion.cargar(datos.retencion);
      if (datos.eddn) eddn.cargar(datos.eddn);
      comercio.cargar();
      spansh.empezar();
    },
    salir: () => spansh.parar(),
  };
}
