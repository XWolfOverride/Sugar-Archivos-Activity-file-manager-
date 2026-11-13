# -*- coding: utf-8 -*-
"""Pruebas del gestor de plugins con plugins buenos y malos fabricados."""
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
os.environ['ARCHIVOS_LANG'] = 'en'

import pluginapi  # noqa: E402
import pluginmgr  # noqa: E402

_N = [0]


def plugin_source(pid, handles='0', extra=''):
    return textwrap.dedent('''
        import pluginapi

        class Plugin(pluginapi.Plugin):
            id = %r
            name = %r

            def handles(self, path, content_type):
                return %s

            def open_tab(self, path):
                return ('tab', self.id, path)
            %s
        ''') % (pid, pid.upper(), handles, extra)


class Host(object):
    def __init__(self):
        self.icons = []

    def add_icon_path(self, path):
        self.icons.append(path)


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='archivos-plug-')
        self.addCleanup(shutil.rmtree, self.root, True)
        self.host = Host()

    def make(self, folder, name, source, files=None):
        directory = os.path.join(self.root, folder, name)
        os.makedirs(directory)
        with open(os.path.join(directory, 'plugin.py'), 'w') as handle:
            handle.write(source)
        for fname, content in (files or {}).items():
            path = os.path.join(directory, fname)
            if not os.path.isdir(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            with open(path, 'w') as handle:
                handle.write(content)
        return directory

    def manager(self, *folders):
        mgr = pluginmgr.PluginManager(
            self.host, [os.path.join(self.root, f) for f in folders])
        return mgr.load_all()


class LoadTests(Base):
    def test_loads_good_plugins_and_skips_folders_without_plugin_py(self):
        self.make('p', 'alpha', plugin_source('alpha'))
        os.makedirs(os.path.join(self.root, 'p', 'vacia'))
        mgr = self.manager('p')
        self.assertEqual([p.id for p in mgr.plugins()], ['alpha'])
        self.assertEqual(mgr.errors, [])

    def test_id_defaults_to_the_folder_name(self):
        source = plugin_source('x').replace("id = 'x'", "id = ''")
        self.make('p', 'carpeta', source)
        self.assertEqual(self.manager('p').plugins()[0].id, 'carpeta')

    def test_bad_plugins_are_isolated_and_reported(self):
        self.make('p', 'bueno', plugin_source('bueno'))
        self.make('p', 'sintaxis', 'esto no es python (((\n')
        self.make('p', 'sinclase', 'X = 1\n')
        self.make('p', 'noheredada', 'class Plugin(object):\n    id = "n"\n')
        self.make('p', 'api', plugin_source('api').replace(
            'class Plugin(pluginapi.Plugin):',
            'class Plugin(pluginapi.Plugin):\n            api_version = 99'))
        self.make('p', 'explota', plugin_source('explota').replace(
            'def handles', 'def __init__(self, h, d):\n'
            '                raise RuntimeError("boom")\n'
            '            def handles'))
        mgr = self.manager('p')
        self.assertEqual([p.id for p in mgr.plugins()], ['bueno'])
        failed = sorted(name for name, _text in mgr.errors)
        self.assertEqual(failed, ['api', 'explota', 'noheredada', 'sinclase',
                                  'sintaxis'])
        self.assertTrue(all(text for _n, text in mgr.errors))

    def test_duplicate_ids_first_wins(self):
        self.make('a', 'uno', plugin_source('mismo'))
        self.make('b', 'dos', plugin_source('mismo'))
        mgr = self.manager('a', 'b')
        self.assertEqual(len(mgr.plugins()), 1)
        self.assertEqual(mgr.plugins()[0].directory,
                         os.path.join(self.root, 'a', 'uno'))
        self.assertEqual([n for n, _t in mgr.errors], ['dos'])

    def test_helper_modules_next_to_plugin_py_can_be_imported(self):
        _N[0] += 1
        helper = 'ayudante_prueba_%d' % _N[0]
        source = plugin_source('conayuda').replace(
            'import pluginapi', 'import pluginapi\nimport %s' % helper)
        self.make('p', 'conayuda', source,
                  files={helper + '.py': 'VALOR = 7\n'})
        mgr = self.manager('p')
        self.assertEqual(mgr.errors, [])
        self.assertEqual([p.id for p in mgr.plugins()], ['conayuda'])

    def test_plugin_icons_folder_is_added_to_the_theme(self):
        self.make('p', 'conicono', plugin_source('conicono'),
                  files={'icons/x.svg': '<svg/>'})
        self.manager('p')
        self.assertEqual(self.host.icons,
                         [os.path.join(self.root, 'p', 'conicono', 'icons')])

    def test_missing_directories_are_fine(self):
        self.assertEqual(self.manager('no-existe').plugins(), [])

    def test_default_directories_and_environment(self):
        os.environ['ARCHIVOS_PLUGIN_PATH'] = '/a:/b::'
        try:
            dirs = pluginmgr.default_directories('/bundle', '/datos')
        finally:
            del os.environ['ARCHIVOS_PLUGIN_PATH']
        self.assertEqual(dirs, ['/bundle/plugins', '/datos/plugins', '/a',
                                '/b'])
        self.assertEqual(pluginmgr.default_directories('/bundle'),
                         ['/bundle/plugins'])


class ChoiceTests(Base):
    def setUp(self):
        Base.setUp(self)
        self.make('p', 'alto', plugin_source(
            'alto', "100 if path.endswith('.txt') else 0"))
        self.make('p', 'medio', plugin_source(
            'medio', "30 if path.endswith('.txt') else "
                     "(60 if path.endswith('.png') else 0)"))
        self.make('p', 'bajo', plugin_source('bajo', '10'))
        self.mgr = self.manager('p')

    def test_candidates_are_sorted_by_score_then_name(self):
        scores = [(s, p.id) for s, p in self.mgr.candidates('a.txt')]
        self.assertEqual(scores, [(100, 'alto'), (30, 'medio'), (10, 'bajo')])
        scores = [(s, p.id) for s, p in self.mgr.candidates('a.png')]
        self.assertEqual(scores, [(60, 'medio'), (10, 'bajo')])

    def test_default_needs_a_good_score(self):
        self.assertEqual(self.mgr.default_for('a.txt').id, 'alto')
        self.assertEqual(self.mgr.default_for('a.png').id, 'medio')
        self.assertTrue(self.mgr.default_for('a.bin') is None)   # solo 10

    def test_scores_are_clamped_and_zero_means_no(self):
        self.make('q', 'enorme', plugin_source('enorme', '5000'))
        mgr = self.manager('q')
        self.assertEqual(mgr.candidates('x')[0][0], 100)
        self.assertEqual(self.mgr.candidates('a.bin')[0][1].id, 'bajo')

    def test_open_tab_goes_through_the_plugin(self):
        plugin = self.mgr.default_for('a.txt')
        self.assertEqual(plugin.open_tab('a.txt'), ('tab', 'alto', 'a.txt'))

    def test_a_plugin_that_fails_in_handles_is_skipped_not_fatal(self):
        self.make('q', 'rota', plugin_source('rota', '1 // 0'))
        mgr = self.manager('p', 'q')
        self.assertEqual(mgr.candidates('a.txt')[0][1].id, 'alto')
        self.assertIn('rota', [n for n, _t in mgr.errors])

    def test_get_by_id(self):
        self.assertEqual(self.mgr.get('medio').id, 'medio')
        self.assertTrue(self.mgr.get('nada') is None)


class PluginTranslationTests(Base):
    def test_each_plugin_has_its_own_translations(self):
        po = ('msgid ""\nmsgstr ""\n"Plural-Forms: nplurals=2; '
              'plural=(n != 1);\\n"\n\nmsgid "PROPIO"\nmsgstr "Mio"\n')
        self.make('p', 'propio', plugin_source('propio'),
                  files={'po/es.po': po})
        plugin = self.manager('p').plugins()[0]
        # el idioma sale del entorno: se fuerza para la prueba
        plugin._translator = pluginapi.i18n.make_translator(
            os.path.join(plugin.directory, 'po'), ['es'])
        self.assertEqual(plugin.display_name(), 'Mio')
        self.assertEqual(plugin.tr('otra'), 'otra')


if __name__ == '__main__':
    unittest.main()
