// Pantalla Estado: pinta lo que Python devuelve y, cuando falta un valor, dice
// por qué con el texto del código de motivo (docs/decisiones.md).
import { copiar } from './copiar.js';
import * as formato from './formato.js';
import { texto } from './i18n.js';

function campos(raiz) {
  const tabla = {};
  for (const elemento of raiz.querySelectorAll('[data-campo]')) {
    tabla[elemento.dataset.campo] = elemento;
  }
  return tabla;
}

function motivo(codigo) {
  return texto(`motivos.${codigo}`);
}

/** Pone el valor o, si falta, el motivo en tono apagado. */
function poner(elemento, valor, codigoDeMotivo) {
  const hay = valor !== null && valor !== undefined;
  elemento.textContent = hay ? valor : motivo(codigoDeMotivo);
  elemento.classList.toggle('motivo', !hay);
}

function ponerPanelAusente(c, prefijo, ausente, codigo) {
  c[`${prefijo}_datos`].hidden = ausente;
  c[`${prefijo}_motivo`].hidden = !ausente;
  if (ausente) c[`${prefijo}_motivo`].textContent = motivo(codigo);
}

/** Legacy y "sin journal" tienen una causa única: se dice una vez y no hay paneles. */
function sinPaneles(datos) {
  return datos.comandante.legacy || datos.sin_journal;
}

function textoDeFranja(datos) {
  if (datos.comandante.legacy) {
    return texto('estado.legacy', { version: datos.comandante.version });
  }
  return datos.sin_journal ? motivo('sin_journal') : '';
}

function pintarCabecera(c, datos) {
  const { comandante } = datos;
  // En Legacy el journal sí trae comandante, pero LUNA descarta esos datos:
  // decir "sin comandante" o "falta el saldo" sería falso.
  const sinNombre = sinPaneles(datos) || comandante.nombre === null;
  c.comandante.textContent = sinNombre ? texto('navegacion.estado') : comandante.nombre;
  c.comandante_motivo.hidden = sinPaneles(datos) || comandante.nombre !== null;
  c.comandante_motivo.textContent = motivo(comandante.motivo_nombre);
  c.saldo_bloque.hidden = sinPaneles(datos);
  poner(
    c.saldo,
    comandante.saldo === null ? null : formato.creditos(comandante.saldo),
    comandante.motivo_saldo,
  );
  c.modo.hidden = comandante.version === null;
  c.modo.textContent = texto(comandante.legacy ? 'estado.modo.legacy' : 'estado.modo.live');
  const franja = textoDeFranja(datos);
  c.franja.hidden = franja === '';
  c.franja.textContent = franja;
}

function pintarUbicacion(c, ubicacion) {
  ponerPanelAusente(c, 'ubicacion', !ubicacion.presente, ubicacion.motivo);
  c.copiar.hidden = !ubicacion.presente;
  if (!ubicacion.presente) return;

  c.sistema.textContent = ubicacion.sistema;
  c.estacion.textContent = ubicacion.estacion
    ? ubicacion.estacion.nombre
    : texto('estado.ubicacion.en_vuelo');
  poner(
    c.coordenadas,
    ubicacion.posicion && formato.coordenadas(ubicacion.posicion),
    'sin_coordenadas',
  );
  const distancia = ubicacion.distancia_al_centro;
  poner(
    c.al_centro,
    distancia === null
      ? null
      : texto('estado.ubicacion.al_centro_valor', {
          distancia: formato.anosLuz(distancia),
          centro: ubicacion.centro,
        }),
    'sin_coordenadas',
  );
}

function pintarNave(c, nave) {
  ponerPanelAusente(c, 'nave', !nave.presente, nave.motivo);
  if (!nave.presente) return;

  c.nave_modelo.textContent = nave.nombre
    ? texto('estado.nave.modelo_con_nombre', { modelo: nave.modelo, nombre: nave.nombre })
    : nave.modelo;
  c.nave_bodega.textContent = formato.toneladas(nave.capacidad_carga);
  poner(
    c.nave_plataforma,
    nave.plataforma && texto(`estado.nave.plataformas.${nave.plataforma}`),
    nave.motivo_plataforma,
  );
  poner(
    c.nave_rango_vacia,
    nave.rango_vacio === null ? null : formato.anosLuz(nave.rango_vacio),
    nave.motivo_rango,
  );
  poner(
    c.nave_rango_cargada,
    nave.rango_cargado === null ? null : formato.anosLuz(nave.rango_cargado),
    nave.motivo_rango,
  );
  poner(c.nave_combustible, combustible(nave), nave.motivo_combustible);
}

function combustible(nave) {
  if (nave.combustible === null) return null;
  if (!nave.combustible_capacidad) return formato.toneladasConDecimales(nave.combustible);
  return texto('formato.toneladas', {
    valor: formato.proporcion(
      formato.decimales(nave.combustible, 1),
      formato.decimales(nave.combustible_capacidad, 1),
    ),
  });
}

