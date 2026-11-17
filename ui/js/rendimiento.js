// Pantalla Rendimiento (SPEC.md §7.5): lo ganado de verdad por sesión, ruta y
// mercancía, y la ganancia por hora real contra la que estimaba LUNA.
import * as api from './api.js';
import { crear, estacion } from './celdas.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';
import { ESENCIAL, pintarTabla, SECUNDARIA } from './tabla.js';

const clave = (nombre) => `comercio.rendimiento.${nombre}`;
const TODO = 'todo';
const PESTANAS = ['rutas', 'mercancias', 'sesiones'];
const INTERVALO_DE_IMPORTACION = 1000;
// Con menos tramos la comparación es orientativa: se dice (DESIGN.md §4.4).
const TRAMOS_SUFICIENTES = 5;

const sinDato = () => texto('formato.sin_dato');
const porHora = (valor) => (valor === null ? sinDato() : formato.creditosPorHora(valor));

function desviacion(comparacion) {
  if (!comparacion || comparacion.desviacion === null) return sinDato();
  return formato.porcentajeConSigno(comparacion.desviacion);
}

function ruta(r) {
  const bloque = crear('div', 'ruta');
  const flecha = crear('span', 'ruta__flecha', texto(clave('rutas.hacia')));
  bloque.append(estacion(r.origen), flecha, estacion(r.destino));
  return bloque;
}

function viajes(r) {
  if (!r.con_pausa) return String(r.viajes);
  return texto(clave('rutas.viajes_con_pausa'), { n: r.viajes, pausa: r.con_pausa });
}

const nombres = (mercancias) => mercancias.map((m) => m.nombre).join(', ');

// Cada columna: [nombre, prioridad, valor que se pinta, valor por el que se ordena].
const COLUMNAS_DE_RUTAS = [
  ['ruta', ESENCIAL, ruta, (r) => `${r.origen.estacion} ${r.destino.estacion}`],
  ['por_hora', ESENCIAL, (r) => porHora(r.por_hora), (r) => r.por_hora],
  [
    'desviacion',
    ESENCIAL,
    (r) => desviacion(r.comparacion),
    (r) => r.comparacion?.desviacion ?? null,
  ],
  ['mercancias', null, (r) => nombres(r.mercancias), (r) => nombres(r.mercancias)],
  ['viajes', null, viajes, (r) => r.viajes],
  ['ganancia', null, (r) => formato.creditos(r.ganancia), (r) => r.ganancia],
  ['tiempo', null, (r) => formato.duracion(r.segundos), (r) => r.segundos],
  [
    'estimada',
    SECUNDARIA,
    (r) => porHora(r.comparacion?.por_hora_estimada ?? null),
    (r) => r.comparacion?.por_hora_estimada ?? null,
  ],
];

function gananciaDeMercancia(m) {
  const ganancia = formato.creditos(m.ganancia);
  if (!m.sin_precio_de_compra) return ganancia;
  return texto(clave('mercancias.sin_precio'), { ganancia, n: m.sin_precio_de_compra });
}

const COLUMNAS_DE_MERCANCIAS = [
  ['mercancia', ESENCIAL, (m) => m.mercancia.nombre, (m) => m.mercancia.nombre],
  ['ganancia', ESENCIAL, gananciaDeMercancia, (m) => m.ganancia],
  ['toneladas', null, (m) => formato.toneladas(m.toneladas), (m) => m.toneladas],
  ['ventas', null, (m) => String(m.ventas), (m) => m.ventas],
];

function estadoDeSesion(s) {
  if (s.en_curso) return texto(clave('sesiones.en_curso'));
  return s.bloques > 1 ? texto(clave('sesiones.bloques'), { n: s.bloques }) : '';
}

const COLUMNAS_DE_SESIONES = [
  ['sesion', ESENCIAL, (s) => formato.fechaHora(s.inicio), (s) => s.inicio],
  ['ganancia', ESENCIAL, (s) => formato.creditos(s.ganancia), (s) => s.ganancia],
  ['por_hora', ESENCIAL, (s) => porHora(s.por_hora), (s) => s.por_hora],
  ['duracion', null, (s) => formato.duracion(s.segundos), (s) => s.segundos],
  ['toneladas', null, (s) => formato.toneladas(s.toneladas), (s) => s.toneladas],
  ['saltos', SECUNDARIA, (s) => String(s.saltos), (s) => s.saltos],
  [
    'saldo',
    SECUNDARIA,
    (s) => (s.saldo_fin === null ? sinDato() : formato.creditos(s.saldo_fin)),
    (s) => s.saldo_fin,
  ],
  ['estado_sesion', null, estadoDeSesion],
];

function campos(raiz) {
  const c = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) c[elemento.dataset.campo] = elemento;
  return c;
}

function mostrarTexto(elemento, mensaje) {
  elemento.hidden = !mensaje;
  elemento.textContent = mensaje ?? '';
}

function opcion(valor, etiqueta) {
  const elemento = crear('option', null, etiqueta);
  elemento.value = valor;
  return elemento;
}

