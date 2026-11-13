# -*- coding: utf-8 -*-
"""El contenido de una pestaña: una sola lista de archivos con su ruta.

Clic principal: abre (entra en la carpeta o abre el archivo con la aplicación
por defecto). Clic secundario: menú de opciones (abrir con, copiar, cortar,
pegar, renombrar, borrar, carpeta nueva...). Ctrl o Mayús con el clic principal
solo seleccionan.
"""
import os
import threading
import time

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

import archives
import fileops
import i18n
import places
import sugaractivities
from i18n import ntr, tr
from sugar3.graphics import style
from sugar3.graphics.icon import Icon
from sugar3.graphics.xocolor import XoColor

# (trazo, relleno) de los iconos de las unidades: una pareja por unidad, en
# el orden del menú.
_DRIVE_COLORS = [('#00588C', '#8BD1FF'), ('#B20008', '#FF8F91'),
                 ('#005FE4', '#FFD400'), ('#3E8B00', '#B7F36B'),
                 ('#8E00B0', '#E8A5FF'), ('#C65600', '#FFC48A'),
                 ('#00796B', '#7DE3D2'), ('#6D6D6D', '#D4D4D4')]

_FILL_CHUNK = 400          # filas que se añaden por cada pasada de la interfaz
_NAV_GUARD = 0.45          # s tras navegar en que se ignoran clics (doble clic)
_REFRESH_DELAY = 800       # ms de espera antes de recargar por un cambio en disco
_ICON_SIZE = 32            # iconos GNOME (el tema de Sugar no trae los de tipos)
# Las listas de Sugar (el Diario, por ejemplo) usan filas de una celda de la
# cuadrícula (75 px); aquí el 75 % para que quepan más archivos a la vista.
_ROW_HEIGHT = int(style.GRID_CELL_SIZE * 0.75)

(COL_NAME, COL_DISPLAY, COL_ICON, COL_SIZE, COL_MTIME,
 COL_ISDIR) = range(6)
_COLUMNS = list(range(6))

# El tema de iconos de Sugar no trae los de tipos de archivo (carpeta, texto,
# imagen...), así que se piden al tema GNOME y se guardan en una caché: así
# cada icono se carga una sola vez, aunque haya miles de archivos.
_file_theme = None
_pixbuf_cache = {}


def _icon_pixbuf(gicon):
    global _file_theme
    if gicon is None:
        return None
    key = gicon.to_string()
    if key in _pixbuf_cache:
        return _pixbuf_cache[key]
    if _file_theme is None:
        _file_theme = Gtk.IconTheme.new()
        _file_theme.set_custom_theme('gnome')
    pixbuf = None
    candidates = [gicon] + [Gio.ThemedIcon.new(n) for n in
                            ('application-x-generic', 'text-x-generic')]
    for candidate in candidates:
        info = _file_theme.lookup_by_gicon(candidate, _ICON_SIZE,
                                           Gtk.IconLookupFlags.FORCE_SIZE)
        if info is None:
            continue
        try:
            pixbuf = info.load_icon()
            break
        except GLib.GError:
            continue
    _pixbuf_cache[key] = pixbuf
    return pixbuf