function filaDeCarga(mercancia) {
  const fila = document.createElement('li');
  const nombre = document.createElement('span');
  nombre.textContent = mercancia.nombre;
  const cantidad = document.createElement('span');
  cantidad.className = 'cifra';
  cantidad.textContent = formato.toneladas(mercancia.cantidad);
  fila.append(nombre, cantidad);
  return fila;
}

function pintarCarga(c, carga) {
  c.carga_lista.replaceChildren();
  c.carga_total.hidden = !carga.presente;
  c.carga_vacia.hidden = carga.presente && carga.mercancias.length > 0;
  if (!carga.presente) {
    c.carga_vacia.textContent = motivo(carga.motivo);
    return;
  }
  c.carga_total.textContent =
    carga.capacidad === null
      ? texto('estado.carga.resumen_sin_capacidad', { total: formato.decimales(carga.total, 0) })
      : texto('estado.carga.resumen', {
          total: formato.decimales(carga.total, 0),
          capacidad: formato.decimales(carga.capacidad, 0),
        });
  c.carga_vacia.textContent = texto('estado.carga.vacia');
  c.carga_lista.append(...carga.mercancias.map(filaDeCarga));
}

function pintarFuentes(c, fuentes) {
  const journal = fuentes.journal.estado;
  c.fuente_journal.classList.toggle('indicador--alerta', journal !== 'leyendo');
  const eddn = fuentes.eddn.estado;
  c.fuente_eddn.classList.toggle('indicador--apagado', eddn === 'desactivado' || eddn === 'conectando');
  c.fuente_eddn.classList.toggle('indicador--alerta', eddn === 'sin_datos' || eddn === 'reintentando');
  c.fuente_eddn.textContent = texto(`estado.fuentes.eddn_estado.${eddn}`);
  const spansh = fuentes.spansh.estado;
  c.fuente_spansh.classList.toggle('indicador--apagado', spansh === 'sin_descarga' || spansh === 'pausada');
  c.fuente_spansh.classList.toggle('indicador--alerta', spansh === 'error');
  pintarTextoDeSpansh(c, fuentes.spansh);
}

function porcentajeDe(spansh) {
  if (spansh.estado === 'importando') {
    return spansh.tamano_archivo ? formato.porcentaje(spansh.leido, spansh.tamano_archivo) : '';
  }
  return spansh.total ? formato.porcentaje(spansh.descargado, spansh.total) : '';
}

/** El texto de la fila de Spansh; «hace N» cambia con el reloj, así que se repinta aparte. */
function pintarTextoDeSpansh(c, spansh) {
  const { estado, ultima } = spansh;
  const clave = estado === 'importando' ? `importando_${spansh.etapa}` : estado;
  c.fuente_spansh.textContent = texto(`estado.fuentes.spansh_estado.${clave}`, {
    porcentaje: porcentajeDe(spansh),
    guardados: formato.decimales(spansh.guardados ?? 0, 0),
    encontrados: formato.decimales(spansh.encontrados ?? 0, 0),
    motivo: spansh.error ? texto(`configuracion.spansh.errores.${spansh.error}`) : '',
    hace: ultima ? formato.hace(ultima.fecha) : '',
    centro: ultima ? ultima.centro : '',
    radio: ultima ? formato.cantidad(ultima.radio) : '',
  });
}

function pintarAvisos(c, datos) {
  const codigos = datos.motivo ? [datos.motivo, ...datos.avisos] : datos.avisos;
  c.avisos.replaceChildren(
    ...codigos.map((codigo) => {
      const aviso = document.createElement('li');
      aviso.className = 'franja franja--advertencia';
      aviso.textContent = texto(`datos.${codigo}`);
      return aviso;
    }),
  );
}

export function crearVistaEstado(raiz) {
  const c = campos(raiz);
  let ultimo = null;

  c.copiar.addEventListener('click', () => copiar(c.copiar, c.sistema.textContent, c.sistema));

  /** «Último evento hace N s» cambia con el reloj aunque los datos no cambien. */
  function refrescarTiempos() {
    if (!ultimo) return;
    const { estado, ultimo_evento: marca } = ultimo.fuentes.journal;
    const base = texto(`estado.fuentes.journal_estado.${estado}`);
    c.fuente_journal.textContent =
      estado === 'leyendo' && marca
        ? texto('estado.fuentes.journal_ultimo', { estado: base, hace: formato.hace(marca) })
        : base;
    pintarTextoDeSpansh(c, ultimo.fuentes.spansh);
  }

  function mostrar(datos) {
    const firma = JSON.stringify(datos);
    if (firma !== JSON.stringify(ultimo)) {
      ultimo = datos;
      pintarCabecera(c, datos);
      pintarUbicacion(c, datos.ubicacion);
      pintarNave(c, datos.nave);
      pintarCarga(c, datos.carga);
      pintarFuentes(c, datos.fuentes);
      pintarAvisos(c, datos.datos);
      for (const panel of raiz.querySelectorAll('[data-solo-live]')) {
        panel.hidden = sinPaneles(datos);
      }
    }
    refrescarTiempos();
  }

  return { mostrar, refrescarTiempos };
}
