# -*- coding: utf-8 -*-
"""Pruebas de las actividades de Sugar que abren archivos."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..'))

import sugaractivities  # noqa: E402


def make_activity(root, folder, bundle_id, name, mimes):
    path = os.path.join(root, folder)
    os.makedirs(os.path.join(path, 'activity'))
    with open(os.path.join(path, 'activity', 'activity.info'), 'w') as f:
        f.write('[Activity]\nname = %s\nbundle_id = %s\nmime_types = %s\n' %
                (name, bundle_id, mimes))
    return path


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_reads_name_id_and_types(self):
        path = make_activity(self.root, 'Read.activity', 'org.x.Read', 'Read',
                             'application/pdf;image/tiff;')
        act = sugaractivities.parse_info(path)
        self.assertEqual(act.name, 'Read')
        self.assertEqual(act.bundle_id, 'org.x.Read')
        self.assertEqual(act.mime_types, ['application/pdf', 'image/tiff'])

    def test_empty_types(self):
        path = make_activity(self.root, 'A.activity', 'org.x.A', 'A', '')
        self.assertEqual(sugaractivities.parse_info(path).mime_types, [])

    def test_not_an_activity(self):
        os.makedirs(os.path.join(self.root, 'x.activity'))
        self.assertIsNone(
            sugaractivities.parse_info(os.path.join(self.root, 'x.activity')))
        self.assertIsNone(sugaractivities.parse_info('/no/existe'))

    def test_broken_info(self):
        path = os.path.join(self.root, 'B.activity')
        os.makedirs(os.path.join(path, 'activity'))
        with open(os.path.join(path, 'activity', 'activity.info'), 'w') as f:
            f.write('esto no es un ini\n')
        self.assertIsNone(sugaractivities.parse_info(path))


class InstalledTests(unittest.TestCase):
    def setUp(self):
        self.a = tempfile.mkdtemp()
        self.b = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.a)
        shutil.rmtree(self.b)

    def test_sorted_by_name_and_first_root_wins(self):
        make_activity(self.a, 'Zeta.activity', 'org.x.Z', 'Zeta', '')
        make_activity(self.a, 'Alfa.activity', 'org.x.A', 'Alfa', '')
        make_activity(self.b, 'Alfa2.activity', 'org.x.A', 'Duplicada', '')
        make_activity(self.b, 'Beta.activity', 'org.x.B', 'beta', '')
        found = sugaractivities.installed([self.a, self.b])
        self.assertEqual([x.name for x in found], ['Alfa', 'beta', 'Zeta'])

    def test_ignores_non_activities_and_missing_roots(self):
        os.makedirs(os.path.join(self.a, 'carpeta'))
        found = sugaractivities.installed([self.a, '/no/existe'])
        self.assertEqual(found, [])


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.acts = [
            sugaractivities.SugarActivity('/r', 'Read', 'org.x.Read',
                                          ['application/pdf', 'text/plain',
                                           'application/zip']),
            sugaractivities.SugarActivity('/w', 'Write', 'org.x.Write',
                                          ['text/plain']),
        ]

    def test_exact_type(self):
        found = sugaractivities.handlers_for('application/pdf',
                                             activities=self.acts)
        self.assertEqual([a.name for a in found], ['Read'])

    def test_strict_ignores_generic_types(self):
        self.assertEqual(sugaractivities.handlers_for(
            'text/plain', strict=True, activities=self.acts), [])
        self.assertEqual(sugaractivities.handlers_for(
            'application/zip', strict=True, activities=self.acts), [])

    def test_not_strict_offers_generic_types(self):
        found = sugaractivities.handlers_for('text/plain',
                                             activities=self.acts)
        self.assertEqual([a.name for a in found], ['Read', 'Write'])

    def test_unknown_and_empty(self):
        self.assertEqual(sugaractivities.handlers_for(
            'video/mp4', activities=self.acts), [])
        self.assertEqual(sugaractivities.handlers_for(
            '', activities=self.acts), [])
        self.assertEqual(sugaractivities.handlers_for(
            None, activities=self.acts), [])


class RootsTests(unittest.TestCase):
    def test_roots_include_user_and_system(self):
        roots = sugaractivities.search_roots()
        self.assertIn('/usr/share/sugar/activities', roots)
        self.assertTrue(any(r.endswith('Activities') for r in roots))


if __name__ == '__main__':
    unittest.main()