class FileView(Gtk.Box):

    kind = 'folder'            # las pestañas de plugin tienen kind = 'plugin'

    def __init__(self, app, path):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL,
                         spacing=2)
        self.app = app
        self.path = os.path.normpath(fileops._clean(path))
        self.show_hidden = app.show_hidden
        self._token = 0
        self._last_nav = 0.0
        self._press_path = None
        self._monitor = None
        self._refresh_id = None
        self._active = False
        self._after_load = {}
        self._entries = []
        self._by_name = {}
        self._fill_pos = 0
        self._menu = None
        self._editing = False      # renombrando: no se recarga la lista
        self._dirty = False        # hubo cambios mientras se editaba
        self.loads = 0             # cargas completas (para depurar)
        self.last_load_time = 0.0  # segundos que tardó la última carga
        self.load_log = []         # (ruta, filas, s totales, s del hilo)
        self._load_started = 0.0
        self._list_time = 0.0
        self._build()
        self.reload()

    # ------------------------------------------------------------------
    # Construcción
    # ------------------------------------------------------------------

    def _build(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_border_width(4)
        up = Gtk.Button()
        up.set_relief(Gtk.ReliefStyle.NONE)
        up.add(Icon(icon_name='go-up', pixel_size=24))
        up.set_tooltip_text(tr('Up'))
        up.connect('clicked', lambda _button: self.go_up())
        home = Gtk.Button()
        home.set_relief(Gtk.ReliefStyle.NONE)
        home.add(Icon(icon_name='archivos-home', pixel_size=24))
        home.set_tooltip_text(tr('Home'))
        home.connect('clicked', lambda _button: self.go_home())
        places_button = Gtk.Button()
        places_button.set_relief(Gtk.ReliefStyle.NONE)
        places_button.add(Icon(icon_name='archivos-usb', pixel_size=24))
        places_button.set_tooltip_text(tr('Drives'))
        places_button.connect('clicked', self._on_places_clicked)
        self.entry = Gtk.Entry()
        self.entry.set_text(self.path)
        self.entry.connect('activate', self._on_entry_activate)
        bar.pack_start(home, False, False, 0)
        bar.pack_start(places_button, False, False, 0)
        bar.pack_start(up, False, False, 0)
        bar.pack_start(self.entry, True, True, 0)
        self.pack_start(bar, False, False, 0)

        self.store = self._new_store()
        self._next_store = None
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.set_headers_visible(True)
        self.tree.set_rubber_banding(True)
        self.tree.set_enable_search(True)
        self.tree.set_search_column(COL_DISPLAY)
        self.tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)

        column = Gtk.TreeViewColumn(tr('Name'))
        column.set_expand(True)
        column.set_resizable(True)
        icon_cell = Gtk.CellRendererPixbuf()
        icon_cell.set_property('xpad', 8)
        icon_cell.set_fixed_size(-1, _ROW_HEIGHT)
        column.pack_start(icon_cell, False)
        column.add_attribute(icon_cell, 'pixbuf', COL_ICON)
        self._text_cell = Gtk.CellRendererText()
        self._text_cell.set_property('ellipsize', Pango.EllipsizeMode.END)
        self._text_cell.set_property('xpad', 6)
        self._text_cell.set_fixed_size(-1, _ROW_HEIGHT)
        # Como en las listas de Sugar (el Diario usa weight="bold"), solo el
        # nombre va en negrita; el tamaño y la fecha, en la fuente normal.
        self._text_cell.set_property('weight', Pango.Weight.BOLD)
        self._text_cell.connect('edited', self._on_edited)
        self._text_cell.connect('editing-canceled', self._on_edit_canceled)
        column.pack_start(self._text_cell, True)
        column.add_attribute(self._text_cell, 'text', COL_DISPLAY)
        self._name_col = column
        self.tree.append_column(column)

        size_cell = Gtk.CellRendererText()
        size_cell.set_property('xalign', 1.0)
        size_cell.set_property('xpad', 8)
        self.tree.append_column(
            Gtk.TreeViewColumn(tr('Size'), size_cell, text=COL_SIZE))
        mtime_cell = Gtk.CellRendererText()
        mtime_cell.set_property('xpad', 8)
        self.tree.append_column(
            Gtk.TreeViewColumn(tr('Modified'), mtime_cell, text=COL_MTIME))

        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.AUTOMATIC,
                                Gtk.PolicyType.AUTOMATIC)
        self._scroll.add(self.tree)
        self.pack_start(self._scroll, True, True, 0)

        self.status = Gtk.Label()
        self.status.set_alignment(0, 0.5)
        self.status.set_margin_left(6)
        self.pack_start(self.status, False, False, 2)

        self.tree.connect('button-press-event', self._on_press)
        self.tree.connect('button-release-event', self._on_release)
        self.tree.connect('key-press-event', self._on_key)
        self.tree.connect('row-activated', self._on_row_activated)
        self.tree.get_selection().connect('changed', self._on_selection)
        self.show_all()

    # ------------------------------------------------------------------
    # Carga del listado
    # ------------------------------------------------------------------

    def title(self):
        if self.path == os.path.expanduser('~'):
            return tr('Home')
        return os.path.basename(self.path) or '/'

    def reload(self, select=None, rename=False, keep_scroll=False):
        """Vuelve a leer la carpeta (en un hilo) y rellena la lista.

        ``keep_scroll`` conserva la posición de desplazamiento (recargas
        automáticas); al cambiar de carpeta se empieza desde arriba.
        """
        if self._editing:
            self._dirty = True
            return
        self._token += 1
        token = self._token
        self._load_started = time.time()
        names = [select] if select else self.selected_names()
        scroll = (self._scroll.get_vadjustment().get_value()
                  if keep_scroll else 0.0)
        self._after_load = {'select': names, 'rename': rename,
                            'scroll': scroll}
        path, hidden = self.path, self.show_hidden

        def work():
            started = time.time()
            try:
                entries, error = fileops.list_dir(path, hidden), None
            except fileops.FileOpError as exc:
                entries, error = None, str(exc)
            GLib.idle_add(self._loaded, token, entries, error,
                          time.time() - started)

        thread = threading.Thread(target=work)
        thread.daemon = True
        thread.start()

    @staticmethod
    def _new_store():
        return Gtk.ListStore(str, str, GdkPixbuf.Pixbuf, str, str, bool)

    def _swap_store(self, store):
        self.store = store
        self.tree.set_model(store)

    def _loaded(self, token, entries, error, list_time=0.0):
        if token != self._token:
            return False
        self._list_time = list_time
        if error:
            self._entries = []
            self._next_store = None
            self._swap_store(self._new_store())
            self.status.set_text(error)
            return False
        # La carpeta nueva se rellena en un almacén APARTE, sin conectar al
        # árbol (así GTK no recalcula las columnas por cada fila) y la lista
        # que se está viendo no se vacía: se cambia de golpe al terminar. Un
        # almacén conectado y vaciado dejaba la lista en blanco durante las
        # recargas automáticas con la CPU ocupada.
        self._entries = entries
        self._fill_pos = 0
        self._next_store = self._new_store()
        GLib.idle_add(self._fill_chunk, token)
        return False

    def _fill_chunk(self, token):
        if token != self._token:
            return False
        end = min(self._fill_pos + _FILL_CHUNK, len(self._entries))
        # insert_with_valuesv es ~8 veces más rápido que append() en PyGObject
        # 3.4 (0,4 frente a 3 ms por fila en el XO).
        insert = self._next_store.insert_with_valuesv
        for entry in self._entries[self._fill_pos:end]:
            insert(-1, _COLUMNS, [
                entry.name, entry.display, _icon_pixbuf(entry.icon),
                '' if entry.is_dir else i18n.decimal(
                    fileops.human_size(entry.size)),
                fileops.format_mtime(entry.mtime), entry.is_dir])
        self._fill_pos = end
        if end < len(self._entries):
            return True
        store, self._next_store = self._next_store, None
        self._swap_store(store)
        self._finish_load()
        return False

    def _finish_load(self):
        self._by_name = dict((e.name, e) for e in self._entries)
        self.loads += 1
        self.last_load_time = time.time() - self._load_started
        self.load_log.append((self.path, len(self.store),
                              round(self.last_load_time, 2),
                              round(self._list_time, 2)))
        del self.load_log[:-30]
        self._update_status()
        scroll = self._after_load.get('scroll') or 0.0
        if scroll:
            adjustment = self._scroll.get_vadjustment()
            GLib.idle_add(lambda: adjustment.set_value(scroll) and False)
        names = self._after_load.get('select') or []
        if names:
            selection = self.tree.get_selection()
            selection.unselect_all()
            first = None
            for row in self.store:
                if row[COL_NAME] in names:
                    selection.select_path(row.path)
                    if first is None:
                        first = row.path
            if first is not None:
                self.tree.scroll_to_cell(first, None, False, 0, 0)
                if self._after_load.get('rename') and len(names) == 1:
                    self.start_rename(first)
        self._after_load = {}

    def status_text(self):
        """«3 carpetas y 12,4 MB en 5 archivos»; con selección, cuántos y su peso."""
        names = self.selected_names()
        if names:
            by_name = self._by_name
            size = sum(by_name[n].size for n in names
                       if n in by_name and not by_name[n].is_dir)
            text = ntr('%d selected', '%d selected', len(names)) % len(names)
            if size:
                text += ' (%s)' % i18n.decimal(fileops.human_size(size))
            return text
        folders, files, size = fileops.summarize(self._entries)
        return tr('%(folders)s and %(size)s in %(files)s') % {
            'folders': ntr('%d folder', '%d folders', folders) % folders,
            'files': ntr('%d file', '%d files', files) % files,
            'size': i18n.decimal(fileops.human_size(size))}

    def _update_status(self):
        self.status.set_text(self.status_text())

    def _on_selection(self, _selection):
        self._update_status()

    # ------------------------------------------------------------------
    # Acceso a la selección
    # ------------------------------------------------------------------

    def selected_names(self):
        model, paths = self.tree.get_selection().get_selected_rows()
        return [model[p][COL_NAME] for p in paths]

    def selected_paths(self):
        return [os.path.join(self.path, n) for n in self.selected_names()]

    def _row_path(self, name):
        for row in self.store:
            if row[COL_NAME] == name:
                return row.path
        return None

    def _is_dir(self, name):
        path = self._row_path(name)
        return bool(path is not None and self.store[path][COL_ISDIR])

    # ------------------------------------------------------------------
    # Navegación
    # ------------------------------------------------------------------

    def navigate(self, new_path, select=None):
        new_path = os.path.normpath(fileops._clean(new_path))
        if not os.path.isdir(new_path):
            self.app.show_message('%s: %s' % (tr('Not a folder'), new_path))
            self.entry.set_text(self.path)
            return False
        if not os.access(new_path, os.R_OK | os.X_OK):
            self.app.show_message('%s: %s' % (tr('Cannot read this folder'),
                                              new_path))
            self.entry.set_text(self.path)
            return False
        self.path = new_path
        self._last_nav = time.time()
        self.entry.set_text(new_path)
        self.reload(select=select)
        if self._active:
            self._start_monitor()
        self.app.view_path_changed(self)
        return True

    def go_home(self):
        """Va a la carpeta personal del usuario."""
        self.navigate(os.path.expanduser('~'))

    def _on_places_clicked(self, button):
        """Menú con las unidades extraíbles montadas (se consultan al abrirlo).

        Cada una lleva el icono de memoria USB en un color distinto (por su
        posición en la lista), para reconocerlas aunque haya varias particiones.
        """
        menu = Gtk.Menu()
        drives = places.removable_mounts()
        for index, (name, path) in enumerate(drives):
            stroke, fill = _DRIVE_COLORS[index % len(_DRIVE_COLORS)]
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.pack_start(Icon(icon_name='archivos-drive', pixel_size=28,
                                xo_color=XoColor('%s,%s' % (stroke, fill))),
                           False, False, 0)
            label = Gtk.Label(label=name)
            label.set_alignment(0, 0.5)
            row.pack_start(label, True, True, 0)
            item = Gtk.MenuItem()
            item.add(row)
            item.set_tooltip_text(path)
            item.connect('activate', lambda _i, p=path: self.navigate(p))
            menu.append(item)
        if not drives:
            item = Gtk.MenuItem(label=tr('No drives mounted'))
            item.set_sensitive(False)
            menu.append(item)
        menu.show_all()
        menu.popup(None, None, None, None, 1, Gtk.get_current_event_time())

    def go_up(self):
        parent = os.path.dirname(self.path) or '/'
        if parent != self.path:
            self.navigate(parent, select=os.path.basename(self.path))

    def _on_entry_activate(self, entry):
        if self.navigate(os.path.expanduser(entry.get_text())):
            self.tree.grab_focus()

    # ------------------------------------------------------------------
    # Abrir
    # ------------------------------------------------------------------

    def open_name(self, name):
        full = os.path.join(self.path, name)
        if self._is_dir(name):
            self.navigate(full)
        else:
            self.open_file(full)

    def _content_type(self, full):
        """Tipo MIME de un archivo, mirando también su contenido."""
        try:
            info = Gio.File.new_for_path(full).query_info(
                'standard::content-type', Gio.FileQueryInfoFlags.NONE, None)
            return info.get_content_type()
        except GLib.GError:
            return fileops.content_type_for(os.path.basename(full))

    def open_in_activity(self, full, activity):
        """Abre ``full`` en otra actividad de Sugar."""
        try:
            sugaractivities.launch(activity, full)
        except Exception as exc:
            self.app.show_message('%s: %s' % (tr('Could not open the file'),
                                              exc))

    def open_file(self, full, app_info=None):
        """Abre un archivo con el primero que valga: la pestaña de un plugin
        (clic normal), la aplicación por defecto del sistema o, si no hay y
        una única actividad de Sugar declara ese tipo, esa actividad."""
        if app_info is None and self.app.open_file(full):
            return
        content_type = self._content_type(full)
        sugar = []
        if app_info is None:
            sugar = sugaractivities.handlers_for(content_type, strict=True)
        try:
            if app_info is None:
                app_info = Gio.app_info_get_default_for_type(content_type,
                                                             False)
            if app_info is None:
                if len(sugar) == 1:
                    self.open_in_activity(full, sugar[0])
                else:
                    self.app.show_message(
                        tr('No application available for this file'))
                return
            app_info.launch([Gio.File.new_for_path(full)], None)
        except GLib.GError as exc:
            # La aplicación por defecto puede estar a medio quitar (queda su
            # .desktop sin el programa): si hay una actividad, mejor ella.
            if len(sugar) == 1:
                self.open_in_activity(full, sugar[0])
                return
            self.app.show_message('%s: %s' % (tr('Could not open the file'),
                                              exc.message))

    def _on_row_activated(self, tree, tree_path, _column):
        # El doble clic del ratón ya lo trata el clic principal; aquí solo
        # llega el Intro del teclado.
        event = Gtk.get_current_event()
        if event is not None and event.type in (
                Gdk.EventType.BUTTON_PRESS, Gdk.EventType._2BUTTON_PRESS,
                Gdk.EventType.BUTTON_RELEASE):
            return
        self.open_name(self.store[tree_path][COL_NAME])

    # ------------------------------------------------------------------
    # Ratón
    # ------------------------------------------------------------------

    def _on_press(self, tree, event):
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        hit = tree.get_path_at_pos(int(event.x), int(event.y))
        self._press_path = hit[0] if hit else None
        if event.button == 3:
            selection = tree.get_selection()
            if hit is None:
                selection.unselect_all()
            elif not selection.path_is_selected(hit[0]):
                selection.unselect_all()
                selection.select_path(hit[0])
            self.popup_menu(event.time)
            return True
        return False

    def _on_release(self, tree, event):
        if event.button != 1:
            return False
        if event.state & (Gdk.ModifierType.CONTROL_MASK |
                          Gdk.ModifierType.SHIFT_MASK):
            return False
        if time.time() - self._last_nav < _NAV_GUARD:
            return False
        hit = tree.get_path_at_pos(int(event.x), int(event.y))
        if hit is None or self._press_path is None:
            return False
        if hit[0] != self._press_path:
            return False
        self.open_name(self.store[hit[0]][COL_NAME])
        return False

    # ------------------------------------------------------------------
    # Menú contextual
    # ------------------------------------------------------------------

    def _open_with_menu(self, full):
        # Todos los plugins, también los que no reconocen el archivo, para poder
        # forzarlos (por ejemplo, un .pas renombrado a .inc): primero los que sí.
        internal = self.app.plugins_for(full, all_plugins=True)
        # Actividades de Sugar que declaran el tipo (con los genéricos:
        # aquí se elige a mano, no hay riesgo de abrir algo sin querer).
        activities = sugaractivities.handlers_for(self._content_type(full))
        try:
            apps = [a for a in
                    Gio.app_info_get_all_for_type(self._content_type(full))
                    if a.should_show()]
            # Sin ninguna opción para este tipo, se ofrecen todas las
            # aplicaciones; pero si ya hay opciones internas (plugins) o
            # actividades no hace falta llenar el menú con las del sistema.
            if not apps and not internal and not activities:
                apps = [a for a in Gio.app_info_get_all() if a.should_show()]
        except Exception:
            apps = []
        if not apps and not internal and not activities:
            return None
        submenu = Gtk.Menu()
        # Primero las opciones internas (plugins): se abren en una pestaña.
        for plugin in internal:
            item = Gtk.MenuItem(label=plugin.display_name())
            item.connect('activate',
                         lambda _i, p=plugin: self.app.open_file(full, p))
            submenu.append(item)
        if internal and (activities or apps):
            submenu.append(Gtk.SeparatorMenuItem())
        for activity in activities:
            item = Gtk.MenuItem(label=activity.name)
            item.connect('activate',
                         lambda _i, a=activity: self.open_in_activity(full, a))
            submenu.append(item)
        if activities and apps:
            submenu.append(Gtk.SeparatorMenuItem())
        for app_info in apps:
            item = Gtk.MenuItem(label=app_info.get_display_name())
            item.connect('activate',
                         lambda _i, a=app_info: self.open_file(full, a))
            submenu.append(item)
        return submenu

    def popup_menu(self, event_time=0, button=3):
        names = self.selected_names()
        paths = self.selected_paths()
        menu = Gtk.Menu()

        def add(label, callback, sensitive=True):
            item = Gtk.MenuItem(label=label)
            item.set_sensitive(sensitive)
            item.connect('activate', lambda _i: callback())
            menu.append(item)

        def separator():
            if menu.get_children():
                menu.append(Gtk.SeparatorMenuItem())

        if len(names) == 1:
            name, full = names[0], paths[0]
            add(tr('Open'), lambda: self.open_name(name))
            if self._is_dir(name):
                add(tr('Open in new tab'), lambda: self.app.open_tab(full))
            else:
                submenu = self._open_with_menu(full)
                if submenu is not None:
                    item = Gtk.MenuItem(label=tr('Open with'))
                    item.set_submenu(submenu)
                    menu.append(item)
            separator()
        if names:
            add(tr('Copy'), lambda: self.app.do_copy(paths))
            add(tr('Cut'), lambda: self.app.do_cut(paths))
        if self.app.clipboard_has_items():
            if len(names) == 1 and self._is_dir(names[0]):
                add(tr('Paste into folder'),
                    lambda: self.app.do_paste(paths[0]))
            add(tr('Paste'), lambda: self.app.do_paste(self.path))
        if names:
            separator()
            if len(names) == 1:
                add(tr('Rename'), self.start_rename)
            add(tr('Delete'), lambda: self.app.do_delete(paths))
            separator()
            if any(archives.is_archive(n) and not self._is_dir(n)
                   for n in names):
                add(tr('Extract'),
                    lambda: self.app.do_extract(paths, self.path))
            compress = Gtk.Menu()
            for label, gz in ((tr('Create .tar'), False),
                              (tr('Create .tar.gz'), True)):
                item = Gtk.MenuItem(label=label)
                item.connect('activate', lambda _i, gz=gz:
                             self.app.do_compress(paths, self.path, gz))
                compress.append(item)
            parent_item = Gtk.MenuItem(label=tr('Compress'))
            parent_item.set_submenu(compress)
            menu.append(parent_item)
        separator()
        add(tr('New folder'), self.new_folder)
        add(tr('New file'), self.new_file)
        check = Gtk.CheckMenuItem(label=tr('Show hidden files'))
        check.set_active(self.show_hidden)
        check.connect('toggled',
                      lambda i: self.app.set_show_hidden(i.get_active()))
        menu.append(check)
        add(tr('Refresh'), self.reload)
        menu.show_all()
        menu.attach_to_widget(self.tree, None)
        self._menu = menu
        menu.popup(None, None, None, None, button, event_time)
        return menu

    # ------------------------------------------------------------------
    # Teclado
    # ------------------------------------------------------------------

    def _on_key(self, tree, event):
        name = Gdk.keyval_name(event.keyval) or ''
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(event.state & Gdk.ModifierType.MOD1_MASK)
        if name == 'F2':
            self.start_rename()
        elif name == 'Delete':
            self.app.do_delete(self.selected_paths())
        elif name == 'F5':
            self.reload()
        elif name == 'BackSpace' or (alt and name == 'Up'):
            self.go_up()
        elif alt and name == 'Home':
            self.go_home()
        elif ctrl and name in ('c', 'C'):
            self.app.do_copy(self.selected_paths())
        elif ctrl and name in ('x', 'X'):
            self.app.do_cut(self.selected_paths())
        elif ctrl and name in ('v', 'V'):
            self.app.do_paste(self.path)
        elif ctrl and name in ('l', 'L'):
            self.entry.grab_focus()
        else:
            return False
        return True

    # ------------------------------------------------------------------
    # Renombrar y carpeta nueva
    # ------------------------------------------------------------------

    def start_rename(self, tree_path=None):
        if tree_path is None:
            names = self.selected_names()
            if len(names) != 1:
                return
            tree_path = self._row_path(names[0])
            if tree_path is None:
                return
        self._editing = True
        self._text_cell.set_property('editable', True)
        self.tree.set_cursor(tree_path, self._name_col, True)

    def _end_editing(self, cell):
        cell.set_property('editable', False)
        self._editing = False

    def _on_edited(self, cell, path_str, new_text):
        self._end_editing(cell)
        old = self.store[path_str][COL_NAME]
        if new_text == old:
            self._reload_if_dirty()
            return
        try:
            new_path = fileops.rename(os.path.join(self.path, old), new_text)
        except fileops.FileOpError as exc:
            self.app.show_message(str(exc))
            self._reload_if_dirty()
            return
        self._dirty = False
        self.reload(select=os.path.basename(new_path))

    def _on_edit_canceled(self, cell):
        self._end_editing(cell)
        self._reload_if_dirty()

    def _reload_if_dirty(self):
        if self._dirty:
            self._dirty = False
            self.reload(keep_scroll=True)

    def new_folder(self):
        name = fileops.unique_name(self.path, tr('New folder'))
        try:
            fileops.make_dir(self.path, name)
        except fileops.FileOpError as exc:
            self.app.show_message(str(exc))
            return
        self.reload(select=name, rename=True)

    def new_file(self):
        """Crea un archivo vacío (0 bytes) y deja su nombre en edición."""
        name = fileops.unique_name(self.path, tr('New file'))
        try:
            fileops.make_file(self.path, name)
        except fileops.FileOpError as exc:
            self.app.show_message(str(exc))
            return
        self.reload(select=name, rename=True)

    # ------------------------------------------------------------------
    # Vigilancia de cambios en disco (solo en la pestaña visible)
    # ------------------------------------------------------------------

    def set_active(self, active):
        if active == self._active:
            return
        self._active = active
        if active:
            self.reload()
            self._start_monitor()
        else:
            self._stop_monitor()

    def _start_monitor(self):
        self._stop_monitor()
        try:
            self._monitor = Gio.File.new_for_path(
                self.path).monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self._monitor.connect('changed', self._on_dir_changed)
        except GLib.GError:
            self._monitor = None

    def _stop_monitor(self):
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None

    def _on_dir_changed(self, _monitor, changed, _other, event):
        if event in (Gio.FileMonitorEvent.ATTRIBUTE_CHANGED,):
            return
        # Los temporales ocultos (.nombre.part, carpetas .extracting...) no se
        # ven en la lista: no hace falta recargar por ellos.
        if (changed is not None and not self.show_hidden
                and (changed.get_basename() or '').startswith('.')):
            return
        # Durante una copia, compresión... el archivo cambia sin parar: se
        # recarga una sola vez al terminar (app._on_op_finish).
        if self.app.busy():
            self._dirty = True
            return
        if self._refresh_id is None:
            self._refresh_id = GLib.timeout_add(_REFRESH_DELAY,
                                                self._delayed_reload)

    def _delayed_reload(self):
        self._refresh_id = None
        self.reload(keep_scroll=True)
        return False

    def destroy_view(self):
        self._stop_monitor()
        self._token += 1
        if self._refresh_id is not None:
            GLib.source_remove(self._refresh_id)
            self._refresh_id = None
