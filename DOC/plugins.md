# Plugins

Los plugins abren archivos **dentro** de la actividad, en una pestaña que el propio
plugin controla (su interfaz, su título, sus cambios sin guardar y su estado).
Cuantos más plugins haya, más opciones internas aparecen en *Abrir con*. Traen tres:

| Plugin | Abre | Qué ofrece |
|---|---|---|
| `image` (Visor de imágenes) | todo lo que decodifica GdkPixbuf (jpeg, png, gif, svg, bmp...) | Carga perezosa y reducida (12 MP en ~2 s), ← / → entre las imágenes de la carpeta, tamaño real si cabe en memoria |
| `text` (Editor de texto) | texto y código (`.pas`, `.py`, `.sh`, `.ini`, `Makefile`...); cualquier otro archivo solo como opción | GtkSourceView: números de línea, resaltado, deshacer/rehacer, buscar y reemplazar, guardado atómico, conserva codificación y finales de línea |
| `video` (Reproductor multimedia) | Ogg/Theora y WebM/VP8 con Vorbis (clic); módulos de tracker y MP3 si hay decodificador (clic); Matroska solo en «Abrir con» | GStreamer `playbin` con `xvimagesink`; reproducir/pausa, posición, volumen; espacio, ←/→ (5 s), AvPág/RePág (30 s), ↑/↓ (volumen), F (pantalla completa) |

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

### Vídeo y audio

- Solo se reproduce lo que decodifica GStreamer del sistema; en el XO-1 (Fedora 18, sin libav)
  son Theora, VP8 y Vorbis en Ogg o WebM. Con otra cosa la pestaña lo dice (`No se pudo reproducir`).
- GStreamer se importa al abrir la primera pestaña, no al cargar el plugin.
- La imagen sale por `GstVideo.VideoOverlay` sobre la ventana nativa de un `Gtk.DrawingArea`;
  en PyGObject 3.4 los métodos de la interfaz se llaman como función de clase
  (`VideoOverlay.set_window_handle(player, xid)`, `VideoOverlay.expose(player)`).
- **Trampa del overlay Xv:** el `Gtk.DrawingArea` que recibe el vídeo necesita `set_double_buffered(False)`,
  `set_app_paintable(True)` y `window.set_background_pattern(None)`; con el doble búfer GTK repinta
  encima y el vídeo se ve un instante y desaparece (el audio sigue). `xvimagesink` con
  `handle-events=False` para no quitarle a GTK sus eventos. Las capturas de pantalla (ni `ximagesrc`)
  no ven el overlay: se prueba a ojo.
- La actividad pone `enable_fullscreen_mode = False`: `Window.fullscreen()` de Sugar oculta barra y
  bandeja y, si no, enseña el botón de salir en una esquina (donde está el marco de Sugar).
- **Dispositivos de un solo uso:** en el XO-1 el audio (ALSA directo, sin PulseAudio ni mezclador)
  y el overlay Xv los abre un solo reproductor a la vez; una pestaña en pausa los sigue reteniendo (y
  bloquea otras pestañas y los sonidos de Sugar). Por eso: al empezar a reproducir, las demás pestañas
  multimedia se sueltan (`_release_others`: se destruye su pipeline y se recuerda la posición); una
  pestaña oculta con vídeo se suelta; el audio puede sonar en segundo plano; una pestaña quieta se
  suelta a los 10 s (audio y final de reproducción) o 120 s (vídeo en pausa); al volver, el vídeo se
  recrea en pausa en su posición y el audio al pulsar reproducir. El audio usa `fakesink` como
  sumidero de vídeo (no toca Xv).
- **Solo audio** (tipo `audio/*`, o sin flujo de vídeo tras cargar): panel negro (el área no tiene
  fondo, hay que pintarlo en `draw`), sin botones de modos de vídeo y sin pantalla completa.
- Tres modos (botones a la derecha del volumen): **normal** (ajustado a la ventana con su
  proporción), **1:1** (tamaño real, centrado; si no cabe, se ajusta) y **pantalla completa**
  (sin barras ni controles; Intro o espacio pausan, Esc vuelve al normal). La pantalla completa la
  hace la actividad (`host.set_fullscreen(True)`: oculta barra, pestañas y progreso).
- Memoria medida en el XO: ~4 MB al iniciar GStreamer y ~5 MB más al reproducir; al cerrar la
  pestaña solo se recuperan ~0,4 MB (las bibliotecas quedan cargadas), por eso no hay descarga por
  inactividad. Solo un proceso aparte la daría.
- **MP3:** OLPC OS 13.2 (Fedora 18) no trae decodificador. Con `gstreamer1-libav` de RPM Fusion Free
  (un solo paquete, 2,9 MB, 7,6 MB instalado, con su libav dentro) el plugin ofrece los MP3 con un clic
  (sin él, solo en «Abrir con»). Instalación en el XO (el paquete no está firmado con una clave que
  el sistema conozca; comprobar la suma SHA-256 contra la del repositorio):

  ```
  curl -LO https://rpmfusion-archive.ip-connect.vn.ua/free-archive/fedora/releases/18/Everything/i386/os/gstreamer1-libav-1.0.2-2.fc18.i686.rpm
  sudo rpm -ivh gstreamer1-libav-1.0.2-2.fc18.i686.rpm        # quitar: sudo rpm -e gstreamer1-libav
  ```

  Trae también decodificadores AAC y H.264 (no ofrecidos: el Geode no mueve H.264 con soltura).
  libav registra los decodificadores de MP3 con rango 0, y `decodebin` no elige elementos de rango 0:
  el plugin sube `avdec_mp3` (coma fija; ~40 % menos CPU que `avdec_mp3float` en el Geode) a
  `Gst.Rank.MARGINAL`. Medido: ~13 % de CPU reproduciendo MP3 a 64 kbps. Una actualización del
  sistema operativo puede quitar el paquete (no es de la imagen).
- **Módulos de tracker** (`.mod`, `.xm`, `.it`, `.s3m`, `.stm`; tipos `audio/x-mod`, `x-xm`, `x-it`, `x-s3m`,
  `x-stm`): los decodifica el elemento `modplug` de GStreamer, del paquete `gstreamer1-plugins-bad-free-extras`
  (Fedora 18, repositorio de actualizaciones; rango primario, no hace falta subirlo). Arrastra
  `gstreamer1-plugins-bad-free`, ImageMagick, libass, schroedinger y zbar: unos 13 MB instalados, 7,7 de ellos
  ImageMagick. El plugin los ofrece con un clic si existe `libgstmodplug.so` (sin él, solo en «Abrir con»).
  Medido en el XO-1: un módulo de 4 canales, ~25-35 % de CPU. Si `yum` se queda sin memoria, los scriptlets
  `%post` fallan ('Cannot allocate memory'): ejecutar `sudo ldconfig`. Otros tipos que modplug no lee (`.mo3`, `.far`,
  `.amf`, `.okt`, `.umx`, `.itz`...) no están en la lista.
- Pausa al pasar a segundo plano; el estado del Diario guarda posición (0 si llegó al final) y volumen.
- Las capturas de `dbg.py shot` no incluyen el vídeo (es una ventana nativa de X): probar a ojo.
- Convertir en el PC: `ffmpeg -i in.mp4 -c:v libtheora -q:v 5 -c:a libvorbis -q:a 3 out.ogv`.

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
botones), `close_tab(tab)`, `open_path(ruta)`, `data_dir`, `add_icon_path(ruta)`,
`set_fullscreen(bool)` (pantalla completa sin barras ni pestañas).

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
