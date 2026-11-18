# Licencias que el `.venv` no trae

`empaquetar.py` copia las licencias de terceros de los paquetes instalados. Estas dos no vienen
con su texto, así que se guardan aquí, descargadas de su fuente oficial el 2026-11-18:

| Archivo | Componente | De dónde |
| --- | --- | --- |
| `proxy_tools-LICENSE.txt` | `proxy_tools` 0.1.0 (dependencia de pywebview) | `LICENSE.txt` del repositorio github.com/jtushman/proxy_tools, rama `master`. Es una licencia BSD aunque los metadatos de PyPI digan MIT |
| `WebView2-LICENSE.txt`, `WebView2-NOTICE.txt` | SDK de WebView2 de Microsoft (las DLL `Microsoft.Web.WebView2.*` que trae pywebview), versión 1.0.2957.106 | `LICENSE.txt` y `NOTICE.txt` del paquete NuGet `Microsoft.Web.WebView2` 1.0.2957.106, la misma versión que las DLL |

Si cambia la versión de pywebview, comprobar la versión de esas DLL y volver a sacar los textos.
