# -*- coding: utf-8 -*-
"""Pruebas de imgutil (ayudas del visor de imágenes), sin pantalla."""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'plugins', 'image'))

import imgutil  # noqa: E402


class FitTests(unittest.TestCase):
    def test_smaller_images_are_not_enlarged(self):
        self.assertEqual(imgutil.fit_size(300, 200, 1000, 800), (300, 200))

    def test_big_images_keep_their_proportion(self):
        # 4000x3000 en 1000x800: manda el ancho (x0,25) -> 1000x750
        self.assertEqual(imgutil.fit_size(4000, 3000, 1000, 800), (1000, 750))
        self.assertEqual(imgutil.fit_size(4000, 3000, 1200, 900), (1200, 900))
        self.assertEqual(imgutil.fit_size(1000, 4000, 1200, 900), (225, 900))

    def test_degenerate_sizes(self):
        self.assertEqual(imgutil.fit_size(0, 100, 10, 10), (0, 0))
        self.assertEqual(imgutil.fit_size(1, 5000, 100, 100), (1, 100))

    def test_megapixels(self):
        self.assertEqual(imgutil.megapixels(4000, 3000), 12.0)


class SiblingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='archivos-img-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name in ('b.png', 'A.jpg', 'c.txt', '.oculta.png', 'z.PNG'):
            open(os.path.join(self.tmp, name), 'w').close()
        os.mkdir(os.path.join(self.tmp, 'dir.png'))

    def is_image(self, name):
        return name.lower().endswith(('.png', '.jpg'))

    def test_only_images_sorted_ignoring_case_without_hidden_or_folders(self):
        paths, index = imgutil.list_siblings(
            os.path.join(self.tmp, 'b.png'), self.is_image)
        self.assertEqual([os.path.basename(p) for p in paths],
                         ['A.jpg', 'b.png', 'z.PNG'])
        self.assertEqual(index, 1)

    def test_a_missing_or_unlisted_path_is_added(self):
        odd = os.path.join(self.tmp, 'c.txt')
        paths, index = imgutil.list_siblings(odd, self.is_image)
        self.assertIn(odd, paths)
        self.assertEqual(paths[index], odd)

    def test_unreadable_folder(self):
        paths, index = imgutil.list_siblings('/no/existe/x.png',
                                             self.is_image)
        self.assertEqual((paths, index), (['/no/existe/x.png'], 0))


if __name__ == '__main__':
    unittest.main()
