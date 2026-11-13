# -*- coding: utf-8 -*-
"""Plugin «Text editor»: editor de texto plano en una pestaña.

Usa GtkSourceView 3 (ya instalado en OLPC OS 13.2): números de línea, resaltado
de sintaxis según el tipo de archivo (Pascal, Python, C, shell, XML...), deshacer
y rehacer, sangría automática. La búsqueda y el reemplazo son propios porque esta
versión no trae el buscador. Guarda de forma atómica, conserva la codificación y
los finales de línea del archivo y avisa si cambió en disco.
"""
import os

import gi
gi.require_version('GtkSource', '3.0')
from gi.repository import Gdk, GLib, Gtk, GtkSource, Pango  # noqa: E402

import fileops  # noqa: E402
import i18n  # noqa: E402
import pluginapi  # noqa: E402
import scriptrunner  # noqa: E402
import textio  # noqa: E402
from i18n import N_  # noqa: E402
from pluginui import PluginTab, icon_button  # noqa: E402

# Los atributos de gi se cargan de forma perezosa y no es seguro hacerlo por
# primera vez desde otro hilo (la salida de los scripts llega desde un hilo).
_idle_add = GLib.idle_add
_OUTPUT_LIMIT = 300000

_TEXT_TYPES = frozenset([
    'application/json', 'application/xml', 'application/javascript',
    'application/x-shellscript', 'application/x-perl', 'application/x-ruby',
    'application/x-yaml', 'application/sql', 'application/x-desktop',
    'application/x-awk', 'application/x-php', 'image/svg+xml'])
_TEXT_EXTENSIONS = frozenset([
    '.txt', '.md', '.rst', '.log', '.ini', '.cfg', '.conf', '.cnf', '.csv',
    '.json', '.xml', '.html', '.htm', '.css', '.js', '.sh', '.bash', '.py',
    '.pas', '.pp', '.inc', '.lpr', '.dpr', '.lfm', '.c', '.h', '.cpp', '.hpp',
    '.cs', '.java', '.rb', '.pl', '.php', '.sql', '.tex', '.yml', '.yaml',
    '.toml', '.bat', '.cmd', '.mk', '.po', '.pot', '.desktop', '.info',
    '.svg', '.diff', '.patch', '.srt'])
_TEXT_NAMES = frozenset(['makefile', 'readme', 'license', 'copying',
                         'changelog', 'authors', 'news', 'todo', 'install'])
_MIN_FONT, _MAX_FONT, _DEFAULT_FONT = 6, 24, 9


class Plugin(pluginapi.Plugin):
    id = 'text'
    name = N_('Text editor')

    def handles(self, path, content_type):
        name = os.path.basename(path).lower()
        if (content_type.startswith('text/') or content_type in _TEXT_TYPES
                or os.path.splitext(name)[1] in _TEXT_EXTENSIONS
                or name in _TEXT_NAMES):
            return 100
        return 10                    # cualquier otro: solo «Abrir con»

    def open_tab(self, path):
        return EditorTab(self.host, self, path)

    def describe(self, error):
        """Texto (traducido) de un TextError."""
        tr = self.tr
        if error.code == 'too-big':
            return tr('The file is too big for the editor (%s)') % \
                i18n.decimal(fileops.human_size(int(error.detail)))
        if error.code == 'binary':
            return tr('This looks like a binary file, not text')
        return error.detail or error.code


