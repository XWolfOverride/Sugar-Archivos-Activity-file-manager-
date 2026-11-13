# -*- coding: utf-8 -*-
"""Pestañas: un Gtk.Notebook que reparte el ancho entre ellas.

- Con una sola pestaña, ocupa la mitad del ancho.
- Desde la segunda, todas se reparten el ancho completo a partes iguales
  (cada vez más estrechas al añadir más).
- El botón «+» queda a la derecha del todo, en la propia barra de pestañas.
"""
from gi.repository import GLib, Gtk, Pango

from sugar3.graphics.icon import Icon

_CLOSE_ICON = 28          # px del icono de cerrar
_PLUS_ICON = 32           # px del icono «+»
_MIN_LABEL = 40           # ancho mínimo (px) del título cuando hay muchas# Lo que la pestaña añade al texto: relleno del tema (~8), hueco (6) y botón
# de cerrar (~42). Calibrado en pantalla para que una pestaña ocupe la mitad.
_TAB_PADDING = 56


class TabLabel(Gtk.Box):
    """Etiqueta de pestaña: título (con puntos suspensivos) y botón de cerrar."""

    def __init__(self, title, on_close):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.HORIZONTAL,
                         spacing=6)
        self._label = Gtk.Label(label=title)
        self._label.set_ellipsize(Pango.EllipsizeMode.END)
        self._label.set_alignment(0.0, 0.5)
        self._label.set_size_request(_MIN_LABEL, -1)
        self.pack_start(self._label, True, True, 0)

        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_focus_on_click(False)
        button.add(Icon(icon_name='dialog-cancel', pixel_size=_CLOSE_ICON))
        button.connect('clicked', lambda _button: on_close())
        self.pack_start(button, False, False, 0)
        self.show_all()

    def set_title(self, title, tooltip=None):
        self._label.set_text(title)
        self.set_tooltip_text(tooltip or title)

    def set_label_width(self, width):
        self._label.set_size_request(max(int(width), _MIN_LABEL), -1)


class TabNotebook(Gtk.Notebook):
    """Notebook cuyas pestañas reparten el ancho; cada página es una FileView."""

    def __init__(self, on_new_tab):
        Gtk.Notebook.__init__(self)
        self.set_scrollable(True)
        self.set_show_border(False)
        self.set_tab_pos(Gtk.PositionType.TOP)
        self._labels = {}
        self._layout_id = None
        self._last_width = 0

        self._plus = Gtk.Button()
        self._plus.set_relief(Gtk.ReliefStyle.NONE)
        self._plus.set_focus_on_click(False)
        self._plus.add(Icon(icon_name='list-add', pixel_size=_PLUS_ICON))
        self._plus.connect('clicked', lambda _button: on_new_tab())
        self._plus.show_all()
        self.set_action_widget(self._plus, Gtk.PackType.END)

        self.connect('size-allocate', self._on_size_allocate)

    # ------------------------------------------------------------------

    def add_view(self, view, title, on_close, position=-1):
        label = TabLabel(title, lambda: on_close(view))
        self._labels[view] = label
        index = self.insert_page(view, label, position)
        view.show()
        self.set_tab_reorderable(view, True)
        self._queue_layout()
        return index

    def remove_view(self, view):
        index = self.page_num(view)
        if index >= 0:
            self.remove_page(index)
        self._labels.pop(view, None)
        self._queue_layout()

    def set_view_title(self, view, title, tooltip=None):
        label = self._labels.get(view)
        if label is not None:
            label.set_title(title, tooltip)

    def views(self):
        return [self.get_nth_page(i) for i in range(self.get_n_pages())]

    def current_view(self):
        index = self.get_current_page()
        if index < 0:
            return None
        return self.get_nth_page(index)

    # ------------------------------------------------------------------
    # Reparto del ancho
    # ------------------------------------------------------------------

    def _on_size_allocate(self, _widget, allocation):
        if allocation.width != self._last_width:
            self._last_width = allocation.width
            self._queue_layout()

    def _queue_layout(self):
        if self._layout_id is None:
            self._layout_id = GLib.idle_add(self._layout)

    def _layout(self):
        self._layout_id = None
        views = self.views()
        count = len(views)
        width = self.get_allocated_width()
        if count == 0 or width <= 1:
            return False
        if count == 1:
            # Una pestaña: la mitad del ancho, sin expandirse.
            view = views[0]
            self.child_set_property(view, 'tab-expand', False)
            self._labels[view].set_label_width(width // 2 - _TAB_PADDING)
        else:
            # Varias: todas con el mismo mínimo y expandiéndose por igual, así
            # llenan el ancho a partes iguales.
            for view in views:
                self.child_set_property(view, 'tab-expand', True)
                self._labels[view].set_label_width(_MIN_LABEL)
        return False