function etiquetaDeSesion(s) {
  const datos = { fecha: formato.fechaHora(s.inicio), duracion: formato.duracion(s.segundos) };
  return texto(clave(s.en_curso ? 'opcion_en_curso' : 'opcion'), datos);
}

function textoDeComparacion(comparacion) {
  if (!comparacion) return texto(clave('comparacion.sin_tramos'));
  const datos = {
    n: comparacion.tramos,
    real: porHora(comparacion.por_hora_real),
    estimada: porHora(comparacion.por_hora_estimada),
    desviacion: desviacion(comparacion),
  };
  const frase = texto(clave('comparacion.resultado'), datos);
  if (comparacion.tramos >= TRAMOS_SUFICIENTES) return frase;
  return `${frase} ${texto(clave('comparacion.pocos'), { minimo: TRAMOS_SUFICIENTES })}`;
}

function mensajeDeError(respuesta) {
  return texto(clave(`errores.${respuesta.error}`));
}

function sesionElegida(respuesta) {
  return respuesta.sesiones.find((s) => s.inicio === respuesta.seleccion);
}

function textoDeVariacion(contra) {
  return texto(clave('dinero.variacion'), {
    cambio: formato.porcentajeConSigno(contra.variacion),
    fecha: formato.fechaHora(contra.inicio),
  });
}

function textoDeImportacion(estado) {
  if (estado.fase === 'importando') return texto(clave('importar.en_marcha'), estado);
  if (estado.fase === 'terminada') return texto(clave('importar.terminada'), estado);
  if (estado.fase === 'cancelada') return texto(clave('importar.cancelada'), estado);
  return texto(clave('importar.error'));
}

