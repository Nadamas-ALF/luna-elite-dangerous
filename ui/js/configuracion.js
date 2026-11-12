// Pantalla Configuración: por ahora solo la carpeta del journal. La carpeta se
// elige con el diálogo nativo de Windows; esta página nunca escribe una ruta.
import * as api from './api.js';
import { texto } from './i18n.js';

export function crearVistaConfiguracion(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) {
    c[elemento.dataset.campo] = elemento;
  }

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

  return { cargar: async () => pintar(await api.configuracion()) };
}
