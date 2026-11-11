# LUNA

Herramienta de escritorio para Windows que calcula rutas de comercio de
**Elite Dangerous** usando tu nave real, tus tiempos reales y tus datos.

No es un clon de INARA ni de los buscadores web. La diferencia es que lee el
journal del juego, detecta la nave que pilotas con su ingeniería y su bodega,
aprende cuánto tardas de verdad en saltar, atracar y comerciar, y con eso
estima la **ganancia por hora** de cada ruta ajustada a cómo juegas tú.

Está en español, funciona en local y no abre ningún puerto: solo hace
conexiones salientes a EDDN y, si lo pides, una descarga de Spansh.

## Estado: en construcción

El proyecto se construye en nueve fases y ahora mismo va por el final de la
primera. **Todavía no sirve para jugar.** Lo que ya funciona:

- Ventana nativa redimensionable que recuerda su tamaño y posición.
- Cálculo del rango de salto de cualquier nave, validado contra 448
  configuraciones reales de journal con un desvío del 0.0000 %, propulsores SCO
  y potenciadores Guardian incluidos.
- Lectura de la configuración, modo portable y detección de los problemas que
  impedirían que la base de datos funcione (unidad de red, carpeta
  sincronizada, sin permisos de escritura).

Lo que falta: lector del journal en vivo, mercados propios, EDDN, descarga de
Spansh, el motor de rutas, el modelo de tiempos, las alertas y el ejecutable.

## Requisitos

- Windows 10 u 11 con el juego **Live** (no Legacy). Funciona igual con Steam,
  Epic o la tienda de Frontier, porque el journal está en la misma carpeta.
- El componente **WebView2** de Microsoft, que ya viene en Windows 11 y en
  Windows 10 actualizado. Si falta, LUNA te lo dice al arrancar.
- Para ejecutarlo desde el código fuente, Python 3.12.

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
