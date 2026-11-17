// Campo para cifras enteras grandes: enseña «1.000.000» mientras se escribe y entrega el número.
// Un `<input type="number">` no admite separador de miles; este es un campo de texto que solo
// deja pasar dígitos. Los límites los valida Python, aquí no se comprueba ningún rango.
const MAXIMO_DE_DIGITOS = 15; // más no cabe sin perder precisión en un número de JavaScript

const conPuntos = (digitos) => digitos.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
const soloDigitos = (cadena) => cadena.replace(/\D/g, '').slice(0, MAXIMO_DE_DIGITOS);

/** El número que hay escrito, o null si el campo está vacío. */
export function leerMiles(entrada) {
  const digitos = soloDigitos(entrada.value);
  return digitos === '' ? null : Number(digitos);
}

export function escribirMiles(entrada, valor) {
  entrada.value = valor === null || valor === undefined ? '' : conPuntos(soloDigitos(String(valor)));
}

function reformatear(entrada) {
  const antes = entrada.value.slice(0, entrada.selectionStart ?? entrada.value.length);
  const digitosAntes = soloDigitos(antes).length;
  entrada.value = conPuntos(soloDigitos(entrada.value));
  let vistos = 0;
  let posicion = 0;
  while (posicion < entrada.value.length && vistos < digitosAntes) {
    if (entrada.value[posicion] !== '.') vistos += 1;
    posicion += 1;
  }
  entrada.setSelectionRange(posicion, posicion);
}

export function activarMiles(entrada) {
  entrada.addEventListener('input', () => reformatear(entrada));
}
