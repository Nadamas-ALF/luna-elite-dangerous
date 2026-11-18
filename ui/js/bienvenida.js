// Bienvenida del primer arranque (docs/primer-arranque.md). Solo cuenta dos cosas, el journal y
// los datos de mercado, y deja una decisión: descargar Spansh o empezar con EDDN. La esfera no
// se elige aquí: «Descargar» lleva a Configuración, al formulario que ya existe.
import * as api from './api.js';
import { nombreDeNave } from './estado.js';
import { texto } from './i18n.js';

function campos(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  return c;
}

/** Qué se dice del journal y qué botón lo acompaña (o `null`), según el estado de Python. */
function journal(datos) {
  const { comandante, nave } = datos;
  const lectura = datos.fuentes.journal.estado;
  if (comandante.legacy) return { mensaje: texto('estado.legacy', { version: comandante.version }), boton: null, bien: false };
  if (lectura === 'sin_carpeta') return { mensaje: texto('bienvenida.journal.sin_carpeta'), boton: 'elegir', bien: false };
  if (lectura === 'sin_archivos') return { mensaje: texto('bienvenida.journal.sin_archivos'), boton: 'elegir_otra', bien: false };
  if (comandante.nombre === null) return { mensaje: texto('bienvenida.journal.sin_comandante'), boton: null, bien: true };
  const modelo = nave.presente ? nombreDeNave(nave) : null;
  const mensaje = modelo
    ? texto('bienvenida.journal.encontrado_con_nave', { nombre: comandante.nombre, nave: modelo })
    : texto('bienvenida.journal.encontrado', { nombre: comandante.nombre });
  return { mensaje, boton: null, bien: true };
}

/**
 * `alDescargar(centro)` recibe el sistema donde está el comandante, o `null` si no se sabe;
 * `alEmpezar()` no recibe nada. Quien crea la vista decide a dónde lleva cada uno.
 */
export function crearVistaBienvenida(raiz, { alDescargar, alEmpezar }) {
  const c = campos(raiz);
  let centro = null;

  c.bienvenida_elegir.addEventListener('click', async () => {
    let respuesta;
    try {
      respuesta = await api.elegirCarpetaJournal();
    } catch (error) {
      console.error(error);
      respuesta = { no_guardado: true };
    }
    c.bienvenida_no_guardado.hidden = !respuesta.no_guardado;
  });
  c.bienvenida_descargar.addEventListener('click', () => alDescargar(centro));
  c.bienvenida_eddn.addEventListener('click', () => alEmpezar());

  return {
    /** Se llama con cada respuesta de `estado()`, como el resto de pantallas. */
    alEstado(datos) {
      // Oculta no hay nada que pintar; y sin cambios no se toca el `role="status"`, que un lector
      // de pantalla repetiría con cada consulta.
      if (raiz.hidden) return;
      centro = datos.ubicacion.presente ? datos.ubicacion.sistema : null;
      const { mensaje, boton, bien } = journal(datos);
      if (c.bienvenida_journal.textContent !== mensaje) c.bienvenida_journal.textContent = mensaje;
      c.bienvenida_indicador.classList.toggle('indicador--alerta', !bien);
      c.bienvenida_elegir_bloque.hidden = boton === null;
      if (boton) c.bienvenida_elegir.textContent = texto(`bienvenida.journal.${boton}`);
    },
  };
}
