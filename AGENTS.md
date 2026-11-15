# Archivos (actividad Sugar)

Explorador de archivos con pestañas para Sugar/OLPC. Una lista por pestaña, sin
doble panel. Autor: XWolf. Licencia MIT.

## Decisiones

- **Python 2.7 + GTK3 + sugar3**, porque una actividad Sugar se lanza con
  `sugar-activity <módulo>` (Python) y se integra con la shell, el marco y el
  Diario. No aplica la regla de C#/Native AOT de los proyectos modernos: la
  plataforma es Python por diseño y .NET no existe para i586. Free Pascal se
  descartó: solo trae unidades de GTK1/GTK2, no GTK3, y no se integra con Sugar.
- **Sin dependencias extra:** solo lo que trae OLPC OS 13.2 (Sugar 0.112,
  PyGObject 3.4, GTK 3.6). El código debe ser compatible con **Python 2**.
- **Poca memoria:** sin miniaturas, sin vista previa, sin árbol lateral. Lista
  (`TreeView`), un icono por tipo en caché, vigilancia de cambios solo en la
  pestaña visible. Una instancia ocupa unos 30 MB.
- **Aspecto de lista de Sugar:** filas de 56 px (75 % de `GRID_CELL_SIZE`, que
  es la altura de las filas del Diario) e iconos GNOME de 32 px. El tema de
  Sugar no trae iconos de tipos de archivo, por eso se piden al tema GNOME.
- **Pestañas:** una sola ocupa la mitad del ancho; con dos o más se reparten el
  ancho completo a partes iguales (`tab-expand` con el mismo mínimo en todas).
  El botón «+» es el *action widget* final del `Gtk.Notebook` y cada pestaña
  lleva su «X» (28 px). Ver `tabs.py`.
- **Iconos propios** en `icons/` (cortar, renombrar, carpeta nueva, archivo
  nuevo), porque el tema de Sugar no los trae. Sugar añade esa carpeta al tema
  de iconos solo (`Activity.__init__`). Estilo: círculo blanco con el dibujo en
  gris oscuro (`#4C4D4F`), 55×55, como los de actualizar/subir.
- **Barra superior sin gestión de pestañas:** se hace con el «+», la «X» y los
  atajos de teclado. La barra principal lleva Carpeta nueva y Archivo nuevo.
- **Cerrar la última pestaña cierra la actividad** (`self.close()`, que guarda
  el estado en el Diario). Con varias, solo cierra esa.
- **Nombres en negrita** (`weight` en el renderizador del nombre, como el Diario).
  El tamaño es el del tema.
- **Diario:** no hay código propio. El icono de Inicio reanuda la última entrada
  gracias al ajuste de Sugar `resume-activity`; «Empezar nuevo» crea otra. Ojo:
  **cada arranque directo con `sugar-activity` (sin `-a`/`-o`) crea una entrada
  nueva**; para probar sin ensuciar el Diario hay que reanudar una existente
  (ver `DOC/depuracion.md`).
- **Tar y tar.gz en `archives.py`** (sin GTK, `tarfile` de la biblioteca estándar).
  Crear escribe en `.nombre.part` (oculto) y renombra al terminar. Extraer lee en
  modo flujo (poca RAM) a una carpeta oculta `.x.extracting` junto al destino y,
  solo si todo va bien, la deja con su nombre: una única entrada en la raíz pasa a
  la carpeta de destino; varias, a una carpeta con el nombre del archivo. Nunca
  sobrescribe; si falla o se cancela no deja restos.
- **Seguridad al extraer:** rutas absolutas → relativas; `..` → error; no se escribe
  a través de enlaces que salgan del destino; enlaces duros solo hacia lo ya
  extraído; sin setuid/setgid/sticky, dispositivos ni tuberías; el propietario
  siempre conserva acceso. **Truncados:** `tarfile` toma un fin de fichero
  inesperado por el final del archivo, así que se verifica el CRC de gzip leyendo
  hasta el final, el marcador de fin en los `.tar` y el tamaño de cada archivo.
  El formato (gzip o no) se decide por el contenido, no por la extensión.
