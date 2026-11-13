# -*- coding: utf-8 -*-
"""Pruebas de textio (lectura/escritura del editor), sin pantalla."""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'plugins', 'text'))

import textio  # noqa: E402


def write(path, data):
    with open(path, 'wb') as handle:
        handle.write(data)


def read(path):
    with open(path, 'rb') as handle:
        return handle.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='archivos-text-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def p(self, name):
        return os.path.join(self.tmp, name)


class DecodeTests(unittest.TestCase):
    def test_utf8(self):
        text, enc, eol, bom = textio.decode(u'canción\nñandú\n'.encode('utf-8'))
        self.assertEqual((text, enc, eol, bom),
                         (u'canción\nñandú\n', 'utf-8', 'LF', False))

    def test_utf8_bom_is_stripped_and_remembered(self):
        data = b'\xef\xbb\xbfhola\n'
        text, enc, eol, bom = textio.decode(data)
        self.assertEqual((text, enc, bom), (u'hola\n', 'utf-8', True))

    def test_latin1_fallback_never_loses_bytes(self):
        data = u'canción'.encode('latin-1')
        text, enc, _eol, bom = textio.decode(data)
        self.assertEqual((text, enc, bom), (u'canción', 'latin-1', False))

    def test_eol_detection_and_normalization(self):
        text, _e, eol, _b = textio.decode(b'a\r\nb\r\nc\r\n')
        self.assertEqual((text, eol), (u'a\nb\nc\n', 'CRLF'))
        text, _e, eol, _b = textio.decode(b'a\rb\rc\r')
        self.assertEqual((text, eol), (u'a\nb\nc\n', 'CR'))
        text, _e, eol, _b = textio.decode(b'a\nb\nc\n')
        self.assertEqual((text, eol), (u'a\nb\nc\n', 'LF'))

    def test_mixed_endings_use_the_majority_and_normalize_all(self):
        text, _e, eol, _b = textio.decode(b'a\r\nb\r\nc\nd\n')
        self.assertEqual((text, eol), (u'a\nb\nc\nd\n', 'CRLF'))
        text, _e, eol, _b = textio.decode(b'a\nb\nc\nd\r\n')
        self.assertEqual((text, eol), (u'a\nb\nc\nd\n', 'LF'))

    def test_no_newline_at_all_is_lf(self):
        self.assertEqual(textio.decode(b'hola')[2], 'LF')


class EncodeTests(unittest.TestCase):
    def doc(self, **kw):
        doc = textio.Document()
        for key, value in kw.items():
            setattr(doc, key, value)
        return doc

    def test_roundtrip_keeps_everything(self):
        for raw in (b'a\nb\n', b'a\r\nb\r\n', b'a\rb\r', b'\xef\xbb\xbfx\n',
                    u'canción\n'.encode('latin-1'),
                    u'canción\r\n'.encode('utf-8')):
            text, enc, eol, bom = textio.decode(raw)
            doc = self.doc(encoding=enc, eol=eol, bom=bom)
            data, used = textio.encode(text, doc)
            self.assertEqual(data, raw)
            self.assertEqual(used, enc)

    def test_characters_latin1_cannot_store_switch_to_utf8(self):
        doc = self.doc(encoding='latin-1')
        data, used = textio.encode(u'caf\xe9 €', doc)
        self.assertEqual(used, 'utf-8')
        self.assertEqual(data.decode('utf-8'), u'caf\xe9 €')

    def test_bom_is_not_added_to_latin1(self):
        doc = self.doc(encoding='latin-1', bom=True)
        data, _used = textio.encode(u'x', doc)
        self.assertEqual(data, b'x')


class FileTests(Base):
    def test_read_document(self):
        write(self.p('a.txt'), u'hola ñ\r\n'.encode('utf-8'))
        doc = textio.read_document(self.p('a.txt'))
        self.assertEqual((doc.text, doc.eol, doc.encoding),
                         (u'hola ñ\n', 'CRLF', 'utf-8'))
        self.assertEqual(doc.size, os.path.getsize(self.p('a.txt')))

    def test_binary_and_too_big_are_refused(self):
        write(self.p('b.bin'), b'abc\0def')
        with self.assertRaises(textio.TextError) as caught:
            textio.read_document(self.p('b.bin'))
        self.assertEqual(caught.exception.code, 'binary')
        write(self.p('big.txt'), b'x' * (textio.MAX_SIZE + 1))
        with self.assertRaises(textio.TextError) as caught:
            textio.read_document(self.p('big.txt'))
        self.assertEqual(caught.exception.code, 'too-big')

    def test_missing_file(self):
        with self.assertRaises(textio.TextError) as caught:
            textio.read_document(self.p('no-existe'))
        self.assertEqual(caught.exception.code, 'read')

    def test_save_is_atomic_and_keeps_the_mode(self):
        write(self.p('a.txt'), b'viejo\n')
        os.chmod(self.p('a.txt'), 0o640)
        doc = textio.read_document(self.p('a.txt'))
        textio.save_document(self.p('a.txt'), u'nuevo ñ\n', doc)
        self.assertEqual(read(self.p('a.txt')), u'nuevo ñ\n'.encode('utf-8'))
        self.assertEqual(os.stat(self.p('a.txt')).st_mode & 0o777, 0o640)
        self.assertEqual(os.listdir(self.tmp), ['a.txt'])      # sin temporales

    def test_save_keeps_crlf_and_updates_the_document(self):
        write(self.p('w.txt'), b'a\r\nb\r\n')
        doc = textio.read_document(self.p('w.txt'))
        textio.save_document(self.p('w.txt'), u'a\nb\nc\n', doc)
        self.assertEqual(read(self.p('w.txt')), b'a\r\nb\r\nc\r\n')
        self.assertFalse(textio.changed_on_disk(self.p('w.txt'), doc))

    def test_save_through_a_symlink_writes_the_target(self):
        write(self.p('real.txt'), b'x')
        os.symlink('real.txt', self.p('enlace.txt'))
        doc = textio.read_document(self.p('enlace.txt'))
        textio.save_document(self.p('enlace.txt'), u'y', doc)
        self.assertTrue(os.path.islink(self.p('enlace.txt')))
        self.assertEqual(read(self.p('real.txt')), b'y')

    def test_save_into_a_missing_folder_fails_cleanly(self):
        doc = textio.Document()
        with self.assertRaises(textio.TextError) as caught:
            textio.save_document(self.p('no/existe.txt'), u'x', doc)
        self.assertEqual(caught.exception.code, 'write')
        self.assertEqual(os.listdir(self.tmp), [])

    def test_new_file_can_be_saved(self):
        doc = textio.Document()
        textio.save_document(self.p('nuevo.txt'), u'hola\n', doc)
        self.assertEqual(read(self.p('nuevo.txt')), b'hola\n')

    def test_changed_on_disk(self):
        write(self.p('a.txt'), b'uno')
        doc = textio.read_document(self.p('a.txt'))
        self.assertFalse(textio.changed_on_disk(self.p('a.txt'), doc))
        write(self.p('a.txt'), b'dos mas largo')
        self.assertTrue(textio.changed_on_disk(self.p('a.txt'), doc))
        os.unlink(self.p('a.txt'))
        self.assertTrue(textio.changed_on_disk(self.p('a.txt'), doc))


if __name__ == '__main__':
    unittest.main()
