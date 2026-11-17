import { crearVistaAhora } from './ahora.js';
import { crearVistaAlertas } from './alertas.js';
import * as api from './api.js';
import { cargarAspecto } from './aspecto.js';
import { crearVistaConfiguracion } from './configuracion.js';
import { crearVistaEstado } from './estado.js';
import { crearVistaFijadas } from './fijadas.js';
import { vigilarDesplazamiento } from './desplazamiento.js';
import { aplicarTextos, texto, textosFaltantes } from './i18n.js';
import { crearBarraLateral } from './lateral.js';
import { crearPanelPerfil } from './perfil.js';
import { crearVistaRendimiento } from './rendimiento.js';
import { crearVistaRutas } from './rutas.js';

// Con el estado cambiando a ritmo de juego, 750 ms dejan el retraso máximo por
// debajo de los 2 s de la fase 1 (0,5 s del núcleo + 0,75 s de esta consulta).
const INTERVALO_DE_CONSULTA = 750;
const VISTA_INICIAL = 'estado';

function mostrarVista(nombre) {
  for (const vista of document.querySelectorAll('.vista')) {
    vista.hidden = vista.id !== `vista-${nombre}`;
  }
  for (const enlace of document.querySelectorAll('.lateral__enlace')) {
    if (enlace.dataset.vista === nombre) enlace.setAttribute('aria-current', 'page');
    else enlace.removeAttribute('aria-current');
  }
}

function conectarNavegacion(alCambiar) {
  for (const enlace of document.querySelectorAll('.lateral__enlace')) {
    enlace.addEventListener('click', () => {
      mostrarVista(enlace.dataset.vista);
      alCambiar(enlace.dataset.vista);
    });
  }
}

function avisarDeError(clave) {
  const aviso = document.createElement('p');
  aviso.className = 'franja franja--advertencia';
  aviso.setAttribute('role', 'alert');
  aviso.textContent = texto(clave);
  document.querySelector('.contenido').prepend(aviso);
  return aviso;
}

/** Consulta el estado en bucle sin solapar llamadas; avisa si el núcleo no responde. */
function consultarEstado(alRecibir) {
  let avisoDeError = null;
  let enCurso = false;

  async function una() {
    if (enCurso) return;
    enCurso = true;
    try {
      alRecibir(await api.estado());
      avisoDeError?.remove();
      avisoDeError = null;
    } catch (error) {
      console.error(error);
      avisoDeError ??= avisarDeError('errores.sin_respuesta');
    } finally {
      enCurso = false;
    }
  }

  una();
  setInterval(una, INTERVALO_DE_CONSULTA);
}

async function arrancar() {
  aplicarTextos(document);
  vigilarDesplazamiento(document);
  const estado = crearVistaEstado(document.getElementById('vista-estado'));
  const configuracion = crearVistaConfiguracion(document.getElementById('vista-configuracion'));
  const vistaRutas = document.getElementById('vista-rutas');
  const perfil = crearPanelPerfil(vistaRutas);
  crearVistaRutas(vistaRutas, perfil);
  const ahora = crearVistaAhora(document.getElementById('vista-ahora'), perfil);
  const fijadas = crearVistaFijadas(document.getElementById('vista-fijadas'));
  const rendimiento = crearVistaRendimiento(document.getElementById('vista-rendimiento'));
  const alertas = crearVistaAlertas(
    document.getElementById('vista-alertas'),
    document.querySelector('[data-campo="aviso_alerta"]'),
    mostrarVista,
  );

  conectarNavegacion((nombre) => {
    if (nombre === 'configuracion') configuracion.cargar();
    else configuracion.salir();
    if (nombre === 'rutas') perfil.cargar();
    if (nombre === 'ahora') ahora.mostrar();
    else ahora.salir();
    if (nombre === 'fijadas') fijadas.mostrar();
    else fijadas.salir();
    if (nombre === 'alertas') alertas.mostrar();
    else alertas.salir();
    if (nombre === 'rendimiento') rendimiento.mostrar();
  });
  mostrarVista(VISTA_INICIAL);

  // Lo lee main.py al verificar la ventana; no afecta al funcionamiento normal.
  window.__luna = { textosFaltantes: textosFaltantes(), modulosEs: true };

  await api.esperarPuente();
  cargarAspecto();
  crearBarraLateral(document.querySelector('.app'), document.querySelector('[data-campo="lateral_plegar"]'));
  alertas.vigilar();
  consultarEstado((datos) => {
    estado.mostrar(datos);
    ahora.alEstado(datos);
    fijadas.alEstado(datos);
  });
}

arrancar();