- **Interfaz con operaciones largas:** la barra de progreso inferior tiene sus
  hijos mostrados a mano (con `set_no_show_all` el contenedor se muestra pero los
  hijos no: la barra llegó a medir 12 px sin que nadie lo viera). La lista se
  rellena en un almacén aparte y se cambia de golpe, sin vaciar la que se ve; los
  cambios en ocultos y los producidos durante una operación no recargan.
- **Plugins** (`pluginapi.py`, `pluginmgr.py`, `pluginui.py`, `plugins/`): abren
  archivos en pestañas controladas por el plugin; puntuación 0-100 (≥50 = abre con
  un clic, 1-49 = solo «Abrir con»); estado en el Diario; aviso de cambios sin
  guardar con `can_close()`. Contrato y trampas en `DOC/plugins.md`. Las pestañas
  tienen `kind` (`'folder'` o `'plugin'`): `current_view()` es solo de carpeta,
  `current_tab()` es cualquiera. Los botones de carpeta se desactivan en pestañas
  de plugin.
- **i18n** (`i18n.py`, `tools/translate.py`, `po/`): gettext leyendo los `.po`
  directamente (sin compilar), `tr`/`ntr`/`N_`, plurales por `Plural-Forms`, una
  carpeta `po/` por plugin. Los textos que se traducen más tarde llevan `N_()`
  (si no, la herramienta no los ve). `tests/test_i18n.py` ejecuta `check`: un texto
  sin traducir rompe las pruebas. Flujo en `DOC/i18n.md`.
- **Multimedia** (`plugins/video`, «Reproductor multimedia»): GStreamer 1.0 importado al abrir la primera pestaña (no al cargar
  el plugin), `playbin` + `xvimagesink` en un `Gtk.DrawingArea`. El XO-1 solo decodifica Theora,
  VP8 y Vorbis (Ogg/WebM; sin libav: ni H.264 ni MP3). Modos normal (ajustado), 1:1 (`set_render_rectangle` centrado) y pantalla completa
  (`host.set_fullscreen`: la actividad oculta barra, pestañas y progreso). Se pausa al ocultarse la pestaña.
  El `DrawingArea` va sin doble búfer ni fondo (si no, GTK tapa el overlay Xv) y la actividad
  desactiva el botón de esquina de Sugar (`enable_fullscreen_mode = False`).
  **MP3:** el sistema no trae decodificador; con `gstreamer1-libav` (RPM Fusion, ver `DOC/plugins.md`)
  el plugin lo ofrece con un clic (se detecta por el fichero `libgstlibav.so`/`mad`/`mpg123`, sin cargar
  GStreamer). libav deja sus decodificadores de MP3 con rango 0: el plugin sube `avdec_mp3` (coma fija).
  **Módulos** (`.mod`/`.xm`/`.it`/`.s3m`/`.stm`): con `gstreamer1-plugins-bad-free-extras` (elemento `modplug`, rango
  primario, sin ajuste de rango) el plugin los ofrece con un clic; se detecta por `libgstmodplug.so`.
  Audio (ALSA directo) y Xv son de un solo uso: al reproducir se sueltan las demás pestañas
  multimedia y una pestaña quieta se suelta por inactividad (ver `DOC/plugins.md`). Solo audio: panel
  negro sin botones de modos.
  Medido en el XO: GStreamer cuesta ~4 MB al iniciar y ~5 MB al reproducir; al cerrar solo se
  recuperan ~0,4 MB, así que no se descarga por inactividad (no se puede descargar un módulo C).
- **Abrir con** lista todos los plugins (forzar uno en un archivo no reconocido); un
  plugin forzado que no puede con el archivo lo dice en su propia pestaña o con un aviso.
