# -*- coding: utf-8 -*-
"""Descubre, carga y elige plugins (sin GTK, se prueba sin pantalla)."""
import imp
import logging
import os
import sys
import traceback

import pluginapi

_LOG = logging.getLogger('archivos.plugins')


def default_directories(bundle_path, data_dir=None):
    """Carpetas de plugins, por orden: los de la actividad, los del usuario y
    los de ``ARCHIVOS_PLUGIN_PATH``. Si un id se repite, gana el primero."""
    found = [os.path.join(bundle_path, 'plugins')]
    if data_dir:
        found.append(os.path.join(data_dir, 'plugins'))
    extra = os.environ.get('ARCHIVOS_PLUGIN_PATH', '')
    found += [d for d in extra.split(':') if d]
    return found


class PluginManager(object):

    def __init__(self, host, directories):
        self._host = host
        self._directories = list(directories)
        self._plugins = []
        self.errors = []            # [(id o carpeta, texto del error)]

    # ---- carga -------------------------------------------------------------

    def load_all(self):
        for directory in self._directories:
            if not os.path.isdir(directory):
                continue
            for name in sorted(os.listdir(directory)):
                folder = os.path.join(directory, name)
                if os.path.isfile(os.path.join(folder, 'plugin.py')):
                    self._load(name, folder)
        return self

    def _fail(self, name, text):
        self.errors.append((name, text))
        _LOG.warning('plugin %s no cargado: %s', name, text.strip()[-300:])

    def _load(self, name, folder):
        if folder not in sys.path:
            sys.path.insert(0, folder)      # para sus módulos auxiliares
        try:
            module = imp.load_source('archivos_plugin_' + name,
                                     os.path.join(folder, 'plugin.py'))
            cls = getattr(module, 'Plugin')
            if not (isinstance(cls, type)
                    and issubclass(cls, pluginapi.Plugin)):
                raise TypeError('Plugin no es una subclase de '
                                'pluginapi.Plugin')
            if cls.api_version != pluginapi.API_VERSION:
                raise ValueError('API %r incompatible (esta actividad usa la '
                                 '%r)' % (cls.api_version,
                                          pluginapi.API_VERSION))
            plugin_id = cls.id or name
            if self.get(plugin_id) is not None:
                raise ValueError('el id %r ya lo usa otro plugin' % plugin_id)
            cls.id = plugin_id
            instance = cls(self._host, folder)
            icons = os.path.join(folder, 'icons')
            if os.path.isdir(icons) and hasattr(self._host, 'add_icon_path'):
                self._host.add_icon_path(icons)
            self._plugins.append(instance)
        except Exception:
            self._fail(name, traceback.format_exc())

    # ---- consulta ------------------------------------------------------------

    def plugins(self):
        return list(self._plugins)

    def get(self, plugin_id):
        for plugin in self._plugins:
            if plugin.id == plugin_id:
                return plugin
        return None

    def candidates(self, path, content_type=''):
        """[(puntuación, plugin)] de los que saben abrir ``path``, mejores antes."""
        scored = []
        for plugin in self._plugins:
            try:
                score = int(plugin.handles(path, content_type))
            except Exception:
                self._fail(plugin.id, traceback.format_exc())
                continue
            if score > 0:
                scored.append((min(score, 100), plugin))
        scored.sort(key=lambda item: (-item[0], item[1].display_name()))
        return scored

    def default_for(self, path, content_type=''):
        """El plugin que abre ``path`` con un simple clic (o None)."""
        for score, plugin in self.candidates(path, content_type):
            if score >= pluginapi.DEFAULT_THRESHOLD:
                return plugin
            break
        return None
