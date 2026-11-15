# -*- coding: utf-8 -*-
"""Pruebas de los sitios (unidades extraíbles)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..'))

import places  # noqa: E402


class PathTests(unittest.TestCase):
    def test_usb_mount_points(self):
        self.assertTrue(places.is_removable_path('/run/media/olpc/USB'))
        self.assertTrue(places.is_removable_path('/run/media/olpc/USB/'))
        self.assertTrue(places.is_removable_path('/media/USB'))

    def test_other_places_are_not_removable(self):
        for path in ('/', '/home/olpc', '/mnt/sd', '/run/media',
                     '/run/media/', '/media', '/run/mediax/a', '/usr'):
            self.assertFalse(places.is_removable_path(path), path)


class MountsTests(unittest.TestCase):
    def test_returns_sorted_existing_folders(self):
        found = places.removable_mounts()     # puede estar vacía
        self.assertEqual(found, sorted(found, key=lambda e: e[1]))
        for name, path, _uuid in found:
            self.assertTrue(name)
            self.assertTrue(os.path.isdir(path))
            self.assertTrue(places.is_removable_path(path))


if __name__ == '__main__':
    unittest.main()
