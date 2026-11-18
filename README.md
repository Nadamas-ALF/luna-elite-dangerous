# LUNA

Herramienta de escritorio para Windows que calcula rutas de comercio de
**Elite Dangerous** usando tu nave real, tus tiempos reales y tus datos.

No es un clon de INARA ni de los buscadores web. La diferencia es que lee el
journal del juego, detecta la nave que pilotas con su ingeniería y su bodega,
aprende cuánto tardas de verdad en saltar, atracar y comerciar, y con eso
estima la **ganancia por hora** de cada ruta ajustada a cómo juegas tú.

Está en español, funciona en local y no abre ningún puerto: solo hace
conexiones salientes a EDDN y, si lo pides, una descarga de Spansh.

## Descargar

La versión 1.0.0 está en [Releases](https://github.com/Nadamas-ALF/luna-elite-dangerous/releases/latest):
`LUNA-1.0.0-win64.zip`, con su SHA-256 al lado.

1. Descomprime la carpeta entera donde quieras y abre `LUNA.exe`. No hace
   falta instalar nada ni tener Python.
2. La primera vez Windows puede decir «Windows protegió su PC», porque LUNA no
   está firmado: «Más información» y «Ejecutar de todas formas».
3. La pantalla de bienvenida te explica el journal y los datos de mercado.

El `LEEME.txt` del `.zip` explica cómo actualizar y desinstalar.

## Qué hace

- Lee el journal en vivo: tu nave, su rango real con carga, tu bodega, dónde
  estás y lo que compras y vendes.
- Guarda los mercados de una zona del espacio (la esfera) con lo que publica
  EDDN, lo que visitas y, si quieres, una descarga de Spansh.
- Busca rutas de un salto, bucles de ida y vuelta, rutas de varias paradas y
  circuitos, ordenadas por ganancia por hora.
- Aprende lo que tardas tú en cada parte del viaje y lo usa para estimar.
- Alertas con sonido cuando aparece una ruta mejor, rutas fijadas y el
  rendimiento real de tus sesiones.
- Dos temas: Sobrio (el de fábrica) y Lunar.

## Requisitos

- Windows 10 u 11 con el juego **Live** (no Legacy). Funciona igual con Steam,
  Epic o la tienda de Frontier, porque el journal está en la misma carpeta.
- El componente **WebView2** de Microsoft, que ya viene en Windows 11 y en
  Windows 10 actualizado. Si falta, LUNA te lo dice al arrancar.
- Para ejecutarlo desde el código fuente, Python 3.12.

## Construir el ejecutable

Con las dependencias de desarrollo instaladas:

```
.venv\Scripts\python.exe empaquetar.py
```

Comprueba las pruebas y el linter, construye con PyInstaller (`luna.spec`), añade
`LEEME.txt`, la licencia y las de terceros, y deja en `dist/` el `.zip` con su
SHA-256.

## Ejecutar desde el código

```
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
.venv\Scripts\python.exe main.py
```

Las pruebas, con las dependencias de desarrollo:

```
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```

## Dónde guarda tus datos

LUNA es portable: la configuración, la base de datos y el registro viven en su
propia carpeta. Si esa carpeta no sirve (una unidad de red, donde SQLite no
puede trabajar; una carpeta de OneDrive, que subiría la base entera cada vez
que cambia un precio; o una carpeta sin permiso de escritura), usa
`%LOCALAPPDATA%\LUNA` y te explica por qué.

El journal del juego se abre **solo en lectura**. No hay telemetría, ni
cuentas, ni envío de datos a ningún sitio.

## Atribución y datos del juego

`data/fsd.json` contiene las constantes de los propulsores de salto, derivadas
de [EDCD/coriolis-data](https://github.com/EDCD/coriolis-data). Esos datos son
propiedad intelectual de **Frontier Developments plc** y están sujetos a sus
términos y condiciones; se incluyen aquí para interoperar con el juego, como
hacen las demás herramientas de la comunidad. La licencia de este repositorio
cubre el código de LUNA, no los datos del juego.

Elite Dangerous es una marca de Frontier Developments plc. Este proyecto no
está afiliado ni respaldado por Frontier.

Las ilustraciones del tema Lunar (las flores y los velos de
`ui/assets/atmosphere/`) están generadas por IA a partir de ideas del autor.

Gracias a [EDCD](https://github.com/EDCD) por EDDN y por mantener los datos de
la comunidad, a [Spansh](https://spansh.co.uk) por sus volcados de la galaxia,
y a [Frameshift](https://github.com/TannerMidd/frameshift) como referencia de
diseño.

## Licencia

GNU General Public License v3.0 o posterior. El texto completo está en
[LICENSE](LICENSE).

LUNA es software libre: puedes redistribuirlo y modificarlo bajo los términos
de esa licencia. Se distribuye con la esperanza de que sea útil, pero **sin
ninguna garantía**.