- **Build/Run del editor:** botones solo si hay `build.sh`/`run.sh` en la carpeta del
  archivo; guarda antes, ejecuta con `bash -l` + `sh` en un grupo de procesos propio y
  *Parar* mata el grupo entero. Nunca se ejecuta nada sin pulsar el botón. Al cerrar
  la pestaña o la actividad se paran los scripts en marcha (`scriptrunner.stop_all`,
  registrado con `atexit`: TERM y, a 1 s, KILL).
- **Barra principal contextual:** la zona tras el separador la pone la pestaña visible:
  carpetas → carpeta nueva/archivo nuevo; plugins → su `toolbar_actions()` (editor:
  «Guardar todo»). Los botones se crean al ver la pestaña y se quitan al cerrarla.
- **Editor:** esquema propio `plugins/text/styles/archivos.xml` (copia de «classic» con
  columna de números en gris claro; GtkSourceView 3.6 no admite `parent-scheme`) y
  `set_left_margin(8)`. El relleno del renderizador de números no se puede cambiar.
- **Navegación:** la casita (antes de «subir») y Alt+Inicio van a `~`. El botón **Ir a** de la
  barra principal abre un menú con las unidades montadas en `/run/media` o `/media`
  (`places.py`, Gio solo al abrir el menú, sin vigilar nada; el color de cada unidad es el que le da el Diario de Sugar: hash SHA-1 del UUID o del nombre de la carpeta, `places.mount_color`), un separador y las carpetas favoritas. La tarjeta SD
  de `/mnt/sd` (fstab) no la monta Sugar y no sale.
- **Favoritas** (`favorites.py`, sin GTK): `~/.config/archivos/favorites.json`, de la
  aplicación y no del Diario (el Diario es por instancia: «Empezar nuevo» partiría sin
  favoritas; se relee cada vez, así las instancias se ven entre sí). Las que ya no existen
  salen desactivadas (puede ser un USB sin enchufar) y se quitan a mano.
- **Propiedades** (`fileprops.py` sin GTK + `propsdialog.py`): nada se aplica hasta
  «Aceptar». chmod solo propietario/root, conserva setuid/setgid/sticky; el propietario solo
  con root; el grupo, uno de los propios. Linux no guarda fecha de creación en este
  núcleo: se enseña «No consta» y el cambio de estado (ctime).
- **Actividades de Sugar como visores** (`sugaractivities.py`): un clic abre un PDF en
  Read, etc., con `activityfactory.create_with_uri` (sin copiar al Diario). Solo si no
  hay plugin ni aplicación de Gio y una única actividad declara el tipo (ignorando los
  genéricos `text/plain`, `application/zip`...); todas, en «Abrir con». `uri` =
  `file://` + ruta sin codificar. Detalle en `DOC/arquitectura.md`.
- **Avisos de Sugar:** `add_alert` **encola** y solo muestra el primero. Por eso
  `show_message` sustituye al aviso informativo anterior y `ask` descarta los
  pendientes: una pregunta nunca queda tapada por un error viejo.
- **Barra de estado:** «X carpetas y Y MB en Z archivos» (`FileView.status_text`).
- **Clic principal abre, clic secundario abre el menú.** Ctrl/Mayús solo
  seleccionan. Tras navegar se ignoran clics 0,45 s para que el segundo clic de
  un doble clic no abra algo de la carpeta nueva.
- **Nunca sobrescribe** al copiar o mover (usa `nombre (2)`). Borrar es directo,
  con confirmación; no hay papelera (ocuparía la flash interna).
- **Portapapeles interno** (no el del sistema): se comparte entre pestañas.
- Estado en el Diario: lista de pestañas y si se ven los ocultos (JSON).

## Estructura

