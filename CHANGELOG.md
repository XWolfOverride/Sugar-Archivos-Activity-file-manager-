# Cambios

## Sin publicar

- **Ir a:** el botón de unidades pasa a la barra principal (antes de «Carpeta nueva») y
  se convierte en un menú con las unidades montadas, un separador y las carpetas
  favoritas. Sin unidades ni favoritas, una sola entrada desactivada lo dice; el separador solo
  sale si hay de las dos. Cada unidad lleva el color que le da el Diario de Sugar.
- **Propiedades** de archivos y carpetas (clic secundario o Alt+Intro; sin selección,
  las de la carpeta actual): tipo MIME, tamaño o contenido, fechas, enlace; cambio de
  permisos y de grupo (y de propietario, solo con root); en carpetas, la estrella que
  la añade a favoritas.
- Las favoritas son de la aplicación (`~/.config/archivos/favorites.json`), no del
  Diario: las ven todas las instancias.
- **Reproductor multimedia** (plugin, antes «de vídeo»): Ogg/Theora y WebM/VP8 con audio Vorbis, con GStreamer
  (`playbin` + `xvimagesink`). Modos normal, 1:1 y pantalla completa (sin barras; Esc vuelve al modo normal).
  Pausa automática al pasar a otra pestaña.
  También reproduce MP3 y módulos de tracker (`.mod`, `.xm`, `.it`, `.s3m`) si hay un decodificador instalado
  (ver `DOC/plugins.md`).

## 0.9

Primera versión publicable.

- Explorador con pestañas: lista de archivos por pestaña, clic principal abre,
  clic secundario abre el menú, barra de estado con totales, ocultos (Ctrl+H).
- Copiar, cortar, pegar, mover, renombrar, borrar, carpeta y archivo nuevos, con
  progreso y cancelación; nunca sobrescribe.
- Crear y extraer `.tar` y `.tar.gz`, con comprobaciones de seguridad y detección
  de archivos truncados.
- Plugins: visor de imágenes y editor de texto (resaltado, buscar y reemplazar,
  guardado atómico, «Guardar todo», Build/Run con `build.sh`/`run.sh`). La barra
  principal cambia según la pestaña. «Abrir con» ofrece todos los plugins.
- Abre archivos con **otras actividades de Sugar** (por ejemplo PDF, DjVu o EPUB en
  Read) sin copiarlos al Diario. Un clic basta si no hay plugin ni aplicación de
  escritorio y una sola actividad declara el tipo; el resto, en «Abrir con».
- Textos en español e inglés (gettext), estado de las pestañas en el Diario.
- Al cerrar la actividad se paran los programas lanzados con Build/Run.
