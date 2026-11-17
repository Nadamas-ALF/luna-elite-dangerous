// Barra lateral plegable a mano (solo por encima de 1200 px: por debajo ya se pliega sola).
// La elección se recuerda en config.json, no en el navegador: la ventana no conserva nada.
import * as api from './api.js';
import { texto } from './i18n.js';

export async function crearBarraLateral(app, boton) {
  let tocada = false;

  function reflejar(plegado) {
    if (plegado) app.dataset.lateral = 'plegado';
    else delete app.dataset.lateral;
    const clave = plegado ? 'navegacion.desplegar' : 'navegacion.plegar';
    boton.setAttribute('aria-expanded', String(!plegado));
    boton.setAttribute('aria-label', texto(clave));
    boton.title = texto(clave);
  }

  boton.addEventListener('click', async () => {
    tocada = true;
    const plegado = app.dataset.lateral !== 'plegado';
    reflejar(plegado);
    const respuesta = await api.guardarLateralPlegado(plegado);
    // Si no se pudo guardar, la barra sigue como se ve: solo se pierde la elección al cerrar.
    if (respuesta.error) console.error(`no se guardó la barra lateral: ${respuesta.error}`);
  });

  const ajustes = await api.ajustesDeVentana();
  // Si se pulsó mientras llegaba, lo que se ve ya es lo que se guardó: no se pisa.
  if (!ajustes.error && !tocada) reflejar(ajustes.lateral_plegado);
}
