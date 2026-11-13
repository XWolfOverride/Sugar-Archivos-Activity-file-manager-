# Hoja de ruta

Estado: **0.9** (primera versión publicable). Lo que viene, por orden aproximado.

## Redes y servidores remotos (GVfs)

Archivos trabaja con rutas normales (`os.*`) y no entiende esquemas como
`sftp://` o `smb://` (Nautilus sí, a través de GVfs). Idea: una acción
**«Conectar a servidor»** que monte la dirección con Gio
(`Gio.File.mount_enclosing_volume`) y abra la pestaña en la ruta FUSE que expone
`gvfs-fuse` (`/run/user/<uid>/gvfs/...`), de modo que el resto de la actividad
sigue funcionando con rutas normales.

- **Ya disponible en OLPC OS 13.2, sin instalar nada:** `sftp`, `ssh`, `dav`,
  `davs`, `ftp`, `http`, `network` (descubrimiento con Avahi, ya instalado).
- **`smb://` no está:** hace falta el paquete `gvfs-smb`, que en el repositorio
  exige exactamente `gvfs` 1.14.2-4 (la imagen trae la -5, hay que bajar de
  versión) y arrastra unos 19 MB de bibliotecas de Samba. El núcleo del XO no
  tiene CIFS, así que `mount.cifs` no es alternativa. Para un NAS es más sencillo
  **exponerlo por WebDAV** (`davs://`).
- **Precauciones:** FUSE es lento en un equipo de un solo núcleo y las carpetas
  montadas no avisan de cambios (hay que actualizar a mano, F5); los montajes
  pueden tardar o fallar, así que la operación no debe bloquear la interfaz.

## Pendiente de pulir

- Arrastrar y soltar entre pestañas.
- Ordenar por columna.
- Retroceder y avanzar en el historial de una pestaña.
- Traducciones de Sugar (`po/`) para más idiomas (hoy es y en).
- Comprobar que la shell de Sugar detecta la actividad sin reiniciar la sesión.
- Más plugins (ver [plugins.md](plugins.md)): por ejemplo visor de PDF o
  reproductor de audio.
