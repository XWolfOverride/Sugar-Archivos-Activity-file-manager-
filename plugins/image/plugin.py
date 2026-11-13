# -*- coding: utf-8 -*-
"""Plugin «Image viewer»: abre imágenes en una pestaña.

Carga perezosa: la imagen se decodifica en un hilo y ya reducida al tamaño de la
ventana (el decodificador JPEG escala al leer: una foto de 12 MP tarda ~2 s y
~3 MB en vez de 8,5 s y 34 MB). Con las flechas se recorren las imágenes de la
carpeta; el botón de tamaño real solo se ofrece si la imagen cabe en memoria.
"""
import os
import threading

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

import fileops
import i18n
import pluginapi
from i18n import N_
from imgutil import fit_size, list_siblings, megapixels
from pluginui import PluginTab, icon_button

# Los atributos de gi se cargan de forma perezosa y no es seguro hacerlo por
# primera vez desde otro hilo: se tocan aquí, en el hilo principal.
_new_from_file = GdkPixbuf.Pixbuf.new_from_file
_new_at_size = GdkPixbuf.Pixbuf.new_from_file_at_size
_get_info = GdkPixbuf.Pixbuf.get_file_info

_MAX_FULL_MP = 4.0             # megapíxeles máximos para verla a tamaño real
_DEFAULT_AREA = (1100, 650)    # hasta que se conoce el tamaño de la ventana


class Plugin(pluginapi.Plugin):
    id = 'image'
    name = N_('Image viewer')

    def __init__(self, host, directory):
        pluginapi.Plugin.__init__(self, host, directory)
        self._types = None

    def supported_types(self):
        if self._types is None:
            types = set()
            for pixbuf_format in GdkPixbuf.Pixbuf.get_formats():
                types.update(pixbuf_format.get_mime_types())
            self._types = types
        return self._types

    def is_image_name(self, name):
        return fileops.content_type_for(name) in self.supported_types()

    def handles(self, path, content_type):
        return 100 if content_type in self.supported_types() else 0

    def open_tab(self, path):
        return ImageTab(self.host, self, path)


