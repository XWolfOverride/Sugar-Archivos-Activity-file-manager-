# -*- coding: utf-8 -*-
"""Pruebas de las carpetas favoritas y de las propiedades."""
import os
import shutil
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..'))

import favorites  # noqa: E402
import fileops  # noqa: E402
import fileprops  # noqa: E402


class FavoritesTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.store = os.path.join(self.root, 'cfg', 'favorites.json')

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_empty_when_missing_or_broken(self):
        self.assertEqual(favorites.load(self.store), [])
        os.makedirs(os.path.dirname(self.store))
        with open(self.store, 'w') as f:
            f.write('{no es json')
        self.assertEqual(favorites.load(self.store), [])

    def test_add_remove_no_duplicates(self):
        favorites.add('/a/b/', self.store)
        favorites.add('/a/b', self.store)
        favorites.add('/c', self.store)
        self.assertEqual(favorites.load(self.store), ['/a/b', '/c'])
        self.assertTrue(favorites.is_favorite('/a/b/', self.store))
        favorites.remove('/a/b', self.store)
        self.assertEqual(favorites.load(self.store), ['/c'])
        favorites.set_favorite('/c', False, self.store)
        self.assertEqual(favorites.load(self.store), [])

    def test_utf8_names(self):
        path = '/tmp/Canci\xc3\xb3n'
        favorites.add(path, self.store)
        self.assertEqual(favorites.load(self.store), [path])

    def test_remove_missing(self):
        real = os.path.join(self.root, 'real')
        os.makedirs(real)
        favorites.add(real, self.store)
        favorites.add(os.path.join(self.root, 'gone'), self.store)
        self.assertEqual(favorites.remove_missing(self.store), 1)
        self.assertEqual(favorites.load(self.store), [real])


class PropsTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.path = os.path.join(self.root, 'f.txt')
        with open(self.path, 'w') as f:
            f.write('hola')
        os.chmod(self.path, 0o644)

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_describe(self):
        info = fileprops.describe(self.path)
        self.assertEqual(info.name, 'f.txt')
        self.assertFalse(info.is_dir)
        self.assertEqual(info.size, 4)
        self.assertEqual(info.mode, 0o644)
        self.assertEqual(info.uid, os.getuid())
        self.assertEqual(fileprops.describe(self.root).items, 1)

    def test_missing(self):
        self.assertRaises(fileops.FileOpError, fileprops.describe,
                          os.path.join(self.root, 'no'))

    def test_mode_helpers(self):
        self.assertEqual(fileprops.mode_string(0o754), 'rwxr-xr--')
        flags = fileprops.flags_from_mode(0o640)
        self.assertEqual(fileprops.bits_from_flags(flags), 0o640)

    def test_chmod_keeps_special_bits(self):
        os.chmod(self.path, 0o2644)
        info = fileprops.describe(self.path)
        n = fileprops.apply_changes(info, perm_bits=0o600)
        self.assertEqual(n, 1)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o2600)

    def test_no_change_does_nothing(self):
        info = fileprops.describe(self.path)
        self.assertEqual(fileprops.apply_changes(
            info, perm_bits=0o644, owner=info.owner, group=info.group), 0)

    def test_unknown_group(self):
        info = fileprops.describe(self.path)
        self.assertRaises(fileops.FileOpError, fileprops.apply_changes,
                          info, group='no-existe-ese-grupo')


if __name__ == '__main__':
    unittest.main()