class EditorTab(PluginTab):

    def __init__(self, host, plugin, path):
        PluginTab.__init__(self, host, plugin, path)
        try:
            self._doc = textio.read_document(path)
        except textio.TextError as exc:
            raise RuntimeError(plugin.describe(exc))
        self._font_size = _DEFAULT_FONT
        self._force_overwrite = False
        self._language = None
        self._script = None             # ScriptProcess en marcha (build/run)
        self._build()
        self._load_text()

    # ------------------------------------------------------------------
    # Interfaz
    # ------------------------------------------------------------------

    def _build(self):
        tr = self.plugin.tr
        bar = Gtk.EventBox()
        bar.override_background_color(Gtk.StateFlags.NORMAL,
                                      Gdk.RGBA(0.16, 0.16, 0.16, 1))
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_border_width(4)
        self._save_button = icon_button('archivos-save', tr('Save'),
                                        lambda _b: self.save())
        self._undo_button = icon_button('edit-undo', tr('Undo'),
                                        lambda _b: self._buffer.undo())
        self._redo_button = icon_button('edit-redo', tr('Redo'),
                                        lambda _b: self._buffer.redo())
        for button in (self._save_button, self._undo_button,
                       self._redo_button):
            row.pack_start(button, False, False, 0)
        row.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL),
                       False, False, 6)
        row.pack_start(icon_button('archivos-find', tr('Find and replace'),
                                   lambda _b: self._show_find()),
                       False, False, 0)
        self._wrap_button = icon_button('archivos-wrap', tr('Wrap lines'),
                                        self._on_wrap, toggle=True)
        row.pack_start(self._wrap_button, False, False, 0)
        row.pack_start(icon_button('list-remove', tr('Smaller text'),
                                   lambda _b: self._zoom(-1)),
                       False, False, 0)
        row.pack_start(icon_button('list-add', tr('Larger text'),
                                   lambda _b: self._zoom(1)),
                       False, False, 0)
        # Build / Run / Stop: solo se ven si junto al archivo hay build.sh o
        # run.sh (se comprueba al abrir y cada vez que la pestaña se muestra).
        self._script_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                   spacing=6)
        self._script_box.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.VERTICAL),
            False, False, 6)
        self._build_button = icon_button(
            'archivos-build', tr('Build (build.sh)'),
            lambda _b: self._start_script('build'))
        self._run_button = icon_button(
            'archivos-run', tr('Run (run.sh)'),
            lambda _b: self._start_script('run'))
        self._stop_button = icon_button(
            'archivos-stop', tr('Stop'), lambda _b: self._stop_script())
        for button in (self._build_button, self._run_button,
                       self._stop_button):
            self._script_box.pack_start(button, False, False, 0)
        row.pack_start(self._script_box, False, False, 0)
        bar.add(row)
        self.pack_start(bar, False, False, 0)

        self._buffer = GtkSource.Buffer()
        self._view = GtkSource.View.new_with_buffer(self._buffer)
        self._view.set_show_line_numbers(True)
        self._view.set_highlight_current_line(True)
        self._view.set_auto_indent(True)
        self._view.set_tab_width(4)
        self._view.set_indent_width(4)
        self._view.set_smart_home_end(GtkSource.SmartHomeEndType.BEFORE)
        # Esquema propio (plugins/text/styles): como «classic», pero con la
        # columna de números sobre gris claro para separarla del texto.
        manager = GtkSource.StyleSchemeManager.get_default()
        styles = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'styles')
        if styles not in manager.get_search_path():
            manager.append_search_path(styles)
        scheme = manager.get_scheme('archivos') or manager.get_scheme('classic')
        self._view.set_left_margin(8)          # aire entre los números y el texto
        if scheme is not None:
            self._buffer.set_style_scheme(scheme)
        self._apply_font()
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self._view)
        self.pack_start(scroll, True, True, 0)

        # panel con la salida de build.sh / run.sh (oculto hasta que se use)
        self._output = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_border_width(4)
        title = Gtk.Label()
        title.set_markup('<b>%s</b>' % GLib.markup_escape_text(tr('Output')))
        title.set_alignment(0, 0.5)
        header.pack_start(title, True, True, 4)
        close = Gtk.Button(label=tr('Close'))
        close.connect('clicked', lambda _b: self._output.hide())
        header.pack_start(close, False, False, 0)
        self._output.pack_start(header, False, False, 0)
        self._out_buffer = Gtk.TextBuffer()
        self._out_view = Gtk.TextView.new_with_buffer(self._out_buffer)
        self._out_view.set_editable(False)
        self._out_view.set_cursor_visible(False)
        self._out_view.set_wrap_mode(Gtk.WrapMode.CHAR)
        self._out_view.override_font(Pango.FontDescription('Monospace 8'))
        self._out_end = self._out_buffer.create_mark(
            None, self._out_buffer.get_end_iter(), False)
        out_scroll = Gtk.ScrolledWindow()
        out_scroll.set_policy(Gtk.PolicyType.AUTOMATIC,
                              Gtk.PolicyType.AUTOMATIC)
        out_scroll.set_size_request(-1, 200)
        out_scroll.add(self._out_view)
        self._output.pack_start(out_scroll, False, False, 0)
        self.pack_start(self._output, False, False, 0)

        # barra de buscar y reemplazar (oculta hasta Ctrl+F)
        self._find_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                 spacing=4)
        self._find_bar.set_border_width(4)
        self._find_entry = Gtk.Entry()
        self._find_entry.set_placeholder_text(tr('Find'))
        self._replace_entry = Gtk.Entry()
        self._replace_entry.set_placeholder_text(tr('Replace with'))
        self._find_bar.pack_start(self._find_entry, True, True, 0)
        self._find_bar.pack_start(self._replace_entry, True, True, 0)
        for label, callback in ((tr('Previous'), lambda _b: self._find(False)),
                                (tr('Next'), lambda _b: self._find(True)),
                                (tr('Replace'), lambda _b: self._replace()),
                                (tr('Replace all'),
                                 lambda _b: self._replace_all()),
                                (tr('Close'), lambda _b: self._hide_find())):
            button = Gtk.Button(label=label)
            button.connect('clicked', callback)
            self._find_bar.pack_start(button, False, False, 0)
        self.pack_start(self._find_bar, False, False, 0)

        status_box = Gtk.EventBox()
        status_box.override_background_color(Gtk.StateFlags.NORMAL,
                                             Gdk.RGBA(0.65, 0.65, 0.65, 1))
        self._status = Gtk.Label()
        self._status.set_alignment(0, 0.5)
        self._status.set_margin_left(6)
        status_box.add(self._status)
        self.pack_start(status_box, False, False, 2)

        self._view.connect('key-press-event', self._on_key)
        self._find_entry.connect('key-press-event', self._on_find_key)
        self._replace_entry.connect('key-press-event', self._on_find_key)
        self._find_entry.connect('activate', lambda _e: self._find(True))
        self._buffer.connect('modified-changed', self._on_modified)
        self._buffer.connect('notify::can-undo', self._update_buttons)
        self._buffer.connect('notify::can-redo', self._update_buttons)
        self._buffer.connect('notify::cursor-position', self._update_status)
        self.show_all()
        self._find_bar.hide()
        self._output.hide()
        self._update_scripts()

    def toolbar_actions(self):
        return [('archivos-save-all', self.plugin.tr('Save all'),
                 self.host.save_all)]

    def _apply_font(self):
        self._view.override_font(
            Pango.FontDescription('Monospace %d' % self._font_size))

    def _zoom(self, step):
        size = min(max(self._font_size + step, _MIN_FONT), _MAX_FONT)
        if size != self._font_size:
            self._font_size = size
            self._apply_font()

    def _on_wrap(self, button):
        self._view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR if button.get_active()
                                 else Gtk.WrapMode.NONE)

    # ------------------------------------------------------------------
    # Contenido
    # ------------------------------------------------------------------

    def _load_text(self):
        content_type = fileops.content_type_for(os.path.basename(self.path))
        manager = GtkSource.LanguageManager.get_default()
        self._language = manager.guess_language(self.path, content_type)
        if self._language is not None:
            self._buffer.set_language(self._language)
            self._buffer.set_highlight_syntax(True)
            # los Makefile exigen tabuladores; el resto, espacios
            self._view.set_insert_spaces_instead_of_tabs(
                self._language.get_id() != 'makefile')
        else:
            self._view.set_insert_spaces_instead_of_tabs(True)
        self._buffer.begin_not_undoable_action()
        self._buffer.set_text(self._doc.text)
        self._buffer.end_not_undoable_action()
        self._buffer.set_modified(False)
        self._buffer.place_cursor(self._buffer.get_start_iter())
        self._update_buttons()
        self._update_status()

    def _text(self):
        start, end = self._buffer.get_bounds()
        text = self._buffer.get_text(start, end, True)
        return text.decode('utf-8') if isinstance(text, bytes) else text

    def _update_buttons(self, *_args):
        self._undo_button.set_sensitive(self._buffer.can_undo())
        self._redo_button.set_sensitive(self._buffer.can_redo())
        self._save_button.set_sensitive(self._buffer.get_modified())

    def _on_modified(self, _buffer):
        self._update_buttons()
        self.title_changed()

    def _update_status(self, *_args):
        cursor = self._buffer.get_iter_at_mark(self._buffer.get_insert())
        tr = self.plugin.tr
        parts = [tr('Line %(line)d, column %(col)d') % {
            'line': cursor.get_line() + 1, 'col': cursor.get_line_offset() + 1},
            self._doc.encoding.upper(), self._doc.eol,
            self._language.get_name() if self._language else tr('Plain text')]
        if not os.access(self.path, os.W_OK):
            parts.append(tr('read only'))
        self._status.set_text('  ·  '.join(parts))

    # ------------------------------------------------------------------
    # Guardar
    # ------------------------------------------------------------------

    def save(self):
        tr = self.plugin.tr
        if not self._force_overwrite and textio.changed_on_disk(
                self.path, self._doc):
            self.host.ask(
                tr('The file changed on disk'),
                tr('Overwrite it with your version?'),
                [(Gtk.ResponseType.ACCEPT, tr('Overwrite'), 'document-save'),
                 (Gtk.ResponseType.CANCEL, tr('Cancel'), 'dialog-cancel')],
                self._overwrite_answer)
            return False
        return self._write()

    def _overwrite_answer(self, response):
        if response == Gtk.ResponseType.ACCEPT:
            self._force_overwrite = True
            self._write()

    def _write(self):
        tr = self.plugin.tr
        before = self._doc.encoding
        try:
            used = textio.save_document(self.path, self._text(), self._doc)
        except textio.TextError as exc:
            self.host.show_message(
                '%s: %s' % (tr('Could not save the file'), exc.detail),
                tr('Error'))
            return False
        self._force_overwrite = False
        self._buffer.set_modified(False)
        self._update_status()
        if used != before:
            self.host.show_message(
                tr('The file had characters that %s cannot store; it was '
                   'saved as UTF-8.') % before.upper(), tr('Saved'))
        return True

    # ------------------------------------------------------------------
    # Buscar y reemplazar
    # ------------------------------------------------------------------

    def _show_find(self):
        selection = self._buffer.get_selection_bounds()
        if selection:
            self._find_entry.set_text(self._buffer.get_text(
                selection[0], selection[1], False))
        self._find_bar.show_all()
        self._find_entry.grab_focus()

    def _hide_find(self):
        self._find_bar.hide()
        self._view.grab_focus()

    def _find(self, forward=True):
        needle = self._find_entry.get_text()
        if not needle:
            return False
        flags = Gtk.TextSearchFlags.CASE_INSENSITIVE
        buf = self._buffer
        bounds = buf.get_selection_bounds()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        if forward:
            start = bounds[1] if bounds else cursor
            found = (start.forward_search(needle, flags, None)
                     or buf.get_start_iter().forward_search(needle, flags,
                                                            None))
        else:
            start = bounds[0] if bounds else cursor
            found = (start.backward_search(needle, flags, None)
                     or buf.get_end_iter().backward_search(needle, flags,
                                                           None))
        if not found:
            self._status.set_text(self.plugin.tr('Not found'))
            return False
        buf.select_range(found[1], found[0])
        self._view.scroll_to_mark(buf.get_insert(), 0.1, False, 0, 0)
        return True

    def _replace(self):
        needle = self._find_entry.get_text()
        buf = self._buffer
        bounds = buf.get_selection_bounds()
        if bounds and buf.get_text(bounds[0], bounds[1], False).lower() == \
                needle.lower():
            buf.begin_user_action()
            buf.delete(bounds[0], bounds[1])
            buf.insert(buf.get_iter_at_mark(buf.get_insert()),
                       self._replace_entry.get_text())
            buf.end_user_action()
        self._find(True)

    def _replace_all(self):
        needle = self._find_entry.get_text()
        if not needle:
            return
        replacement = self._replace_entry.get_text()
        length = len(replacement.decode('utf-8')
                     if isinstance(replacement, bytes) else replacement)
        flags = Gtk.TextSearchFlags.CASE_INSENSITIVE
        buf = self._buffer
        count = 0
        buf.begin_user_action()
        position = buf.get_start_iter()
        while count < 100000:
            found = position.forward_search(needle, flags, None)
            if not found:
                break
            offset = found[0].get_offset()
            buf.delete(found[0], found[1])
            buf.insert(buf.get_iter_at_offset(offset), replacement)
            position = buf.get_iter_at_offset(offset + length)
            count += 1
        buf.end_user_action()
        self._status.set_text(self.plugin.ntr(
            '%d replacement', '%d replacements', count) % count)

    # ------------------------------------------------------------------
    # Teclado
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Build y Run (build.sh / run.sh junto al archivo)
    # ------------------------------------------------------------------

    def _update_scripts(self):
        scripts = scriptrunner.find_scripts(self.path)
        running = self._script is not None
        self._build_button.set_visible('build' in scripts)
        self._run_button.set_visible('run' in scripts)
        self._build_button.set_sensitive(not running)
        self._run_button.set_sensitive(not running)
        self._stop_button.set_visible(running)
        self._script_box.set_visible(bool(scripts) or running)

    def _append_output(self, text):
        buf = self._out_buffer
        buf.insert(buf.get_end_iter(), text)
        if buf.get_char_count() > _OUTPUT_LIMIT + 50000:
            start, end = buf.get_bounds()
            keep = scriptrunner.trim_output(
                buf.get_text(start, end, True).decode('utf-8'),
                _OUTPUT_LIMIT)
            buf.set_text(keep)
        buf.move_mark(self._out_end, buf.get_end_iter())
        self._out_view.scroll_mark_onscreen(self._out_end)
        return False

    def _start_script(self, kind):
        if self._script is not None:
            return
        script = scriptrunner.find_scripts(self.path).get(kind)
        if script is None:
            self._update_scripts()
            return
        if self.is_modified() and not self.save():
            return                      # primero se guarda; si no se puede, no se ejecuta
        self._out_buffer.set_text('')
        self._output.show_all()
        self._append_output(u'$ sh %s\n' % os.path.basename(script).decode(
            'utf-8', 'replace'))
        process = scriptrunner.ScriptProcess(
            script, lambda text: _idle_add(self._append_output, text),
            lambda code, error: _idle_add(self._script_done, process, code,
                                          error))
        self._script = process
        self._update_scripts()
        process.start()

    def _stop_script(self):
        if self._script is not None:
            self._script.stop()

    def _script_done(self, process, code, error):
        if process is not self._script:
            return False
        def uni(text):
            return text.decode('utf-8', 'replace') if isinstance(
                text, bytes) else text

        tr = self.plugin.tr
        if error is not None:
            text = u'%s: %s' % (uni(tr('Could not start the script')),
                                uni(error))
        elif process.was_stopped:
            text = uni(tr('Stopped'))
        elif code is not None and code < 0:
            text = uni(tr('Killed by signal %d')) % -code
        else:
            text = uni(tr('Finished (exit code %d)')) % code
        self._append_output(u'\n[%s]\n' % text)
        self._script = None
        self._update_scripts()
        return False

    def _on_key(self, _widget, event):
        name = Gdk.keyval_name(event.keyval) or ''
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        if ctrl and name in ('s', 'S'):
            self.save()
        elif ctrl and name in ('f', 'F'):
            self._show_find()
        elif ctrl and name in ('y', 'Y'):
            self._buffer.redo()
        elif ctrl and name in ('z', 'Z'):
            (self._buffer.redo if shift else self._buffer.undo)()
        elif ctrl and name in ('plus', 'equal', 'KP_Add'):
            self._zoom(1)
        elif ctrl and name in ('minus', 'KP_Subtract'):
            self._zoom(-1)
        elif name == 'F3':
            self._find(not shift)
        elif name == 'F5':
            self._start_script('run')
        elif name == 'F7':
            self._start_script('build')
        elif name == 'Escape' and self._find_bar.get_visible():
            self._hide_find()
        else:
            return False
        return True

    def _on_find_key(self, _widget, event):
        name = Gdk.keyval_name(event.keyval) or ''
        if name == 'Escape':
            self._hide_find()
            return True
        if name == 'F3':
            self._find(not event.state & Gdk.ModifierType.SHIFT_MASK)
            return True
        return False

    # ------------------------------------------------------------------
    # Contrato de PluginTab
    # ------------------------------------------------------------------

    def is_modified(self):
        return self._buffer.get_modified()

    def discard_changes(self):
        self._buffer.set_modified(False)

    def get_state(self):
        cursor = self._buffer.get_iter_at_mark(self._buffer.get_insert())
        return {'line': cursor.get_line(), 'col': cursor.get_line_offset(),
                'font': self._font_size,
                'wrap': self._wrap_button.get_active()}

    def restore_state(self, state):
        size = state.get('font')
        if isinstance(size, int):
            self._font_size = min(max(size, _MIN_FONT), _MAX_FONT)
            self._apply_font()
        if state.get('wrap'):
            self._wrap_button.set_active(True)
        line, col = state.get('line', 0), state.get('col', 0)
        if isinstance(line, int) and isinstance(col, int):
            GLib.idle_add(self._restore_cursor, line, col)

    def _restore_cursor(self, line, col):
        iterator = self._buffer.get_iter_at_line(
            min(line, max(self._buffer.get_line_count() - 1, 0)))
        iterator.forward_chars(min(col, iterator.get_chars_in_line() - 1)
                               if iterator.get_chars_in_line() > 0 else 0)
        self._buffer.place_cursor(iterator)
        self._view.scroll_to_mark(self._buffer.get_insert(), 0.1, False, 0, 0)
        return False

    def on_shown(self):
        self._update_scripts()          # puede haber aparecido/desaparecido un .sh
        self._view.grab_focus()

    def dispose(self):
        self._stop_script()             # no dejar un script huérfano
        self._buffer.set_language(None)
