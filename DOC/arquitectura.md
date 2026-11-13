# Arquitectura

## Flujo general

```
ArchivosActivity (archivos.py)
 ├─ barra de herramientas Sugar (actividad, Editar, subir, actualizar,
 │   carpeta nueva, archivo nuevo, parar); iconos propios en icons/
 ├─ TabNotebook (tabs.py)
 │   ├─ FileView × N (fileview.py)        pestañas de carpeta
 │   └─ PluginTab × N (pluginui.py)       pestañas de plugin (imagen, texto...)
 ├─ PluginManager (pluginmgr.py)          descubre y elige plugins; PluginHost
 │        ├─ hilo: fileops.list_dir()     lee la carpeta
 │        └─ ListStore → TreeView         se rellena en trozos
 ├─ portapapeles interno (copiar/cortar)
 ├─ OpRunner (ops.py)                      hilo de copiar/mover/borrar
 └─ Diario: write_file/read_file           JSON con las pestañas
```

## fileops.py (sin GTK)

Todo lo que toca el sistema de ficheros. Solo importa `Gio` (tipos MIME e
iconos) y la biblioteca estándar, así que se prueba sin pantalla.

- `list_dir(path, show_hidden)`: `os.listdir` + `os.lstat`; los enlaces a
  carpetas se muestran como carpetas; ordena carpetas primero y después por
  nombre sin distinguir mayúsculas. Oculto = empieza por `.` o acaba en `~`.
- `make_file` crea un archivo vacío (0 bytes) con `O_EXCL`: nunca sobrescribe.
- `copy`, `move`, `delete`, `rename`, `make_dir`: errores como `FileOpError` con
  el mensaje ya traducido; `Cancelled` si se cancela (con un `Gio.Cancellable`).
- Copiar nunca sobrescribe (`unique_name`) y limpia lo copiado a medias si falla
  o se cancela. Borrar no sigue enlaces simbólicos y se niega a operar sobre `/`.
- Mover usa `os.rename`; si el origen y el destino están en sistemas de ficheros
  distintos (`EXDEV`) copia y después borra el origen (solo si la copia terminó).
- Una carpeta no se puede copiar ni mover dentro de sí misma.

## archives.py (sin GTK)

`create_archive(fuentes, carpeta, gz)` y `extract_archive(archivo, carpeta)`; ver
`AGENTS.md` para las reglas de seguridad y de limpieza. En `OpRunner` son los
tipos `tar`, `targz` (una sola operación con todas las fuentes) y `extract` (una
operación por archivo). El progreso de crear son bytes de datos de origen; el de
extraer, la posición en el archivo comprimido. Los nombres admitidos por
extensión son `.tar`, `.tar.gz` y `.tgz` (`archive_kind`), pero el contenido
manda: un `.tar.gz` que en realidad es un tar plano también se extrae.

## fileview.py

- **Carga:** `reload()` lanza un hilo con `list_dir`; el resultado vuelve al hilo
  principal con `GLib.idle_add` y un *token* que descarta cargas obsoletas. La
  lista se rellena en trozos de 400 filas con el modelo desconectado del árbol.
- **Ratón:** el clic principal se resuelve al *soltar* (`button-release-event`);
  el secundario, al pulsar. El doble clic de GTK (`row-activated`) se ignora; solo
  vale el Intro del teclado.
- **Edición:** renombrar usa el editor de celda del propio `TreeView`. Mientras se
  edita no se recarga la lista (`_editing`); los cambios en disco que llegan
  entonces se aplican al terminar (`_dirty`).
- **Cambios en disco:** `Gio.FileMonitor` solo en la pestaña visible, con un
  retardo de 800 ms para agrupar eventos.

## ops.py

`OpRunner` ejecuta de uno en uno los trabajos (`copy`, `move`, `delete`) en un
hilo. Las funciones de retorno (`on_start`, `on_progress`, `on_finish`) se
ejecutan en el hilo principal. El progreso se limita a unos 7 avisos por segundo.

## Diario

`write_file` guarda `{"tabs": [...], "current": n, "hidden": bool}`. `read_file`
ignora las rutas que ya no existen. Sugar puede llamar a `read_file` antes de que
la interfaz exista: en ese caso el estado queda pendiente y se aplica al final de
`__init__`.

## Límites conocidos

- No hay arrastrar y soltar, ordenar por columna ni historial atrás/adelante.
- El portapapeles es interno: no se comparte con otras aplicaciones.
- «Abrir con» usa los plugins, las actividades de Sugar y las aplicaciones registradas
  en el sistema (Gio).

## Actividades de Sugar como visores

`sugaractivities.py` (sin GTK) lee el `mime_types` del `activity.info` de las
actividades de `~/Activities` y `/usr/share/sugar/activities` (se relee solo si cambia
alguna de esas carpetas) y lanza la elegida con `activityfactory.create_with_uri`,
igual que la shell. Orden de un clic en `FileView.open_file`: plugin → aplicación por
defecto de Gio → actividad de Sugar, solo si es **la única** que declara el tipo y
**ignorando los tipos genéricos** (`text/plain`, `application/zip`,
`application/octet-stream`, que casi todas declaran). Esos genéricos sí salen en
«Abrir con». El `uri` es `file://` + la ruta **sin codificar** (Read quita el prefijo
y usa el resto como ruta). Esta misma actividad se excluye de la lista.