class ImageTab(PluginTab):

    def __init__(self, host, plugin, path):
        PluginTab.__init__(self, host, plugin, path)
        self._token = 0
        self._full = False
        self._pixbuf = None
        self._info = ''
        self._resize_id = None
        self._last_area = None
        self._siblings, self._index = list_siblings(path,
                                                    plugin.is_image_name)
        self._build()
        GLib.idle_add(self._first_load)

    # ------------------------------------------------------------------

    def _build(self):
        tr = self.plugin.tr
        bar = Gtk.EventBox()
        bar.override_background_color(Gtk.StateFlags.NORMAL,
                                      Gdk.RGBA(0.16, 0.16, 0.16, 1))
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_border_width(4)
        row.pack_start(icon_button('go-previous', tr('Previous image'),
                                   lambda _b: self.go(-1)), False, False, 0)
        row.pack_start(icon_button('go-next', tr('Next image'),
                                   lambda _b: self.go(1)), False, False, 0)
        self._label = Gtk.Label()
        self._label.set_alignment(0, 0.5)
        self._label.override_color(Gtk.StateFlags.NORMAL,
                                   Gdk.RGBA(1, 1, 1, 1))
        row.pack_start(self._label, True, True, 8)
        theme = Gtk.IconTheme.get_default()
        zoom_icon = 'zoom-original' if theme.has_icon('zoom-original') \
            else 'view-fullscreen'
        self._zoom = icon_button(zoom_icon, tr('Actual size'),
                                 self._on_zoom, toggle=True)
        row.pack_start(self._zoom, False, False, 0)
        bar.add(row)
        self.pack_start(bar, False, False, 0)

        self._image = Gtk.Image()
        self._box = Gtk.EventBox()
        self._box.override_background_color(Gtk.StateFlags.NORMAL,
                                            Gdk.RGBA(0.1, 0.1, 0.1, 1))
        self._box.set_can_focus(True)
        self._box.add(self._image)
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.AUTOMATIC,
                                Gtk.PolicyType.AUTOMATIC)
        self._scroll.add(self._box)
        self.pack_start(self._scroll, True, True, 0)
        self._box.connect('key-press-event', self._on_key)
        self._scroll.connect('size-allocate', self._on_size_allocate)
        self.show_all()

    # ------------------------------------------------------------------
    # Carga
    # ------------------------------------------------------------------

    def _area(self):
        alloc = self._scroll.get_allocation()
        if alloc.width > 50 and alloc.height > 50:
            return alloc.width - 4, alloc.height - 4
        return _DEFAULT_AREA

    def _first_load(self):
        self._box.grab_focus()
        self._load()
        return False

    def _load(self):
        self._token += 1
        token, path, full = self._token, self.path, self._full
        max_w, max_h = self._area()
        self._last_area = (max_w, max_h)
        self._label.set_text(self.plugin.tr('Loading…'))

        def work():
            pixbuf, width, height, error = None, 0, 0, None
            try:
                info = _get_info(path)
                if info and info[0]:
                    width, height = info[1], info[2]
                if full:
                    if megapixels(width, height) > _MAX_FULL_MP:
                        error = self.plugin.tr(
                            'Too big to show at actual size')
                    else:
                        pixbuf = _new_from_file(path)
                elif width and (width <= max_w and height <= max_h):
                    pixbuf = _new_from_file(path)          # ya cabe: sin escalar
                else:
                    pixbuf = _new_at_size(path, max_w, max_h)
            except GLib.GError as exc:
                error = '%s: %s' % (self.plugin.tr('Could not load the image'),
                                    exc.message)
            GLib.idle_add(self._loaded, token, pixbuf, width, height, error)

        thread = threading.Thread(target=work)
        thread.daemon = True
        thread.start()

    def _loaded(self, token, pixbuf, width, height, error):
        if token != self._token:
            return False
        if error is not None and pixbuf is None:
            self._label.set_text(error)
            if self._full:
                self._zoom.set_active(False)     # vuelve al ajuste a ventana
            return False
        self._pixbuf = pixbuf                    # suelta la anterior
        self._image.set_from_pixbuf(pixbuf)
        try:
            size = os.path.getsize(self.path)
        except OSError:
            size = 0
        self._info = '%s  —  %d×%d  —  %s' % (
            os.path.basename(self.path), width or pixbuf.get_width(),
            height or pixbuf.get_height(),
            i18n.decimal(fileops.human_size(size)))
        if len(self._siblings) > 1:
            self._info += '  —  %d/%d' % (self._index + 1, len(self._siblings))
        self._label.set_text(self._info)
        return False

    def _on_size_allocate(self, _widget, _allocation):
        if self._full or self._resize_id is not None:
            return
        self._resize_id = GLib.timeout_add(500, self._after_resize)

    def _after_resize(self):
        self._resize_id = None
        area = self._area()
        last = self._last_area
        if last is None or abs(area[0] - last[0]) > last[0] * 0.25 \
                or abs(area[1] - last[1]) > last[1] * 0.25:
            self._load()
        return False

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------

    def go(self, delta):
        if len(self._siblings) < 2:
            return
        self._index = (self._index + delta) % len(self._siblings)
        self.path = self._siblings[self._index]
        self._full = False
        self._zoom.handler_block_by_func(self._on_zoom)
        self._zoom.set_active(False)
        self._zoom.handler_unblock_by_func(self._on_zoom)
        self.title_changed()
        self._load()

    def _on_zoom(self, button):
        self._full = button.get_active()
        self._load()

    def _on_key(self, _widget, event):
        name = Gdk.keyval_name(event.keyval) or ''
        if name in ('Right', 'Page_Down', 'space', 'n'):
            self.go(1)
        elif name in ('Left', 'Page_Up', 'BackSpace', 'p'):
            self.go(-1)
        elif name == 'Home':
            self.go(-self._index)
        elif name == 'End':
            self.go(len(self._siblings) - 1 - self._index)
        elif name in ('1', 'z'):
            self._zoom.set_active(not self._zoom.get_active())
        else:
            return False
        return True

    # ------------------------------------------------------------------
    # Contrato de PluginTab
    # ------------------------------------------------------------------

    def get_state(self):
        return {'full': self._full}

    def restore_state(self, state):
        if state.get('full'):
            self._full = True
            self._zoom.handler_block_by_func(self._on_zoom)
            self._zoom.set_active(True)
            self._zoom.handler_unblock_by_func(self._on_zoom)

    def on_shown(self):
        self._box.grab_focus()

    def dispose(self):
        self._token += 1                         # descarta cargas en curso
        self._pixbuf = None
        if self._resize_id is not None:
            GLib.source_remove(self._resize_id)
            self._resize_id = None
