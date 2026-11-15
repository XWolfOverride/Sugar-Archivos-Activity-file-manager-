# -*- coding: utf-8 -*-
"""Ventana de propiedades de un archivo o carpeta.

Tiene el aspecto de las ventanas de Sugar con contenido (el Panel de control):
barra superior con el nombre y, a la derecha, cancelar y aceptar; debajo, el
contenido sobre fondo blanco. Enseña el tipo, el tamaño y las fechas; deja
cambiar los permisos y el grupo (y el propietario, solo si se es root) y, en
carpetas, marcarla como favorita con la estrella. Nada se aplica hasta aceptar.
"""
import os
import time

from gi.repository import Gdk, Gtk, Pango

import favorites
import fileops
import fileprops
import i18n
from i18n import tr
from sugar3.graphics import style
from sugar3.graphics.icon import Icon
from sugar3.graphics.toolbutton import ToolButton


def _date(seconds):
    try:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(seconds))
    except (ValueError, OverflowError, OSError):
        return ''


class PropertiesDialog(Gtk.Window):

    def __init__(self, app, path, on_done=None):
        info = fileprops.describe(path)
        Gtk.Window.__init__(self)
        self.info = info
        self._on_done = on_done
        self._app = app
        self.set_transient_for(app)
        self.set_modal(True)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_size_request(560, -1)
        self.set_border_width(style.LINE_WIDTH)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.connect('key-press-event', self._on_key)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(self._toolbar(), False, False, 0)
        body = Gtk.EventBox()
        body.modify_bg(Gtk.StateType.NORMAL, style.COLOR_WHITE.get_gdk_color())
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_border_width(style.DEFAULT_SPACING)
        content.pack_start(self._details(), False, False, 0)
        content.pack_start(self._ownership(), False, False, 0)
        content.pack_start(self._permissions(), False, False, 0)
        self._error = Gtk.Label()
        self._error.set_alignment(0, 0.5)
        self._error.set_line_wrap(True)
        self._error.set_no_show_all(True)
        self._paint(self._error, style.COLOR_BUTTON_GREY)
        content.pack_start(self._error, False, False, 0)
        body.add(content)
        root.pack_start(body, True, True, 0)
        self.add(root)
        self.show_all()
        self._error.hide()

    # ------------------------------------------------------------------

    @staticmethod
    def _paint(widget, color):
        widget.modify_fg(Gtk.StateType.NORMAL, color.get_gdk_color())

    def _toolbar(self):
        """Nombre a la izquierda; estrella (carpetas), cancelar y aceptar a la
        derecha, como la barra de las secciones del Panel de control."""
        info = self.info
        bar = Gtk.Toolbar()

        def add(widget, expand=False):
            item = Gtk.ToolItem()
            item.set_expand(expand)
            item.add(widget)
            bar.insert(item, -1)
            return item

        pad = Gtk.SeparatorToolItem()
        pad.props.draw = False
        pad.set_size_request(style.DEFAULT_SPACING, -1)
        bar.insert(pad, -1)
        name = Gtk.Label(label=info.name)
        name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        name.set_max_width_chars(40)
        name.set_alignment(0, 0.5)
        add(name, expand=True)
        self._star = None
        if info.is_dir:
            self._star = Gtk.ToggleButton()
            self._star.set_relief(Gtk.ReliefStyle.NONE)
            self._star.set_active(favorites.is_favorite(info.path))
            self._star.set_tooltip_text(tr('Favorite folder'))
            self._star_icon = Icon(pixel_size=style.STANDARD_ICON_SIZE)
            self._star.add(self._star_icon)
            self._star.connect('toggled', self._on_star)
            self._on_star(self._star)
            add(self._star)
        cancel = ToolButton('dialog-cancel')
        cancel.set_tooltip(tr('Cancel'))
        cancel.connect('clicked', lambda _b: self._close(False))
        bar.insert(cancel, -1)
        accept = ToolButton('dialog-ok')
        accept.set_tooltip(tr('OK'))
        accept.connect('clicked', lambda _b: self._close(True))
        bar.insert(accept, -1)
        return bar

    def _on_key(self, _window, event):
        if Gdk.keyval_name(event.keyval) == 'Escape':
            self._close(False)
            return True
        return False

    def _on_star(self, button):
        self._star_icon.props.icon_name = (
            'archivos-star-on' if button.get_active() else 'archivos-star')

    def _grid(self):
        grid = Gtk.Grid()
        grid.set_column_spacing(12)
        grid.set_row_spacing(4)
        return grid

    @staticmethod
    def _add_row(grid, row, label, text, selectable=True):
        title = Gtk.Label(label=label)
        title.set_alignment(1, 0)
        PropertiesDialog._paint(title, style.COLOR_BUTTON_GREY)
        value = Gtk.Label(label=text)
        PropertiesDialog._paint(value, style.COLOR_BLACK)
        value.set_alignment(0, 0)
        value.set_selectable(selectable)
        value.set_line_wrap(True)
        value.set_max_width_chars(48)
        value.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        grid.attach(title, 0, row, 1, 1)
        grid.attach(value, 1, row, 1, 1)

    def _details(self):
        info = self.info
        grid = self._grid()
        rows = []
        kind = info.type_description or info.mime
        if info.mime and info.type_description:
            kind = '%s (%s)' % (info.type_description, info.mime)
        rows.append((tr('Type'), kind))
        rows.append((tr('Location'), os.path.dirname(info.path) or '/'))
        if info.is_link:
            rows.append((tr('Link to'), info.link_target or ''))
        if info.is_dir:
            if info.items is not None:
                rows.append((tr('Contents'), _items_text(info.items)))
        else:
            rows.append((tr('Size'), _size_text(info.size)))
        rows.append((tr('Modified'), _date(info.mtime)))
        rows.append((tr('Accessed'), _date(info.atime)))
        rows.append((tr('Changed'), _date(info.ctime)))
        rows.append((tr('Created'), _date(info.created) if info.created
                     else tr('Not recorded')))
        for index, (label, text) in enumerate(rows):
            self._add_row(grid, index, label, text)
        return grid

    def _ownership(self):
        info = self.info
        grid = self._grid()
        self._owner = Gtk.Entry()
        self._owner.set_text(info.owner)
        self._owner.set_sensitive(fileprops.can_chown_owner())
        self._group = Gtk.ComboBoxText.new_with_entry()
        groups = fileprops.my_groups()
        if info.group not in groups:
            groups.insert(0, info.group)
        for name in groups:
            self._group.append_text(name)
        self._group.get_child().set_text(info.group)
        self._group.set_sensitive(fileprops.can_chown_group(info))
        for row, (label, widget) in enumerate(((tr('Owner'), self._owner),
                                               (tr('Group'), self._group))):
            title = Gtk.Label(label=label)
            title.set_alignment(1, 0.5)
            self._paint(title, style.COLOR_BUTTON_GREY)
            grid.attach(title, 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        return grid

    def _permissions(self):
        info = self.info
        frame = Gtk.Frame()
        caption = Gtk.Label(label=tr('Permissions'))
        self._paint(caption, style.COLOR_BUTTON_GREY)
        frame.set_label_widget(caption)
        grid = self._grid()
        grid.set_border_width(8)
        flags = fileprops.flags_from_mode(info.mode)
        sensitive = fileprops.can_chmod(info) and not info.is_link
        self._checks = []
        heads = (tr('Read'), tr('Write'), tr('Execute'))
        for col, text in enumerate(heads):
            head = Gtk.Label(label=text)
            self._paint(head, style.COLOR_BLACK)
            grid.attach(head, col + 1, 0, 1, 1)
        for row, who in enumerate((tr('Owner'), tr('Group'), tr('Others'))):
            label = Gtk.Label(label=who)
            label.set_alignment(1, 0.5)
            self._paint(label, style.COLOR_BLACK)
            grid.attach(label, 0, row + 1, 1, 1)
            for col in range(3):
                check = Gtk.CheckButton()
                check.set_active(flags[row * 3 + col])
                check.set_sensitive(sensitive)
                check.connect('toggled', self._on_perm_toggled)
                grid.attach(check, col + 1, row + 1, 1, 1)
                self._checks.append(check)
        self._perm_label = Gtk.Label()
        self._perm_label.set_alignment(0, 0.5)
        self._paint(self._perm_label, style.COLOR_BLACK)
        grid.attach(self._perm_label, 0, 4, 4, 1)
        self._on_perm_toggled()
        frame.add(grid)
        return frame

    def _perm_bits(self):
        return fileprops.bits_from_flags([c.get_active()
                                          for c in self._checks])

    def _on_perm_toggled(self, _check=None):
        bits = self._perm_bits()
        self._perm_label.set_text('%s   %04o' % (fileprops.mode_string(bits),
                                                 bits))

    # ------------------------------------------------------------------

    def _close(self, accept):
        if accept and not self._apply():
            return
        self.destroy()
        if self._on_done is not None:
            self._on_done()

    def _apply(self):
        """Aplica los cambios; ``False`` (y el aviso) si algo falla, dejando
        el diálogo abierto."""
        info = self.info
        try:
            fileprops.apply_changes(
                info, perm_bits=self._perm_bits(),
                owner=self._owner.get_text().strip() or None,
                group=self._group.get_child().get_text().strip() or None)
            if self._star is not None:
                favorites.set_favorite(info.path, self._star.get_active())
        except (fileops.FileOpError, IOError, OSError) as exc:
            self._error.set_text(str(exc))
            self._error.show()
            return False
        return True


def _escape(text):
    return (text.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))


def _items_text(count):
    return i18n.ntr('%d item', '%d items', count) % count


def _size_text(size):
    text = i18n.decimal(fileops.human_size(size))
    if size >= 1024:
        text += ' (%s)' % (i18n.ntr('%d byte', '%d bytes', size) % size)
    return text
