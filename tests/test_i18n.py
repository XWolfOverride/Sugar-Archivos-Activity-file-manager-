# -*- coding: utf-8 -*-
"""Pruebas de i18n (gettext sobre .po) y de que las traducciones están completas."""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tools'))

import i18n  # noqa: E402

PO = b'''# comentario del traductor
msgid ""
msgstr ""
"Project-Id-Version: prueba\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"

#: x.py:1
msgid "Open"
msgstr "Abrir"

msgid "Line one\\nLine two"
msgstr "Linea uno\\nLinea dos"

msgid "Say \\"hi\\" \\\\ now"
msgstr "Di \\"hola\\" \\\\ ahora"

msgid "A very long text that the translator "
"split in two lines"
msgstr "Un texto muy largo que el traductor "
"partio en dos lineas"

#, fuzzy
msgid "Dudoso"
msgstr "Raro"

msgid "Vacio"
msgstr ""

#, python-format
msgid "%d file"
msgid_plural "%d files"
msgstr[0] "%d archivo"
msgstr[1] "%d archivos"

msgctxt "menu"
msgid "Copy"
msgstr "Copiar (menu)"

#~ msgid "Obsoleto"
#~ msgstr "Obsoleto"

msgid "DECIMAL_SEPARATOR"
msgstr ","
'''

