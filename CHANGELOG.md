# Cambios

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
