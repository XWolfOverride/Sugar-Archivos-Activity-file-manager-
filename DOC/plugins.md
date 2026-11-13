# Plugins

Los plugins abren archivos **dentro** de la actividad, en una pestaña que el propio
plugin controla (su interfaz, su título, sus cambios sin guardar y su estado).
Cuantos más plugins haya, más opciones internas aparecen en *Abrir con*. Traen dos:

| Plugin | Abre | Qué ofrece |
|---|---|---|
| `image` (Visor de imágenes) | todo lo que decodifica GdkPixbuf (jpeg, png, gif, svg, bmp...) | Carga perezosa y reducida (12 MP en ~2 s), ← / → entre las imágenes de la carpeta, tamaño real si cabe en memoria |
| `text` (Editor de texto) | texto y código (`.pas`, `.py`, `.sh`, `.ini`, `Makefile`...); cualquier otro archivo solo como opción | GtkSourceView: números de línea, resaltado, deshacer/rehacer, buscar y reemplazar, guardado atómico, conserva codificación y finales de línea |

### Build y Run del editor

Junto al archivo abierto, si existe `build.sh` y/o `run.sh`, el editor muestra los
botones **Compilar** y **Ejecutar** (F7 / F5) y, mientras corre, **Parar**. Se
comprueba al abrir y cada vez que la pestaña se muestra, así que aparecen y
desaparecen según haya o no los scripts (solo cuentan los de **la misma carpeta**).

- Antes de ejecutar se **guarda** el archivo (si no se puede guardar, no se ejecuta).
- El script se ejecuta con `sh` en esa carpeta, con stdin cerrado y stdout y stderr
  en un solo flujo que llega en vivo a un panel «Salida» (se recorta pasado ~300 KB).
- Se lanza con `bash -l` para que vea el mismo `PATH` que una terminal (compiladores
  instalados en carpetas del usuario).
- *Parar* envía TERM a todo el **grupo de procesos** y, a los 2 s, KILL: también
  mueren los programas que haya arrancado. Cerrar la pestaña también lo para.
- **Al cerrar la actividad** (o salir el intérprete por cualquier causa) no queda
  ningún script: `scriptrunner.stop_all()`, registrado con `atexit`, manda TERM a
  los grupos en marcha y, a 1 s, KILL. No cubre un `kill -9` de la propia actividad.
- Solo se ejecuta al pulsar el botón; nunca por abrir un archivo.
- El código está en `plugins/text/scriptrunner.py` (sin GTK, con sus pruebas).

## Dónde se buscan

1. `plugins/` de la actividad (los que trae).
2. `<datos de la actividad>/plugins/` (los del usuario; sobreviven a reinstalar).
3. Las carpetas de `ARCHIVOS_PLUGIN_PATH` (separadas por `:`; útil para desarrollar).

Cada plugin es una carpeta con un `plugin.py`. Si un id se repite, gana el primero;
un plugin que falla al cargarse se salta y queda anotado (`app._plugins.errors`),
sin afectar a los demás. **Ojo:** un plugin es código Python que se ejecuta con los
permisos de la actividad; instala solo los que conozcas.

```
plugins/miplugin/
    plugin.py          la clase Plugin (obligatorio)
    miplugin_util.py   módulos auxiliares (nombres únicos: comparten sys.path)
    po/es.po           traducciones propias (opcional, ver DOC/i18n.md)
    icons/*.svg        iconos propios (opcional; se añaden al tema)
```

## El contrato (`pluginapi.py`, `pluginui.py`)

```python
import pluginapi
from i18n import N_
from pluginui import PluginTab

class Plugin(pluginapi.Plugin):
    id = 'hex'                       # único (si falta, el nombre de la carpeta)
    name = N_('Hex viewer')          # visible; se traduce con el po del plugin

    def handles(self, path, content_type):
        return 20                    # 0 no; 1-49 solo «Abrir con»; 50-100 también el clic

    def open_tab(self, path):
        return HexTab(self.host, self, path)

class HexTab(PluginTab):
    def __init__(self, host, plugin, path):
        PluginTab.__init__(self, host, plugin, path)
        ...                          # rellenar la caja con self.pack_start(...)
```

`handles` devuelve una puntuación. Con un clic se abre el plugin de mayor puntuación
si llega a 50; los demás aparecen en *Abrir con* (primero los internos, luego las
aplicaciones del sistema). Si no hay ninguno, se usa la aplicación por defecto.
*Abrir con* lista **todos** los plugins, también los que dan 0 (`plugins_for(ruta,
all_plugins=True)`), por orden de puntuación y después por nombre: así se puede
forzar uno en un archivo que ninguno reconoce.

`PluginTab` (todos los métodos tienen una versión que no hace nada):

| Método | Para qué |
|---|---|
| `get_title()` / `get_tooltip()` | texto de la pestaña (la actividad antepone `●` si hay cambios) |
| `is_modified()` / `save()` / `discard_changes()` | cambios sin guardar: la actividad avisa al cerrar la pestaña o salir |
| `get_state()` / `restore_state(estado)` | estado en el Diario (solo tipos JSON); lo recupera al reanudar |
| `on_shown()` / `on_hidden()` | la pestaña se ve / pasa a segundo plano |
| `toolbar_actions()` | `[(icono, texto, función)]`: botones que la pestaña pone en la barra principal (donde las carpetas tienen «Carpeta nueva» y «Archivo nuevo») mientras se ve. El editor pone «Guardar todo» (`host.save_all()`) |
| `dispose()` | se cierra: soltar hilos, memoria, ficheros |
| `title_changed()` | el plugin avisa de que el título o el estado cambiaron |

El plugin recibe `host` (`PluginHost` en `archivos.py`), su única puerta de entrada:
`show_message(texto, título)`, `ask(título, texto, botones, callback)` (aviso con
botones), `close_tab(tab)`, `open_path(ruta)`, `data_dir`, `add_icon_path(ruta)`.

## Qué hace la actividad por ti

- Abrir el mismo archivo con el mismo plugin vuelve a la pestaña que ya existe.
- Mientras una pestaña de plugin está activa, los botones de carpeta (copiar,
  nueva carpeta...) quedan desactivados.
- Cerrar la pestaña o la actividad con `is_modified()` pregunta *Guardar / Descartar
  / Cancelar* (`Activity.can_close`).
- Las pestañas de plugin se guardan y recuperan en el Diario (`{"type": "plugin",
  "plugin": id, "path": ..., "state": ...}`).
- Si `open_tab` lanza una excepción, se muestra el mensaje y la actividad sigue.

## Trampas conocidas

- En un hilo, no uses por primera vez un atributo de `gi` (PyGObject 3.4 los carga
  de forma perezosa y falla): tócalo antes, en el hilo principal (ver `image`).
- Sugar **encola** los avisos y solo enseña el primero: usa `host.show_message`
  (sustituye al anterior) y `host.ask` en lugar de crear avisos propios.
- Un contenedor con `set_no_show_all(True)` no muestra a sus hijos al hacer `show()`.