PO_PLURAL3 = b'''msgid ""
msgstr ""
"Plural-Forms: nplurals=3; plural=(n==1 ? 0 : n>=2 && n<=4 ? 1 : 2);\\n"

msgid "%d day"
msgid_plural "%d days"
msgstr[0] "%d den"
msgstr[1] "%d dny"
msgstr[2] "%d dnu"
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='archivos-i18n-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def po(self, name, data):
        path = os.path.join(self.tmp, name + '.po')
        with open(path, 'wb') as handle:
            handle.write(data)
        return path


class ParserTests(Base):
    def setUp(self):
        Base.setUp(self)
        self.catalog = i18n.Catalog(i18n.parse_po(PO))

    def test_simple_and_escapes(self):
        self.assertEqual(self.catalog.gettext('Open'), 'Abrir')
        self.assertEqual(self.catalog.gettext('Line one\nLine two'),
                         'Linea uno\nLinea dos')
        self.assertEqual(self.catalog.gettext('Say "hi" \\ now'),
                         'Di "hola" \\ ahora')

    def test_multiline_strings_are_joined(self):
        self.assertEqual(
            self.catalog.gettext('A very long text that the translator '
                                 'split in two lines'),
            'Un texto muy largo que el traductor partio en dos lineas')

    def test_fuzzy_and_empty_are_not_used(self):
        self.assertEqual(self.catalog.gettext('Dudoso'), 'Dudoso')
        self.assertEqual(self.catalog.gettext('Vacio'), 'Vacio')

    def test_obsolete_entries_are_ignored(self):
        self.assertEqual(self.catalog.gettext('Obsoleto'), 'Obsoleto')

    def test_unknown_text_is_returned_as_is(self):
        self.assertEqual(self.catalog.gettext('No existe'), 'No existe')

    def test_plural_forms(self):
        for n, expected in ((0, '0 archivos'), (1, '1 archivo'),
                            (2, '2 archivos'), (21, '21 archivos')):
            self.assertEqual(
                self.catalog.ngettext('%d file', '%d files', n) % n, expected)

    def test_plural_untranslated_falls_back_to_english(self):
        self.assertEqual(self.catalog.ngettext('%d cat', '%d cats', 1), '%d cat')
        self.assertEqual(self.catalog.ngettext('%d cat', '%d cats', 3),
                         '%d cats')

    def test_three_plural_forms_from_the_header(self):
        catalog = i18n.Catalog(i18n.parse_po(PO_PLURAL3))
        picks = [catalog.ngettext('%d day', '%d days', n) % n
                 for n in (1, 3, 5, 22)]
        # regla de la cabecera de la prueba: 1 -> 0; 2..4 -> 1; el resto -> 2
        self.assertEqual(picks, ['1 den', '3 dny', '5 dnu', '22 dnu'])

    def test_header_entry_fields(self):
        entries = i18n.parse_po(PO)
        header = [e for e in entries if e.msgid == ''][0]
        self.assertIn('Plural-Forms', header.msgstr[0])
        flagged = [e for e in entries if e.msgid == 'Dudoso'][0]
        self.assertTrue(flagged.fuzzy)
        plural = [e for e in entries if e.msgid_plural][0]
        self.assertEqual(plural.forms(), ['%d archivo', '%d archivos'])
        self.assertEqual(plural.refs, [])
        ref = [e for e in entries if e.msgid == 'Open'][0]
        self.assertEqual(ref.refs, ['x.py:1'])


class LanguageTests(Base):
    def test_candidates(self):
        env = {'LANG': 'es_ES.utf8'}
        self.assertEqual(i18n.language_candidates(env), ['es_ES', 'es'])
        env = {'LANGUAGE': 'ca:es_ES', 'LANG': 'en_US.UTF-8'}
        self.assertEqual(i18n.language_candidates(env),
                         ['ca', 'es_ES', 'es', 'en_US', 'en'])
        self.assertEqual(i18n.language_candidates({'LANG': 'C'}), [])
        self.assertEqual(i18n.language_candidates({'LANG': 'de_DE@euro'}),
                         ['de_DE', 'de'])
        self.assertEqual(i18n.language_candidates({}), [])

    def test_forced_language_wins(self):
        env = {'ARCHIVOS_LANG': 'pt_BR', 'LANG': 'es_ES.utf8'}
        self.assertEqual(i18n.language_candidates(env), ['pt_BR', 'pt'])

    def test_translator_prefers_the_specific_file(self):
        self.po('es', b'msgid "A"\nmsgstr "general"\n')
        self.po('es_ES', b'msgid "A"\nmsgstr "espana"\n')
        self.assertEqual(
            i18n.Translator(self.tmp, ['es_ES', 'es']).tr('A'), 'espana')
        self.assertEqual(i18n.Translator(self.tmp, ['es_MX', 'es']).tr('A'),
                         'general')

    def test_without_catalog_it_is_english(self):
        translator = i18n.Translator(self.tmp, ['fr'])
        self.assertTrue(translator.language is None)
        self.assertEqual(translator.tr('Open'), 'Open')
        self.assertEqual(translator.ntr('%d file', '%d files', 1), '%d file')
        self.assertEqual(translator.ntr('%d file', '%d files', 2), '%d files')

    def test_broken_po_does_not_crash(self):
        self.po('xx', b'esto no es un po \xff\xfe\n"suelta"\nmsgstr\n')
        translator = i18n.Translator(self.tmp, ['xx'])
        self.assertEqual(translator.tr('Open'), 'Open')

    def test_decimal_separator(self):
        self.po('es', PO)
        spanish = i18n.Translator(self.tmp, ['es'])
        self.assertEqual(spanish.decimal('12.4 MB'), '12,4 MB')
        self.assertEqual(i18n.Translator(self.tmp, ['fr']).decimal('12.4 MB'),
                         '12.4 MB')


class ActivityTranslatorTests(unittest.TestCase):
    """El traductor de la actividad lee po/es.po y se rehace al cambiar el idioma."""

    def setUp(self):
        self._saved = dict((k, os.environ.get(k)) for k in i18n._ENV_KEYS)
        self.addCleanup(self._restore)

    def _restore(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_switching_language_at_runtime(self):
        os.environ['ARCHIVOS_LANG'] = 'es'
        self.assertEqual(i18n.tr('Open'), 'Abrir')
        os.environ['ARCHIVOS_LANG'] = 'en'
        self.assertEqual(i18n.tr('Open'), 'Open')
        os.environ['ARCHIVOS_LANG'] = 'es'
        self.assertEqual(i18n.tr('Open'), 'Abrir')

    def test_plurals_and_numbers_in_spanish_and_english(self):
        os.environ['ARCHIVOS_LANG'] = 'es'
        self.assertEqual(i18n.ntr('%d folder', '%d folders', 1) % 1,
                         '1 carpeta')
        self.assertEqual(i18n.ntr('%d folder', '%d folders', 3) % 3,
                         '3 carpetas')
        self.assertEqual(i18n.decimal('12.4 MB'), '12,4 MB')
        os.environ['ARCHIVOS_LANG'] = 'en'
        self.assertEqual(i18n.ntr('%d folder', '%d folders', 3) % 3,
                         '3 folders')
        self.assertEqual(i18n.decimal('12.4 MB'), '12.4 MB')

    def test_status_sentence(self):
        os.environ['ARCHIVOS_LANG'] = 'es'
        text = i18n.tr('%(folders)s and %(size)s in %(files)s') % {
            'folders': '3 carpetas', 'size': '12,4 MB', 'files': '5 archivos'}
        self.assertEqual(text, '3 carpetas y 12,4 MB en 5 archivos')


class CompletenessTests(unittest.TestCase):
    """Cada texto del código está en los .po y está traducido (actividad y plugins)."""

    def test_all_po_files_are_complete_and_consistent(self):
        import translate
        problems = []
        for name, folder, main, po_dir in translate.domains():
            problems += translate.check_domain(name, folder, main, po_dir)
        self.assertEqual(problems, [])

    def test_every_plugin_has_a_spanish_catalog(self):
        import translate
        for name, _folder, _main, po_dir in translate.domains():
            self.assertIn('es', translate.po_languages(po_dir), name)


if __name__ == '__main__':
    unittest.main()
