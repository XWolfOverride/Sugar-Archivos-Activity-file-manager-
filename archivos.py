# -*- coding: utf-8 -*-
"""Archivos: un explorador de archivos sencillo, con pestañas, para Sugar."""
import json
import logging
import os

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk, GObject, Gtk  # noqa: E402

from sugar3.activity import activity  # noqa: E402
from sugar3.activity.widgets import (  # noqa: E402
    ActivityToolbarButton, StopButton)
from sugar3.graphics.alert import Alert, ConfirmationAlert  # noqa: E402
from sugar3.graphics.icon import Icon  # noqa: E402
from sugar3.graphics.toolbarbox import (  # noqa: E402
    ToolbarBox, ToolbarButton)
from sugar3.graphics.palettemenu import (  # noqa: E402
    PaletteMenuBox, PaletteMenuItem, PaletteMenuItemSeparator)
from sugar3.graphics.toolbutton import ToolButton  # noqa: E402

import archives  # noqa: E402
import favorites  # noqa: E402
import fileops  # noqa: E402
import ops  # noqa: E402
import pluginmgr  # noqa: E402
import places  # noqa: E402
import propsdialog  # noqa: E402
from fileview import FileView  # noqa: E402
from i18n import N_, tr  # noqa: E402
from tabs import TabNotebook  # noqa: E402

GObject.threads_init()
_LOG = logging.getLogger('archivos')

_ACTION_TEXT = {ops.COPY: N_('Copying'), ops.MOVE: N_('Moving'),
                ops.DELETE: N_('Deleting'), ops.TAR: N_('Compressing'),
                ops.TARGZ: N_('Compressing'), ops.EXTRACT: N_('Extracting')}


def _icon(*names):
    """Primer nombre de icono que exista en el tema; el último si ninguno."""
    theme = Gtk.IconTheme.get_default()
    for name in names:
        if theme.has_icon(name):
            return name
    return names[-1]


def _is_plugin_tab(tab):
    return getattr(tab, 'kind', 'folder') == 'plugin'


class PluginHost(object):
    """Lo que la actividad ofrece a los plugins (su única puerta de entrada)."""

    def __init__(self, app):
        self._app = app

    @property
    def data_dir(self):
        """Carpeta de datos de la actividad (los plugins pueden guardar ahí)."""
        root = os.environ.get('SUGAR_ACTIVITY_ROOT')
        return os.path.join(root, 'data') if root else None

    def show_message(self, text, title=None):
        self._app.show_message(text, title)

    def ask(self, title, message, buttons, callback):
        """Pregunta con botones [(Gtk.ResponseType, texto, icono)]."""
        return self._app.ask(title, message, buttons, callback)

    def tab_title_changed(self, tab):
        self._app.tab_title_changed(tab)

    def close_tab(self, tab):
        self._app.request_close(tab)

    def save_all(self):
        """Guarda todas las pestañas de plugin con cambios."""
        self._app.save_all()

    def open_path(self, path):
        """Abre ``path`` como si se hiciera clic en él (plugin o aplicación)."""
        self._app.open_path(path)

    def add_icon_path(self, path):
        Gtk.IconTheme.get_default().append_search_path(path)

    def set_fullscreen(self, on):
        """Pantalla completa: sin barra, pestañas ni progreso (la pide una pestaña)."""
        self._app.set_fullscreen(on)


