// Señal de que queda contenido debajo: cada zona que se desplaza lleva `data-mas` mientras
// no esté en su final, y el CSS pinta el degradado solo entonces.
const MARGEN = 2;

function vigilar(zona) {
  const cuerpo = zona.querySelector('.vista__cuerpo');
  let pendiente = false;

  function medir() {
    pendiente = false;
    const quedan = cuerpo.scrollHeight - cuerpo.scrollTop - cuerpo.clientHeight;
    zona.dataset.mas = String(quedan > MARGEN);
  }
  const programar = () => {
    if (pendiente) return;
    pendiente = true;
    requestAnimationFrame(medir);
  };

  cuerpo.addEventListener('scroll', programar, { passive: true });
  // El alto del contenido cambia por muchas vías (filas nuevas, un <details> que se pliega, la
  // fuente que llega tarde): se vigila el tamaño de cada hijo, no las causas.
  const tamano = new ResizeObserver(programar);
  tamano.observe(cuerpo);
  for (const hijo of cuerpo.children) tamano.observe(hijo);
  programar();
}

export function vigilarDesplazamiento(raiz) {
  for (const zona of raiz.querySelectorAll('.vista__zona')) vigilar(zona);
}
