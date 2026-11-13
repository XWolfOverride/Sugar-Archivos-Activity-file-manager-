# -*- coding: utf-8 -*-
"""Base gráfica de las pestañas de plugin (necesita GTK)."""
import os

from gi.repository import Gtk

from sugar3.graphics.icon import Icon


class PluginTab(Gtk.Box):
    """Pestaña controlada por un plugin.

    El plugin hereda de esta clase y rellena la caja (``self.pack_start``). La
    actividad solo usa los métodos de abajo; todos tienen una versión que no
    hace nada o la más sencilla, y el plugin sobrescribe los que le interesan.
    """

    kind = 'plugin'

    def __init__(self, host, plugin, path):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL,
                         spacing=0)
        self.host = host
        self.plugin = plugin
        self.path = path

    # ---- lo que la actividad pregunta o ordena ------------------------------

    def get_title(self):
        return os.path.basename(self.path)

    def title(self):
        # La actividad pide title() a cualquier pestaña (también a las carpetas)
        return ('\xe2\x97\x8f ' if self.is_modified() else '') + self.get_title()

    def get_tooltip(self):
        return self.path

    def is_modified(self):
        """True si hay cambios sin guardar (la actividad avisa al cerrar)."""
        return False

    def save(self):
        """Guarda los cambios. Devuelve True si quedó guardado."""
        return True

    def discard_changes(self):
        """El usuario descartó los cambios: ya no cuentan como pendientes."""

    def get_state(self):
        """Estado para el Diario (solo tipos JSON: números, textos, listas...)."""
        return {}

    def restore_state(self, state):
        """Recupera lo que devolvió ``get_state`` en otra sesión."""

    def set_active(self, active):
        """La pestaña se ve (True) o pasa a segundo plano (False)."""
        (self.on_shown if active else self.on_hidden)()

    def on_shown(self):
        pass

    def on_hidden(self):
        pass

    def toolbar_actions(self):
        """Botones que esta pestaña pone en la barra principal mientras se ve:
        lista de ``(icono, texto, función_sin_argumentos)``."""
        return []

    def dispose(self):
        """Se cierra la pestaña: soltar hilos, memoria, ficheros..."""

    def destroy_view(self):
        self.dispose()

    # ---- lo que el plugin llama ------------------------------------------------

    def title_changed(self):
        """Avisa a la actividad de que el título (o el estado) cambió."""
        self.host.tab_title_changed(self)


def icon_button(icon_name, tooltip, callback, size=32, toggle=False):
    """Botón plano con un icono de Sugar, para las barras de los plugins."""
    button = Gtk.ToggleButton() if toggle else Gtk.Button()
    button.set_relief(Gtk.ReliefStyle.NONE)
    button.set_focus_on_click(False)
    button.add(Icon(icon_name=icon_name, pixel_size=size))
    button.set_tooltip_text(tooltip)
    if callback is not None:
        # sin envoltorio: así el plugin puede bloquearla (handler_block_by_func)
        button.connect('toggled' if toggle else 'clicked', callback)
    button.show_all()
    return button