class ArchivosActivity(activity.Activity):

    def __init__(self, handle):
        activity.Activity.__init__(self, handle)
        self.max_participants = 1
        # Sin el botón «salir de pantalla completa» de Sugar (en una esquina,
        # donde está el marco de Sugar): el plugin de vídeo sale con Esc.
        self.props.enable_fullscreen_mode = False
        self._fullscreen = False
        self._fs_progress = False
        self.show_hidden = False
        self._clip_mode = None
        self._clip_paths = []
        self._pending_state = None
        self._ask_alert = None
        self._message_alerts = []   # avisos informativos mostrados o en cola
        self._fv_buttons = []       # botones que solo valen en pestañas de carpeta
        self._runner = ops.OpRunner(self._on_op_start, self._on_op_progress,
                                    self._on_op_finish)
        host = PluginHost(self)
        self._plugins = pluginmgr.PluginManager(
            host, pluginmgr.default_directories(
                os.path.dirname(os.path.abspath(__file__)), host.data_dir))
        self._plugins.load_all()
        self._build_toolbar()
        self._build_canvas()
        self.connect('key-press-event', self._on_window_key)
        if self._pending_state is not None:
            self._apply_state(self._pending_state)
            self._pending_state = None
        if self._notebook.get_n_pages() == 0:
            self.open_tab(os.path.expanduser('~'))
        self._update_toolbar_state(self._notebook.current_view())
        if os.environ.get('ARCHIVOS_DEBUG'):
            import debugsrv
            self._debug = debugsrv.start(self)

    # ------------------------------------------------------------------
    # Interfaz
    # ------------------------------------------------------------------

    def _tool(self, icon_names, tooltip, callback, folder_only=True):
        button = ToolButton(_icon(*icon_names))
        button.set_tooltip(tooltip)
        button.connect('clicked', lambda _b: callback())
        if folder_only:
            self._fv_buttons.append(button)
        return button

    def _build_toolbar(self):
        box = ToolbarBox()
        bar = box.toolbar

        activity_button = ActivityToolbarButton(self)
        bar.insert(activity_button, 0)
        activity_button.show()

        # Los iconos de cortar, renombrar y nuevo archivo/carpeta son propios
        # (carpeta icons/): el tema de Sugar no los trae.
        edit_bar = Gtk.Toolbar()
        for icons, tip, callback in (
                (('edit-copy',), tr('Copy'), self._tb_copy),
                (('archivos-cut',), tr('Cut'), self._tb_cut),
                (('edit-paste',), tr('Paste'), self._tb_paste),
                (('archivos-rename',), tr('Rename'), self._tb_rename),
                (('edit-delete',), tr('Delete'), self._tb_delete)):
            button = self._tool(icons, tip, callback, folder_only=False)
            edit_bar.insert(button, -1)
            button.show()
        edit_button = ToolbarButton(page=edit_bar, icon_name='toolbar-edit')
        edit_bar.show()
        bar.insert(edit_button, -1)
        edit_button.show()
        self._fv_buttons.append(edit_button)

        for icons, tip, callback in (
                (('go-up',), tr('Up'), self._tb_up),
                (('view-refresh',), tr('Refresh'), self._tb_refresh)):
            button = self._tool(icons, tip, callback)
            bar.insert(button, -1)
            button.show()

        separator = Gtk.SeparatorToolItem()
        bar.insert(separator, -1)
        separator.show()

        # La gestión de pestañas ya no está aquí: se hace con el «+» y la «X»
        # de la barra de pestañas y con los atajos de teclado.
        # Esta zona de la barra la pone la pestaña visible: las carpetas ponen
        # carpeta nueva y archivo nuevo; cada plugin, lo que devuelva su
        # ``toolbar_actions()`` (ver ``_show_context_actions``).
        self._folder_actions = []
        goto = self._tool(('archivos-usb',), tr('Go to'), self._tb_goto)
        self._goto_button = goto
        goto.connect('enter-notify-event', lambda *_a: self._fill_goto())
        bar.insert(goto, -1)
        goto.show()
        self._folder_actions.append(goto)
        for icons, tip, callback in (
                (('archivos-new-folder',), tr('New folder'),
                 self._tb_new_folder),
                (('archivos-new-file',), tr('New file'),
                 self._tb_new_file)):
            button = self._tool(icons, tip, callback)
            bar.insert(button, -1)
            button.show()
            self._folder_actions.append(button)

        spacer = Gtk.SeparatorToolItem()
        spacer.props.draw = False
        spacer.set_expand(True)
        bar.insert(spacer, -1)
        spacer.show()
        self._toolbar = bar
        self._tb_spacer = spacer

        stop = StopButton(self)
        stop.props.accelerator = '<Ctrl><Shift>Q'
        bar.insert(stop, -1)
        stop.show()

        self.set_toolbar_box(box)
        self._toolbar_box = box
        box.show()

    def _build_canvas(self):
        self._notebook = TabNotebook(self._tb_new_tab)
        self._notebook.connect('switch-page', self._on_switch_page)

        self._progress_label = Gtk.Label()
        self._progress_label.set_alignment(0, 0.5)
        self._progress_bar = Gtk.ProgressBar()
        cancel = Gtk.Button(label=tr('Cancel'))
        cancel.connect('clicked', lambda _b: self._runner.cancel())
        self._progress_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                     spacing=8)
        self._progress_box.set_border_width(6)
        self._progress_box.pack_start(self._progress_label, False, False, 0)
        self._progress_box.pack_start(self._progress_bar, True, True, 0)
        self._progress_box.pack_start(cancel, False, False, 0)
        # Los hijos se muestran ya; el contenedor no (set_no_show_all) hasta que
        # haya una operación. Sin esto, show() solo mostraba el contenedor y la
        # etiqueta, la barra y el botón quedaban ocultos (barra de 12 px).
        for child in self._progress_box.get_children():
            child.show()
        self._progress_box.set_no_show_all(True)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(self._notebook, True, True, 0)
        root.pack_start(self._progress_box, False, False, 0)
        self.set_canvas(root)
        root.show_all()
        self._progress_box.hide()

    def set_fullscreen(self, on):
        if on == self._fullscreen:
            return
        self._fullscreen = on
        if on:
            self._fs_progress = self._progress_box.get_visible()
            self._toolbar_box.hide()
            self._notebook.set_show_tabs(False)
            self._progress_box.hide()
            self.fullscreen()
        else:
            self.unfullscreen()
            self._toolbar_box.show()
            self._notebook.set_show_tabs(True)
            if self._fs_progress:
                self._progress_box.show()

    def _update_toolbar_state(self, page):
        """Las acciones de archivos solo valen en pestañas de carpeta."""
        sensitive = page is not None and not _is_plugin_tab(page)
        for button in self._fv_buttons:
            button.set_sensitive(sensitive)
        self._show_context_actions(page)

    def _show_context_actions(self, page):
        """Muestra en la barra los botones de la pestaña visible y oculta el
        resto (los de carpeta, o los que puso otro plugin)."""
        is_plugin = page is not None and _is_plugin_tab(page)
        for button in self._folder_actions:
            button.set_visible(not is_plugin)
        for tab in self._notebook.views():
            if not _is_plugin_tab(tab):
                continue
            items = getattr(tab, '_toolbar_items', None)
            if items is None and tab is page:
                items = tab._toolbar_items = self._make_actions(tab)
            for button in items or ():
                button.set_visible(tab is page)

    def _make_actions(self, tab):
        items = []
        try:
            actions = tab.toolbar_actions()
        except Exception:
            actions = []
        for icon, tip, callback in actions:
            button = ToolButton(_icon(icon))
            button.set_tooltip(tip)
            button.connect('clicked', lambda _b, cb=callback: cb())
            self._toolbar.insert(
                button, self._toolbar.get_item_index(self._tb_spacer))
            items.append(button)
        return items

    def save_all(self):
        """Guarda todas las pestañas de plugin con cambios."""
        for tab in self._notebook.views():
            if _is_plugin_tab(tab) and tab.is_modified():
                tab.save()

    def _drop_actions(self, tab):
        for button in getattr(tab, '_toolbar_items', None) or ():
            self._toolbar.remove(button)
        tab._toolbar_items = None

    # ------------------------------------------------------------------
    # Pestañas
    # ------------------------------------------------------------------

    def current_tab(self):
        """La pestaña visible, sea de carpeta o de plugin."""
        return self._notebook.current_view()

    def current_view(self):
        """La pestaña visible si es una carpeta; None si es de un plugin."""
        tab = self.current_tab()
        return None if tab is None or _is_plugin_tab(tab) else tab

    def file_views(self):
        return [t for t in self._notebook.views() if not _is_plugin_tab(t)]

    def _folder_for_new_tab(self):
        tab = self.current_tab()
        if tab is None:
            return os.path.expanduser('~')
        if _is_plugin_tab(tab):
            return os.path.dirname(tab.path) or os.path.expanduser('~')
        return tab.path

    def open_tab(self, path, switch=True, append=False):
        view = FileView(self, path)
        position = -1 if append else self._notebook.get_current_page() + 1
        index = self._notebook.add_view(view, view.title(), self.request_close,
                                        position if position > 0 else -1)
        self._notebook.set_view_title(view, view.title(), view.path)
        if switch:
            self._notebook.set_current_page(index)
        self._activate_current()
        return view

    def _add_plugin_tab(self, tab, switch=True, append=False):
        position = -1 if append else self._notebook.get_current_page() + 1
        index = self._notebook.add_view(tab, tab.title(), self.request_close,
                                        position if position > 0 else -1)
        self._notebook.set_view_title(tab, tab.title(), tab.get_tooltip())
        if switch:
            self._notebook.set_current_page(index)
        self._activate_current()
        return tab

    def tab_title_changed(self, tab):
        self._notebook.set_view_title(tab, tab.title(), tab.get_tooltip())

    def request_close(self, view):
        """Cierra una pestaña, preguntando antes si un plugin tiene cambios."""
        if _is_plugin_tab(view) and view.is_modified():
            def answer(response):
                if response == Gtk.ResponseType.ACCEPT:
                    if view.save():
                        self.close_tab(view)
                elif response == Gtk.ResponseType.REJECT:
                    view.discard_changes()
                    self.close_tab(view)
            self.ask(tr('Save changes to "%s"?') % view.get_title(),
                     tr('Your changes will be lost if you do not save them.'),
                     self._save_buttons(), answer)
        else:
            self.close_tab(view)

    def close_tab(self, view):
        """Cierra una pestaña; si era la última, cierra la actividad."""
        if self._notebook.get_n_pages() <= 1:
            self.close()           # guarda el estado en el Diario y sale
            return
        view.set_active(False)
        if _is_plugin_tab(view):
            self._drop_actions(view)
        view.destroy_view()
        self._notebook.remove_view(view)
        self._activate_current()
        self._update_toolbar_state(self.current_tab())

    def view_path_changed(self, view):
        self._notebook.set_view_title(view, view.title(), view.path)

    def _on_switch_page(self, _notebook, page, _index):
        for view in self._notebook.views():
            view.set_active(view is page)
        self._update_toolbar_state(page)

    def _activate_current(self):
        current = self._notebook.current_view()
        for view in self._notebook.views():
            view.set_active(view is current)

    def set_show_hidden(self, flag):
        self.show_hidden = bool(flag)
        for view in self.file_views():
            view.show_hidden = self.show_hidden
            view.reload()

    def _on_window_key(self, _widget, event):
        name = Gdk.keyval_name(event.keyval) or ''
        if not event.state & Gdk.ModifierType.CONTROL_MASK:
            return False
        tab = self.current_tab()
        if name in ('t', 'T'):
            self.open_tab(self._folder_for_new_tab())
        elif name in ('w', 'W') and tab is not None:
            self.request_close(tab)
        elif name in ('h', 'H') and not _is_plugin_tab(tab):
            self.set_show_hidden(not self.show_hidden)
        elif name == 'Page_Up':
            self._tb_prev_tab()
        elif name == 'Page_Down':
            self._tb_next_tab()
        else:
            return False
        return True

    # ------------------------------------------------------------------
    # Abrir archivos: plugins (pestañas internas) o aplicación del sistema
    # ------------------------------------------------------------------

    def plugins_for(self, path, all_plugins=False):
        """Los plugins que saben abrir ``path`` (los mejores, primero).

        Con ``all_plugins`` se añaden detrás los que no lo reconocen, por orden
        de nombre: sirve para forzar un plugin en un archivo que no identifica.
        """
        content_type = fileops.content_type_for(os.path.basename(path))
        found = [p for _score, p in self._plugins.candidates(path,
                                                             content_type)]
        if all_plugins:
            others = [p for p in self._plugins.plugins() if p not in found]
            others.sort(key=lambda p: p.display_name())
            found += others
        return found

    def open_file(self, path, plugin=None):
        """Abre ``path`` en una pestaña del plugin (o del mejor que haya).

        Devuelve False si no hay ningún plugin: entonces quien llama usa la
        aplicación por defecto del sistema.
        """
        if plugin is None:
            content_type = fileops.content_type_for(os.path.basename(path))
            plugin = self._plugins.default_for(path, content_type)
        if plugin is None:
            return False
        for tab in self._notebook.views():
            if _is_plugin_tab(tab) and tab.plugin is plugin \
                    and tab.path == path:
                self._notebook.set_current_page(self._notebook.page_num(tab))
                return True
        try:
            tab = plugin.open_tab(path)
        except Exception as exc:
            _LOG.exception('el plugin %s no pudo abrir %s', plugin.id, path)
            self.show_message('%s: %s' % (tr('Could not open the file'), exc))
            return True
        if tab is not None:
            self._add_plugin_tab(tab)
        return True

    def open_path(self, path):
        """Como un clic: plugin si lo hay; si no, aplicación del sistema."""
        if os.path.isdir(path):
            self.open_tab(path)
        elif not self.open_file(path):
            view = self.current_view() or self.open_tab(
                os.path.dirname(path))
            view.open_file(path)

    # ------------------------------------------------------------------
    # Acciones de la barra de herramientas
    # ------------------------------------------------------------------

    def _tb_copy(self):
        view = self.current_view()
        if view:
            self.do_copy(view.selected_paths())

    def _tb_cut(self):
        view = self.current_view()
        if view:
            self.do_cut(view.selected_paths())

    def _tb_paste(self):
        view = self.current_view()
        if view:
            self.do_paste(view.path)

    def _tb_rename(self):
        view = self.current_view()
        if view:
            view.start_rename()

    def _tb_delete(self):
        view = self.current_view()
        if view:
            self.do_delete(view.selected_paths())

    def _tb_new_folder(self):
        view = self.current_view()
        if view:
            view.new_folder()

    def _tb_new_file(self):
        view = self.current_view()
        if view:
            view.new_file()

    def _fill_goto(self):
        """Rellena la paleta de «Ir a»: unidades extraíbles montadas, un
        separador (solo si hay de las dos cosas) y las carpetas favoritas.
        Se consulta todo al abrirla (nada se vigila)."""
        view = self.current_view()
        if view is None:
            return
        palette = self._goto_button.get_palette()
        box = PaletteMenuBox()
        drives = places.removable_mounts()
        stars = favorites.load()

        def go(path):
            palette.popdown(True)
            view.navigate(path)

        def add(text, icon, path, color=None, enabled=True):
            item = PaletteMenuItem(text, icon_name=icon, xo_color=color)
            item.set_tooltip_text(path)
            item.set_sensitive(enabled)
            if enabled:
                item.connect('activate', lambda _i, p=path: go(p))
            box.append_item(item)

        for name, path, uuid in drives:
            add(name, 'archivos-drive', path, places.mount_color(uuid, path))
        if drives and stars:
            box.append_item(PaletteMenuItemSeparator())
        missing = False
        for path in stars:
            exists = os.path.isdir(path)
            missing = missing or not exists
            add(os.path.basename(path) or '/', 'archivos-star-on', path,
                enabled=exists)
        if not drives and not stars:
            item = PaletteMenuItem(tr('No drives mounted'))
            item.set_sensitive(False)
            box.append_item(item)
        if missing:
            box.append_item(PaletteMenuItemSeparator())
            item = PaletteMenuItem(tr('Remove missing favorites'))
            item.connect('activate', lambda _i: (
                favorites.remove_missing(), palette.popdown(True)))
            box.append_item(item)
        box.show_all()
        palette.set_content(box)

    def _tb_goto(self):
        """Clic en «Ir a»: abre la paleta (un menú de Sugar, no un Gtk.Menu)."""
        if self.current_view() is None:
            return
        self._fill_goto()
        self._goto_button.get_palette().popup(immediate=True)

    def show_properties(self, path, view=None):
        """Diálogo de propiedades de ``path``."""
        try:
            dialog = propsdialog.PropertiesDialog(
                self, path, on_done=(view.reload if view is not None
                                     else None))
        except fileops.FileOpError as exc:
            self.show_message(str(exc))
            return
        dialog.show()

    def _tb_up(self):
        view = self.current_view()
        if view:
            view.go_up()

    def _tb_refresh(self):
        view = self.current_view()
        if view:
            view.reload()

    def _tb_new_tab(self):
        self.open_tab(self._folder_for_new_tab())

    def _tb_prev_tab(self):
        self._notebook.prev_page()

    def _tb_next_tab(self):
        self._notebook.next_page()

    # ------------------------------------------------------------------
    # Portapapeles interno y operaciones
    # ------------------------------------------------------------------

    def clipboard_has_items(self):
        return bool(self._clip_paths)

    def do_copy(self, paths):
        if paths:
            self._clip_mode, self._clip_paths = 'copy', list(paths)

    def do_cut(self, paths):
        if paths:
            self._clip_mode, self._clip_paths = 'cut', list(paths)

    def do_paste(self, dst_dir):
        if not self._clip_paths:
            return
        kind = ops.COPY if self._clip_mode == 'copy' else ops.MOVE
        sources = list(self._clip_paths)
        if kind == ops.MOVE:
            self._clip_mode, self._clip_paths = None, []
        self._runner.submit(kind, sources, dst_dir)

    def busy(self):
        """True mientras hay una operación larga en curso."""
        return self._runner.busy()

    def do_compress(self, paths, dst_dir, gz):
        """Crea un .tar (o .tar.gz) con ``paths`` en ``dst_dir``."""
        if paths:
            self._runner.submit(ops.TARGZ if gz else ops.TAR, paths, dst_dir)

    def do_extract(self, paths, dst_dir):
        """Extrae los .tar/.tar.gz de ``paths`` (cada uno a su carpeta)."""
        archives_only = [p for p in paths if archives.is_archive(p)]
        if archives_only:
            self._runner.submit(ops.EXTRACT, archives_only, dst_dir)

    def do_delete(self, paths):
        if not paths:
            return
        alert = ConfirmationAlert()
        if len(paths) == 1:
            alert.props.title = tr('Delete "%s"?') % os.path.basename(
                paths[0])
        else:
            alert.props.title = tr('Delete these items?')
        alert.props.msg = tr('This cannot be undone.')
        alert.connect('response', self._on_delete_response, list(paths))
        self.add_alert(alert)

    def _on_delete_response(self, alert, response, paths):
        self.remove_alert(alert)
        if response == Gtk.ResponseType.OK:
            self._runner.submit(ops.DELETE, paths)

    def _drop_message_alerts(self):
        for alert in list(self._message_alerts):
            self._message_alerts.remove(alert)
            self.remove_alert(alert)

    def show_message(self, text, title=None):
        # Sugar encola los avisos y solo enseña el primero: un mensaje nuevo
        # sustituye a los anteriores (que son informativos) en vez de quedar
        # detrás de uno viejo que nadie cerró.
        self._drop_message_alerts()
        alert = Alert()
        alert.props.title = title or tr('Error')
        alert.props.msg = text
        icon = Icon(icon_name=_icon('dialog-ok', 'dialog-cancel'))
        alert.add_button(Gtk.ResponseType.OK, tr('OK'), icon)
        icon.show()

        def dismissed(_alert, _response):
            if _alert in self._message_alerts:
                self._message_alerts.remove(_alert)
            self.remove_alert(_alert)

        alert.connect('response', dismissed)
        self._message_alerts.append(alert)
        self.add_alert(alert)

    def _save_buttons(self):
        return [(Gtk.ResponseType.ACCEPT, tr('Save'), 'document-save'),
                (Gtk.ResponseType.REJECT, tr('Discard'), 'edit-delete'),
                (Gtk.ResponseType.CANCEL, tr('Cancel'), 'dialog-cancel')]

    def ask(self, title, message, buttons, callback):
        """Aviso con varios botones; ``callback(respuesta)`` al pulsar uno."""
        # Una pregunta no puede quedar detrás de un mensaje informativo viejo.
        self._drop_message_alerts()
        alert = Alert()
        alert.props.title = title
        alert.props.msg = message
        for response, label, icon_name in buttons:
            icon = Icon(icon_name=_icon(icon_name, 'dialog-ok'))
            alert.add_button(response, label, icon)
            icon.show()

        def answered(_alert, response):
            self.remove_alert(_alert)
            if self._ask_alert is _alert:
                self._ask_alert = None
            callback(response)

        alert.connect('response', answered)
        self._ask_alert = alert
        self.add_alert(alert)
        return alert

    def can_close(self):
        """Antes de salir: avisa si algún plugin tiene cambios sin guardar."""
        modified = [t for t in self._notebook.views()
                    if _is_plugin_tab(t) and t.is_modified()]
        if not modified:
            return True
        if self._ask_alert is not None:
            return False            # ya se está preguntando

        def answer(response):
            if response == Gtk.ResponseType.ACCEPT:
                if all(t.save() for t in modified):
                    self.close()
            elif response == Gtk.ResponseType.REJECT:
                for tab in modified:
                    tab.discard_changes()
                self.close()

        self.ask(tr('Save changes before closing?'),
                 ', '.join(t.get_title() for t in modified),
                 self._save_buttons(), answer)
        return False

    def _on_op_start(self, kind, count):
        self._progress_label.set_text(tr(_ACTION_TEXT[kind]) + '…')
        self._progress_bar.set_fraction(0.0)
        self._progress_box.show()

    def _on_op_progress(self, kind, index, count, fraction, name):
        self._progress_label.set_text(
            '%s %s (%d/%d)' % (tr(_ACTION_TEXT[kind]), name, index + 1,
                               count))
        self._progress_bar.set_fraction((index + fraction) / float(count))

    def _on_op_finish(self, kind, results, errors, cancelled, dst_dir):
        self._progress_box.hide()
        if errors:
            self.show_message('\n'.join(errors[:5]))
        for view in self.file_views():
            view.reload(keep_scroll=True)

    # ------------------------------------------------------------------
    # Diario: recordar las pestañas abiertas
    # ------------------------------------------------------------------

    def write_file(self, file_path):
        pages = []
        for tab in self._notebook.views():
            if _is_plugin_tab(tab):
                pages.append({'type': 'plugin', 'plugin': tab.plugin.id,
                              'path': tab.path, 'state': tab.get_state()})
            else:
                pages.append({'type': 'folder', 'path': tab.path})
        data = {'pages': pages,
                'current': self._notebook.get_current_page(),
                'hidden': self.show_hidden}
        with open(file_path, 'w') as handle:
            json.dump(data, handle)
        self.metadata['mime_type'] = 'application/json'

    def read_file(self, file_path):
        try:
            with open(file_path) as handle:
                data = json.load(handle)
        except (IOError, ValueError):
            return
        if not hasattr(self, '_notebook'):
            self._pending_state = data
        else:
            self._apply_state(data)

    @staticmethod
    def _bytes(text):
        return text.encode('utf-8') if not isinstance(text, bytes) else text

    def _apply_state(self, data):
        # Formato antiguo: {'tabs': [ruta, ...]}; nuevo: {'pages': [{...}]}
        pages = data.get('pages')
        if pages is None:
            pages = [{'type': 'folder', 'path': p}
                     for p in data.get('tabs', [])]
        wanted = []
        for page in pages:
            path = self._bytes(page.get('path', ''))
            if page.get('type') == 'plugin':
                plugin = self._plugins.get(page.get('plugin', ''))
                if plugin is not None and os.path.isfile(path):
                    wanted.append((page, path, plugin))
            elif os.path.isdir(path):
                wanted.append((page, path, None))
        if not wanted:
            return
        self.show_hidden = bool(data.get('hidden'))
        for view in list(self._notebook.views()):
            view.destroy_view()
            self._notebook.remove_view(view)
        created = {}
        for page, path, plugin in wanted:
            try:
                if plugin is None:
                    tab = self.open_tab(path, switch=False, append=True)
                else:
                    tab = self._add_plugin_tab(
                        plugin.restore_tab(path, page.get('state') or {}),
                        switch=False, append=True)
            except Exception:
                _LOG.exception('no se pudo recuperar la pestaña %s', path)
                continue
            created[id(page)] = tab
        current = data.get('current', 0)
        if isinstance(current, int) and 0 <= current < len(pages):
            tab = created.get(id(pages[current]))
            if tab is not None:
                self._notebook.set_current_page(self._notebook.page_num(tab))
        self._activate_current()
        self._update_toolbar_state(self.current_tab())
