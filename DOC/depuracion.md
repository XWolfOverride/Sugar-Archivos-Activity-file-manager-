# Depuración

Una actividad Sugar solo se ve dentro de la sesión gráfica. Para probarla desde
una conexión SSH (o desde un agente) sin tocar nada del sistema, la propia
actividad incluye un pequeño servidor de depuración.

## Activarlo

Solo existe si el entorno trae `ARCHIVOS_DEBUG=1`. Escucha en un socket Unix
(`/tmp/archivos-debug.sock`, permisos 600; se cambia con `ARCHIVOS_DEBUG_SOCK`).
Sin esa variable no se arranca nada.

## Lanzar la actividad desde SSH

La actividad necesita las variables de la sesión gráfica (`DISPLAY`,
`XAUTHORITY`, `DBUS_SESSION_BUS_ADDRESS`, `XDG_RUNTIME_DIR`). Se toman del
proceso de la shell de Sugar (`python2 -m jarabe.main`), **no** de otra
conexión SSH, cuyo bus puede estar caducado. No hay que copiar las variables
`SUGAR_*` de otra actividad.

```
ARCHIVOS_DEBUG=1 setsid nohup sugar-activity ~/Activities/Archivos.activity \
    archivos.ArchivosActivity > /tmp/archivos.log 2>&1 < /dev/null &
```

### Cuidado con el Diario

`Activity.__init__` crea una entrada **nueva** en el Diario cada vez que se
arranca sin `-o` (objeto del Diario). Lanzar la actividad decenas de veces al
probar llena el Diario de entradas «Actividad Archivos». Para probar sin ensuciar
hay que **reanudar** una entrada existente, igual que hace Sugar al pulsar el
icono con `resume-activity`:

```
sugar-activity -b org.xwolf.Archivos -a <activity_id> -o <uid de la entrada> \
    ~/Activities/Archivos.activity archivos.ArchivosActivity
```

El `uid` y el `activity_id` salen del propio Diario (`sugar3.datastore.datastore.find`
con `{'activity': 'org.xwolf.Archivos'}`; el `uid` es `entrada.object_id`). Al
reanudar y cerrar, el número de entradas no cambia.

## Cliente

```
python tools/dbg.py ping
python tools/dbg.py eval "view.path"
python tools/dbg.py eval "click_row(view, 'carpeta', 1)"
python tools/dbg.py shot /tmp/capturas
python tools/dbg.py tree
```

- `eval`: ejecuta Python dentro de la actividad. Devuelve el valor si es una
  expresión; las sentencias no devuelven nada. Variables disponibles: `app` (la
  actividad), `view` (la pestaña actual si es una carpeta), `tab` (la pestaña
  actual, sea de carpeta o de plugin), `plugins` (el gestor de plugins), `Gtk`,
  `Gdk`, `Gio`, `GLib`, `os`,
  `click_row(view, nombre, botón, estado)` y `FakeEvent`.
- `shot`: guarda un PNG **de cada ventana de la actividad** (la principal y los
  menús desplegados). No captura el resto de la pantalla.
- `tree`: árbol de widgets con tamaños, para localizar elementos.
- Las órdenes largas bloquean la interfaz mientras se ejecutan; para ellas,
  `ARCHIVOS_DEBUG_TIMEOUT=180` alarga la espera del cliente.

## Trucos

- `view.load_log` guarda `(ruta, filas, segundos totales, segundos del hilo)`
  de las últimas cargas; sirve para medir.
- No sondear con un cliente Python cada segundo mientras se mide: arrancar el
  intérprete en un equipo de un solo núcleo falsea los tiempos. Mejor lanzar la
  acción, esperar y leer el registro.
- Un `pkill -f` con el nombre de la actividad puede matar a la propia shell que
  lo lanza (su línea de órdenes lo contiene). Anclar el patrón al principio del
  proceso: `'^python2? /usr/bin/sugar-activity .*archivos'`.
- La consola de Sugar avisa de errores del tema (`gtk-widgets.css ... pseudo-class`):
  son del tema y no afectan a la actividad.
