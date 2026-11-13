# -*- coding: utf-8 -*-
"""Contrato de los plugins de Archivos (sin GTK).

Un plugin es una carpeta con un ``plugin.py`` que define una clase ``Plugin``
(subclase de ``pluginapi.Plugin``). Sirve para ABRIR archivos dentro de la
actividad, en una pestaña que el propio plugin controla::

    plugins/
        miplugin/
            plugin.py        la clase Plugin
            po/es.po         sus traducciones (opcional)
            icons/*.svg      sus iconos (opcional)
            miplugin_util.py módulos auxiliares (nombres únicos: sys.path común)

La actividad busca plugins en ``plugins/`` (los que trae), en la carpeta de datos
del usuario (``<datos de la actividad>/plugins``) y en las de la variable
``ARCHIVOS_PLUGIN_PATH`` (separadas por ``:``, útil para desarrollar).

Qué decide un plugin
    ``handles(path, content_type)`` devuelve una puntuación:
        0       no sabe abrirlo;
        1-49    puede abrirlo, pero solo como opción («Abrir con» del menú);
        50-100  es una buena opción: el mejor de ellos se usa al hacer clic.
    Cuantos más plugins, más entradas aparecen en «Abrir con».

Qué hace la actividad con él
    ``open_tab(path)`` crea una pestaña (``pluginui.PluginTab``) que se añade a
    las demás; desde ahí manda el plugin: su interfaz, su título, sus cambios
    sin guardar y su estado (se guarda en el Diario y se recupera al reanudar).

Compatibilidad: ``API_VERSION`` sube cuando el contrato cambia de forma
incompatible; un plugin con otra versión no se carga (queda anotado el error).
"""
import os

import i18n

API_VERSION = 1
DEFAULT_THRESHOLD = 50       # puntuación mínima para abrirse con un simple clic


class Plugin(object):
    id = ''                  # único; si falta se usa el nombre de la carpeta
    name = ''                # nombre visible, en inglés (se traduce con self.tr)
    api_version = API_VERSION

    def __init__(self, host, directory):
        self.host = host
        self.directory = directory
        self._translator = i18n.make_translator(
            os.path.join(directory, 'po'))

    # ---- traducciones propias del plugin ---------------------------------

    def tr(self, text):
        return self._translator.tr(text)

    def ntr(self, singular, plural, number):
        return self._translator.ntr(singular, plural, number)

    def display_name(self):
        return self.tr(self.name or self.id)

    # ---- a sobrescribir ---------------------------------------------------

    def handles(self, path, content_type):
        """Puntuación (0-100) con la que este plugin abre ``path``."""
        return 0

    def open_tab(self, path):
        """Devuelve la pestaña (``PluginTab``) que muestra ``path``."""
        raise NotImplementedError

    def restore_tab(self, path, state):
        """Pestaña recuperada del Diario (por defecto, abrir y restaurar)."""
        tab = self.open_tab(path)
        tab.restore_state(state)
        return tab
