# -*- coding: utf-8 -*-
"""Pruebas de videoutil (ayudas del reproductor de vídeo), sin pantalla."""
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'plugins', 'video'))

import videoutil  # noqa: E402

NS = videoutil.NS


class ScoreTests(unittest.TestCase):
    def test_ogg_and_webm_open_with_a_click(self):
        for ctype in ('video/ogg', 'video/webm', 'video/x-theora+ogg'):
            self.assertGreaterEqual(videoutil.score_for(ctype), 50)

    def test_generic_ogg_is_still_a_click(self):
        self.assertGreaterEqual(videoutil.score_for('application/ogg'), 50)

    def test_matroska_is_only_an_option(self):
        score = videoutil.score_for('video/x-matroska')
        self.assertTrue(0 < score < 50)

    def test_unsupported_types_are_not_claimed(self):
        for ctype in ('video/mp4', 'video/x-msvideo', 'text/plain', '', None):
            self.assertEqual(videoutil.score_for(ctype), 0)


class Mp3Tests(unittest.TestCase):
    def test_mp3_with_decoder_opens_with_a_click(self):
        for ctype in ('audio/mpeg', 'audio/mp3'):
            self.assertEqual(videoutil.score_for(ctype, mp3=True), 100)

    def test_mp3_without_decoder_is_only_an_option(self):
        score = videoutil.score_for('audio/mpeg', mp3=False)
        self.assertTrue(0 < score < 50)

    def test_decoder_detection_by_plugin_file(self):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        self.assertFalse(videoutil.mp3_decoder_available([tmp, '/no/existe']))
        open(os.path.join(tmp, 'libgstlibav.so'), 'w').close()
        self.assertTrue(videoutil.mp3_decoder_available(['/no/existe', tmp]))


class ModuleTests(unittest.TestCase):
    def test_modules_with_decoder_open_with_a_click(self):
        for ctype in ('audio/x-mod', 'audio/x-xm', 'audio/x-it', 'audio/x-s3m',
                      'audio/x-stm'):
            self.assertEqual(videoutil.score_for(ctype, modules=True), 100)

    def test_modules_without_decoder_are_only_an_option(self):
        score = videoutil.score_for('audio/x-xm', modules=False)
        self.assertTrue(0 < score < 50)

    def test_mp3_flag_does_not_enable_modules(self):
        self.assertTrue(videoutil.score_for('audio/x-mod', mp3=True) < 50)

    def test_module_decoder_detection(self):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        self.assertFalse(videoutil.module_decoder_available([tmp]))
        open(os.path.join(tmp, 'libgstmodplug.so'), 'w').close()
        self.assertTrue(videoutil.module_decoder_available([tmp]))
        self.assertFalse(videoutil.mp3_decoder_available([tmp]))


class TimeTests(unittest.TestCase):
    def test_format(self):
        self.assertEqual(videoutil.format_time(0), '0:00')
        self.assertEqual(videoutil.format_time(None), '0:00')
        self.assertEqual(videoutil.format_time(-5 * NS), '0:00')
        self.assertEqual(videoutil.format_time(9 * NS + NS // 2), '0:09')
        self.assertEqual(videoutil.format_time(75 * NS), '1:15')
        self.assertEqual(videoutil.format_time(3725 * NS), '1:02:05')


class SeekTests(unittest.TestCase):
    def test_forward_and_back(self):
        self.assertEqual(videoutil.seek_target(10 * NS, 5, 60 * NS), 15 * NS)
        self.assertEqual(videoutil.seek_target(10 * NS, -5, 60 * NS), 5 * NS)

    def test_clamped_to_the_ends(self):
        self.assertEqual(videoutil.seek_target(2 * NS, -30, 60 * NS), 0)
        self.assertEqual(videoutil.seek_target(50 * NS, 30, 60 * NS), 60 * NS)

    def test_unknown_duration_only_clamps_at_zero(self):
        self.assertEqual(videoutil.seek_target(50 * NS, 30, 0), 80 * NS)
        self.assertEqual(videoutil.seek_target(1 * NS, -9, 0), 0)


if __name__ == '__main__':
    unittest.main()
