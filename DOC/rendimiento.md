# Rendimiento: lo que se midió

Máquina de referencia: un solo núcleo a unos 430 MHz, 222 MB de RAM y memoria
flash JFFS2. Python 2.7 con PyGObject 3.4. Los tiempos son de esa máquina.

## Listar una carpeta

| Enfoque | 1 500 entradas |
|---|---|
| `Gio` con `standard::content-type` e icono por archivo | ~2,7 s (más de 18 s dentro de la actividad) |
| `Gio` con `fast-content-type` y sin icono por archivo | ~0,9 s |
| `os.listdir` + `os.lstat` + tipo por extensión en caché | ~0,6-1,0 s |

Cada llamada de introspección de Gio cuesta unos 0,2 ms. Con 8-10 por archivo se
come el tiempo. Por eso `list_dir` usa `os` (C puro) y llama a Gio **una vez por
tipo**, no por archivo.

`standard::content-type` (el normal) **lee el contenido** de cada archivo para
adivinar el tipo; `fast-content-type` solo mira el nombre.

## Rellenar la lista

`Gtk.ListStore.append([...])` cuesta 2,5-3 ms por fila en PyGObject 3.4, aunque
el modelo no esté en ninguna vista. `insert_with_valuesv(-1, columnas, valores)`
cuesta ~0,4 ms (8 veces menos). Además se desconecta el modelo del `TreeView`
mientras se rellena y se hace en trozos de 400 filas desde el bucle de GTK.

`Gtk.ListStore.clear()` con 1 500 filas son ~0,08 s: no es un problema.

Resultado: carpetas normales en menos de 1 s; las de 1 500 entradas, en 2-3 s.

## Hilos y PyGObject 3.4

PyGObject 3.4 carga los atributos de `gi` de forma perezosa y no es seguro hacerlo
por primera vez desde otro hilo: `Gio.FileType.DIRECTORY` falló con
`AttributeError` solo dentro del hilo. `fileops._warm_up()` toca esos atributos
al importar el módulo, desde el hilo principal.

## GTK 3.6

- `Gtk.Notebook` reparte a las pestañas su ancho **mínimo**, no el natural. Un
  `Gtk.Label` con elipsis sin `width_chars` se reduce a «…»; la etiqueta de la
  pestaña ajusta `width_chars` al título (entre 6 y 26).
- Para que las pestañas llenen el ancho a partes iguales, todas deben tener el
  mismo ancho mínimo y la propiedad hija `tab-expand`; con anchos mínimos
  distintos (por ejemplo, según el título) el reparto sale desigual. Con una
  sola pestaña se desactiva `tab-expand` y se fija el ancho de la etiqueta a
  `ancho/2 - 56` (relleno del tema, hueco y botón de cerrar), calibrado en
  pantalla.
- `Gtk.Notebook.set_action_widget(widget, Gtk.PackType.END)` pone el botón «+»
  en el extremo derecho de la barra de pestañas.
- No existe `set_activate_on_single_click` (llegó en 3.8): el clic principal se
  implementa con `button-release-event`.
- El tema de Sugar no trae los iconos de tipos de archivo (carpeta, texto,
  imagen...): se piden al tema GNOME, con una caché de `Pixbuf` por icono. Para
  las carpetas hay que pedir `folder`, porque Gio pide `inode-directory`, que
  ningún tema trae.

## Archivos comprimidos

16 MB (6 MB aleatorios, 10 MB de texto, 400 archivos pequeños), en la tarjeta SD:

| Operación | Tiempo | Velocidad de datos |
|---|---|---|
| crear `.tar` | 3,4 s | 4,8 MB/s |
| crear `.tar.gz` (nivel 6) | 14,6 s | 1,1 MB/s |
| extraer `.tar` | 9,3 s | 1,7 MB/s |
| extraer `.tar.gz` | 6,7 s | 2,4 MB/s |

El nivel de gzip casi no influye (niveles 1, 3 y 6: 12,6, 9,5 y 11,8 s, mismo
tamaño): el límite lo pone la escritura en la tarjeta (~2 MB/s). Se deja el 6.
`/tmp` es RAM (50 MB): no usarlo para probar con datos grandes.

## Imágenes (decodificación con GdkPixbuf)

| Imagen | Entera | Reducida a 320 px | Reducida a 48 px |
|---|---|---|---|
| 640×480 JPEG | 0,27 s | 0,09 s | 0,05 s |
| 2048×1536 JPEG (3 MP) | 1,4 s | 0,9 s | 0,5 s |
| 4000×3000 JPEG (12 MP) | **8,5 s, 34 MB de RAM** | 2,1 s | 2,4 s |
| 1600×1200 PNG | 0,6 s | 0,7 s | 0,8 s |

`new_from_file_at_scale` es mucho más rápido con JPEG porque el decodificador
escala al leer; con PNG no ayuda. Miniaturas automáticas de una carpeta de 14
fotos de 12 MP serían ~30 s de CPU (por eso, solo bajo demanda y con caché).
Formatos: jpeg, png, gif, svg, bmp, tiff, ico, xpm, pnm, tga, wbmp, xbm...

## Editor de texto (TextView y GtkSourceView 3)

GtkSourceView 3 está instalado (typelib `GtkSource-3.0`), no añade RAM al
importarlo, trae 100 lenguajes (Pascal, Python, C, shell, XML, JSON, ini,
Makefile...), deshacer/rehacer, números de línea y esquemas de color. Cargar
1 MB de texto tarda ~0,5 s y ocupa ~1,2 MB; 5 MB, ~2,5 s y ~5,4 MB. Activar el
resaltado cuesta 0,2-0,5 s (el coloreado es incremental). `import Gtk` ya son
~12 MB de RSS en un proceso nuevo.

## Memoria

Una instancia con tres pestañas ocupa unos 30-33 MB de RSS (Terminal: ~16 MB).