export function crearVistaRendimiento(raiz) {
  const c = campos(raiz);
  const botonesDePestana = raiz.querySelectorAll('[data-pestana]');
  let turno = 0;
  let pestana = PESTANAS[0];
  let sondeo = null;
  // Solo se cuenta cómo acabó la importación que se lanzó o se vio en marcha desde esta pantalla.
  let siguiendo = false;

  function pintarSelector(respuesta) {
    const opciones = respuesta.sesiones.map((s) => opcion(s.inicio, etiquetaDeSesion(s)));
    if (opciones.length) opciones.push(opcion(TODO, texto(clave('todo'))));
    c.sesion.replaceChildren(...opciones);
    c.sesion.value = respuesta.seleccion ?? '';
    c.sesion.disabled = opciones.length === 0;
    c.omitir_vacias.checked = respuesta.ajuste.omitir_vacias;
  }

  function pintarVariacion(contra) {
    c.dinero_variacion.hidden = !contra;
    if (!contra) return;
    c.dinero_variacion.textContent = textoDeVariacion(contra);
    // Color y signo a la vez: el color solo no basta (DESIGN.md §2).
    c.dinero_variacion.classList.toggle('dinero__variacion--sube', contra.variacion > 0);
    c.dinero_variacion.classList.toggle('dinero__variacion--baja', contra.variacion < 0);
  }

  function pintarDinero(respuesta) {
    const { resumen } = respuesta;
    c.dinero.hidden = false;
    c.dinero_saldo.textContent =
      respuesta.saldo_actual === null ? sinDato() : formato.creditos(respuesta.saldo_actual);
    c.dinero_ganancia.textContent = formato.creditos(resumen.ganancia);
    c.dinero_por_hora.textContent = porHora(resumen.por_hora);
    pintarVariacion(resumen.contra_anterior);
    const enCurso = sesionElegida(respuesta)?.en_curso;
    mostrarTexto(
      c.dinero_detalle,
      texto(clave(enCurso ? 'dinero.detalle_en_curso' : 'dinero.detalle'), {
        tiempo: formato.duracion(resumen.segundos),
        toneladas: formato.toneladas(resumen.toneladas),
        saltos: resumen.saltos,
      }),
    );
    c.comparacion.textContent = textoDeComparacion(resumen.comparacion);
  }

  function pintarLista(prefijo, columnas, datos, vacio) {
    pintarTabla(c[`${prefijo}_tabla`], columnas, datos, clave(`${prefijo}.columnas`));
    c[`${prefijo}_contenedor`].hidden = datos.length === 0;
    mostrarTexto(c[`${prefijo}_vacio`], datos.length === 0 ? vacio : null);
  }

  function pintarSesiones(respuesta) {
    const { pausa_horas: horas, por_partida: porPartida } = respuesta.ajuste;
    c.sesiones_ayuda.textContent = porPartida
      ? texto(clave('sesiones.ayuda_partida'))
      : texto(clave('sesiones.ayuda_pausa'), { horas });
    const elegir = (s) => cargar(s.inicio);
    pintarTabla(c.sesiones_tabla, COLUMNAS_DE_SESIONES, respuesta.sesiones, clave('sesiones.columnas'), elegir);
  }

  function ocultarTodo() {
    for (const nombre of ['dinero', 'dinero_detalle', 'pestanas']) c[nombre].hidden = true;
    for (const nombre of PESTANAS) c[`${nombre}_panel`].hidden = true;
    mostrarTexto(c.error, null);
  }

  function elegirPestana(nombre, enfocar = false) {
    pestana = nombre;
    for (const boton of botonesDePestana) {
      const activa = boton.dataset.pestana === nombre;
      boton.setAttribute('aria-selected', String(activa));
      // Con el teclado se entra a la lista por la pestaña activa y se mueve con las flechas.
      boton.tabIndex = activa ? 0 : -1;
      if (activa && enfocar) boton.focus();
    }
    for (const otra of PESTANAS) c[`${otra}_panel`].hidden = otra !== nombre;
  }

  function moverPestana(desde, tecla) {
    const posicion = PESTANAS.indexOf(desde);
    const destino = {
      ArrowRight: (posicion + 1) % PESTANAS.length,
      ArrowLeft: (posicion + PESTANAS.length - 1) % PESTANAS.length,
      Home: 0,
      End: PESTANAS.length - 1,
    }[tecla];
    if (destino !== undefined) elegirPestana(PESTANAS[destino], true);
  }

  function pintar(respuesta) {
    pintarSelector(respuesta);
    if (respuesta.sesiones.length === 0) {
      mostrarTexto(c.estado, texto(clave(respuesta.ocultas > 0 ? 'todas_ocultas' : 'sin_sesiones')));
      return;
    }
    pintarDinero(respuesta);
    pintarLista('rutas', COLUMNAS_DE_RUTAS, respuesta.rutas, texto(clave('rutas.vacio')));
    pintarLista('mercancias', COLUMNAS_DE_MERCANCIAS, respuesta.mercancias, texto(clave('mercancias.vacio')));
    pintarSesiones(respuesta);
    c.pestanas.hidden = false;
    elegirPestana(pestana);
    mostrarTexto(c.estado, texto(clave('actualizado'), { hora: formato.hora(new Date()) }));
  }

  async function cargar(sesion) {
    const mio = ++turno;
    mostrarTexto(c.estado, texto(clave('cargando')));
    let respuesta;
    try {
      respuesta = await api.rendimiento(sesion ?? null);
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (mio !== turno) return;
    // La sesión elegida desaparece si cambia el umbral en Configuración o se omiten las vacías.
    if (respuesta.error === 'sesion_desconocida' && sesion) {
      cargar(null);
      return;
    }
    ocultarTodo();
    if (respuesta.error) {
      mostrarTexto(c.estado, null);
      mostrarTexto(c.error, mensajeDeError(respuesta));
      return;
    }
    pintar(respuesta);
  }

  const recargar = () => cargar(c.sesion.value || null);

  function pintarImportacion(estado) {
    const enMarcha = estado.fase === 'importando';
    c.importar.disabled = enMarcha;
    c.importar_cancelar.hidden = !enMarcha;
    mostrarTexto(c.importacion, textoDeImportacion(estado));
  }

  function dejarDeSondear() {
    clearInterval(sondeo);
    sondeo = null;
  }

  async function consultarImportacion() {
    let estado;
    try {
      estado = await api.estadoDeLaImportacion();
    } catch (error) {
      console.error(error);
      dejarDeSondear();
      return;
    }
    if (estado.fase === 'importando') {
      siguiendo = true;
      sondeo ??= setInterval(consultarImportacion, INTERVALO_DE_IMPORTACION);
      pintarImportacion(estado);
      return;
    }
    dejarDeSondear();
    c.importar.disabled = false;
    c.importar_cancelar.hidden = true;
    if (!siguiendo || estado.fase === 'inactiva') return;
    siguiendo = false;
    pintarImportacion(estado);
    recargar();
  }

  async function alImportar() {
    let respuesta;
    try {
      respuesta = await api.importarHistorial();
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (respuesta.error) {
      mostrarTexto(c.importacion, texto(clave(`importar.errores.${respuesta.error}`)));
      return;
    }
    siguiendo = true;
    pintarImportacion(respuesta);
    sondeo ??= setInterval(consultarImportacion, INTERVALO_DE_IMPORTACION);
  }

  async function alCancelar() {
    try {
      await api.cancelarImportacion();
    } catch (error) {
      console.error(error);
    }
    consultarImportacion();
  }

  async function alOmitir() {
    let respuesta;
    try {
      respuesta = await api.guardarOmitirSesionesVacias(c.omitir_vacias.checked);
    } catch (error) {
      console.error(error);
      respuesta = { error: 'sin_respuesta' };
    }
    if (respuesta.error) c.omitir_vacias.checked = !c.omitir_vacias.checked;
    recargar();
  }

  c.sesion.addEventListener('change', recargar);
  c.actualizar.addEventListener('click', recargar);
  c.omitir_vacias.addEventListener('change', alOmitir);
  c.importar.addEventListener('click', alImportar);
  c.importar_cancelar.addEventListener('click', alCancelar);
  for (const boton of botonesDePestana) {
    boton.addEventListener('click', () => elegirPestana(boton.dataset.pestana));
    boton.addEventListener('keydown', (evento) => moverPestana(boton.dataset.pestana, evento.key));
  }

  return {
    mostrar() {
      recargar();
      consultarImportacion();
    },
  };
}