| Fichero | Contenido |
|---|---|
| `archivos.py` | La actividad: barra de herramientas, pestañas, portapapeles, operaciones, Diario |
| `fileview.py` | Contenido de una pestaña (lista, ratón, menú, teclado, renombrar, carga) |
| `fileops.py` | Lógica de archivos **sin GTK** (listar, copiar, mover, borrar, renombrar) |
| `archives.py` | Crear y extraer `.tar`/`.tar.gz` (sin GTK, con comprobaciones de seguridad) |
| `ops.py` | Cola de operaciones largas en un hilo, con progreso y cancelación |
| `tabs.py` | `Gtk.Notebook` y etiqueta de pestaña con botón de cerrar |
| `places.py` | Unidades extraíbles montadas (para el botón USB) |
| `sugaractivities.py` | Actividades de Sugar instaladas que abren un tipo de archivo (sin GTK) |
| `favorites.py`, `fileprops.py`, `propsdialog.py` | Carpetas favoritas, datos/permisos de un archivo (sin GTK) y su diálogo |
| `i18n.py` | Textos es/en (la clave es el texto en inglés) |
| `pluginapi.py`, `pluginmgr.py`, `pluginui.py` | Contrato (sin GTK), gestor (sin GTK) y base gráfica de los plugins |
| `plugins/image/`, `plugins/text/`, `plugins/video/` | Visor de imágenes, editor de texto y reproductor de vídeo (cada uno con su `po/`) |
| `i18n.py`, `po/`, `tools/translate.py` | Traducciones con gettext (`.po` leídos directamente) y sus herramientas |
| `debugsrv.py`, `tools/dbg.py` | Servidor/cliente de depuración (solo con `ARCHIVOS_DEBUG=1`) |
| `tests/` | `unittest` de `fileops` (sin pantalla) |

Detalle en `DOC/arquitectura.md`, `DOC/plugins.md`, `DOC/i18n.md`,
`DOC/depuracion.md` y `DOC/rendimiento.md`.

## Cómo probar

- Lógica: `python -m unittest discover -s tests -v` (en el XO; no hay `gi` en
  Windows).
- Interfaz: lanzar con `ARCHIVOS_DEBUG=1` y usar `tools/dbg.py` (`eval`, `shot`,
  `tree`). Ver `DOC/depuracion.md`.

## Convenciones

- Saltos de línea del repositorio: CRLF. **Al copiar al XO hay que pasar a LF**
  (`activity.info`, scripts y fuentes); un `\r` rompe los scripts de Linux.
- Rutas y nombres son `str` (bytes UTF-8) en todo el código.
- **PowerShell 5.1 corrompe los acentos** si se usa `Get-Content`/`Set-Content` con
  ficheros UTF-8 sin BOM (lee como ANSI y reescribe con BOM). Editar con la
  herramienta de edición o con `ReadAllBytes`/`WriteAllBytes`.
- Los `.pot`/`.po` los normaliza `tools/translate.py` en el XO (no hay Python en el
  PC): traerlos de vuelta al repositorio después de ejecutarlo.
- Las pruebas de interfaz se hacen en un XO real; las capturas las toma la
  propia actividad (solo sus ventanas), nunca la pantalla completa.

## Estado

Funcional y probado: navegar, abrir, menú contextual (archivo, carpeta y fondo),
copiar/cortar/pegar/mover (también entre sistemas de ficheros, simulado en las
pruebas), renombrar, borrar, carpeta nueva, ocultos, pestañas, recuperación del
Diario, progreso y cancelación.

Versión **0.9** (`activity/activity.info`, `CHANGELOG.md`). `.xo` con `tools/package.ps1`
(zip con LF, sin tests/tools/DOC; `setup.py dist_xo` usa `git ls-files`, y la imagen
OLPC no trae git). Hoja de ruta y la idea del conector GVfs/WebDAV: `DOC/roadmap.md`.

Pendiente o por decidir: arrastrar y soltar, ordenar por columna, retroceder y
avanzar en el historial, ver si la shell de Sugar detecta la actividad sin
reiniciar la sesión, traducciones de Sugar (`po/`), instalador de una línea.
