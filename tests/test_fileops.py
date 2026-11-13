# -*- coding: utf-8 -*-
"""Pruebas de fileops (sin pantalla). Ejecutar desde la raíz del proyecto:

    python -m unittest discover -s tests -v
"""
import errno
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ['ARCHIVOS_LANG'] = 'en'

from gi.repository import Gio  # noqa: E402

import fileops  # noqa: E402


def write(path, data='x'):
    with open(path, 'wb') as handle:
        handle.write(data)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='archivos-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def p(self, *parts):
        return os.path.join(self.tmp, *parts)


class ListTests(Base):
    def test_sort_dirs_first_then_name(self):
        os.mkdir(self.p('zeta'))
        os.mkdir(self.p('Alfa'))
        write(self.p('b.txt'))
        write(self.p('A.txt'))
        names = [e.name for e in fileops.list_dir(self.tmp)]
        self.assertEqual(names, ['Alfa', 'zeta', 'A.txt', 'b.txt'])

    def test_hidden_files(self):
        write(self.p('.oculto'))
        write(self.p('visible'))
        write(self.p('copia~'))
        self.assertEqual([e.name for e in fileops.list_dir(self.tmp)],
                         ['visible'])
        names = [e.name for e in fileops.list_dir(self.tmp, True)]
        self.assertEqual(sorted(names), ['.oculto', 'copia~', 'visible'])

    def test_entry_fields(self):
        write(self.p('f.txt'), 'hola')
        os.mkdir(self.p('d'))
        entries = dict((e.name, e) for e in fileops.list_dir(self.tmp))
        self.assertTrue(entries['d'].is_dir)
        self.assertFalse(entries['f.txt'].is_dir)
        self.assertEqual(entries['f.txt'].size, 4)
        self.assertTrue(entries['f.txt'].mtime > 0)
        self.assertTrue(entries['f.txt'].icon is not None)

    def test_symlink_to_dir_is_listed_as_dir(self):
        os.mkdir(self.p('real'))
        os.symlink('real', self.p('enlace'))
        entries = dict((e.name, e) for e in fileops.list_dir(self.tmp))
        self.assertTrue(entries['enlace'].is_dir)
        self.assertTrue(entries['enlace'].is_link)

    def test_unreadable_folder_raises(self):
        self.assertRaises(fileops.FileOpError, fileops.list_dir,
                          self.p('no-existe'))

    def test_non_ascii_names(self):
        write(self.p('canci\xc3\xb3n.txt'))
        names = [e.name for e in fileops.list_dir(self.tmp)]
        self.assertEqual(names, ['canci\xc3\xb3n.txt'])


class ListTypeTests(Base):
    def test_broken_symlink_is_listed_as_a_file(self):
        os.symlink('no-existe', self.p('roto'))
        entries = dict((e.name, e) for e in fileops.list_dir(self.tmp))
        self.assertFalse(entries['roto'].is_dir)
        self.assertTrue(entries['roto'].is_link)

    def test_content_types_by_name(self):
        self.assertEqual(fileops.content_type_for('a.txt'), 'text/plain')
        self.assertEqual(fileops.content_type_for('A.TXT'), 'text/plain')
        self.assertEqual(fileops.content_type_for('x', True),
                         'inode/directory')
        self.assertTrue(fileops.content_type_for('sin-extension'))

    def test_one_icon_object_per_type(self):
        write(self.p('a.txt'))
        write(self.p('b.txt'))
        entries = dict((e.name, e) for e in fileops.list_dir(self.tmp))
        self.assertTrue(entries['a.txt'].icon is entries['b.txt'].icon)

    def test_summarize_counts_folders_files_and_bytes(self):
        os.mkdir(self.p('d1'))
        os.mkdir(self.p('d2'))
        write(self.p('a'), 'x' * 100)
        write(self.p('b'), 'y' * 2000)
        self.assertEqual(fileops.summarize(fileops.list_dir(self.tmp)),
                         (2, 2, 2100))
        self.assertEqual(fileops.summarize([]), (0, 0, 0))

    def test_directories_use_the_folder_icon(self):
        os.mkdir(self.p('d'))
        entry = fileops.list_dir(self.tmp)[0]
        self.assertEqual(entry.icon.get_names()[0], 'folder')

    def test_directory_size_is_zero_and_mtime_is_int(self):
        os.mkdir(self.p('d'))
        entry = fileops.list_dir(self.tmp)[0]
        self.assertEqual(entry.size, 0)
        self.assertTrue(isinstance(entry.mtime, int))


class NameTests(Base):
    def test_unique_name(self):
        self.assertEqual(fileops.unique_name(self.tmp, 'a.txt'), 'a.txt')
        write(self.p('a.txt'))
        self.assertEqual(fileops.unique_name(self.tmp, 'a.txt'), 'a (2).txt')
        write(self.p('a (2).txt'))
        self.assertEqual(fileops.unique_name(self.tmp, 'a.txt'), 'a (3).txt')

    def test_unique_name_tar_gz(self):
        write(self.p('x.tar.gz'))
        self.assertEqual(fileops.unique_name(self.tmp, 'x.tar.gz'),
                         'x (2).tar.gz')

    def test_unique_name_dotfile(self):
        write(self.p('.bashrc'))
        self.assertEqual(fileops.unique_name(self.tmp, '.bashrc'),
                         '.bashrc (2)')

    def test_validate_name(self):
        for bad in ('', '.', '..', 'a/b', 'a\0b'):
            self.assertRaises(fileops.FileOpError, fileops.validate_name, bad)
        self.assertEqual(fileops.validate_name(u'ñ'), '\xc3\xb1')

    def test_human_size(self):
        self.assertEqual(fileops.human_size(0), '0 B')
        self.assertEqual(fileops.human_size(1023), '1023 B')
        self.assertEqual(fileops.human_size(1024), '1.0 KB')
        self.assertEqual(fileops.human_size(5 * 1024 * 1024), '5.0 MB')


class RenameMkdirTests(Base):
    def test_rename(self):
        write(self.p('a'))
        new = fileops.rename(self.p('a'), 'b')
        self.assertEqual(new, self.p('b'))
        self.assertTrue(os.path.exists(self.p('b')))
        self.assertFalse(os.path.exists(self.p('a')))

    def test_rename_same_name_is_noop(self):
        write(self.p('a'))
        self.assertEqual(fileops.rename(self.p('a'), 'a'), self.p('a'))

    def test_rename_refuses_to_overwrite(self):
        write(self.p('a'), '1')
        write(self.p('b'), '2')
        self.assertRaises(fileops.FileOpError, fileops.rename,
                          self.p('a'), 'b')
        self.assertEqual(open(self.p('b')).read(), '2')

    def test_rename_invalid(self):
        write(self.p('a'))
        self.assertRaises(fileops.FileOpError, fileops.rename,
                          self.p('a'), 'x/y')

    def test_make_dir(self):
        path = fileops.make_dir(self.tmp, 'nueva')
        self.assertTrue(os.path.isdir(path))
        self.assertRaises(fileops.FileOpError, fileops.make_dir,
                          self.tmp, 'nueva')


class MakeFileTests(Base):
    def test_make_file_is_empty(self):
        path = fileops.make_file(self.tmp, 'nuevo.txt')
        self.assertEqual(path, self.p('nuevo.txt'))
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.getsize(path), 0)

    def test_make_file_has_normal_permissions(self):
        path = fileops.make_file(self.tmp, 'a')
        mode = os.stat(path).st_mode & 0o777
        self.assertEqual(mode & 0o600, 0o600)

    def test_make_file_never_overwrites(self):
        write(self.p('a'), 'datos')
        self.assertRaises(fileops.FileOpError, fileops.make_file,
                          self.tmp, 'a')
        self.assertEqual(open(self.p('a')).read(), 'datos')

    def test_make_file_refuses_existing_broken_symlink(self):
        os.symlink('no-existe', self.p('roto'))
        self.assertRaises(fileops.FileOpError, fileops.make_file,
                          self.tmp, 'roto')
        self.assertFalse(os.path.exists(self.p('no-existe')))

    def test_make_file_invalid_name_or_folder(self):
        self.assertRaises(fileops.FileOpError, fileops.make_file,
                          self.tmp, 'a/b')
        self.assertRaises(fileops.FileOpError, fileops.make_file,
                          self.p('no-existe'), 'a')

    def test_unique_name_for_new_file(self):
        fileops.make_file(self.tmp, 'Archivo nuevo')
        name = fileops.unique_name(self.tmp, 'Archivo nuevo')
        self.assertEqual(name, 'Archivo nuevo (2)')
        fileops.make_file(self.tmp, name)
        self.assertEqual(len(os.listdir(self.tmp)), 2)


class CopyTests(Base):
    def test_copy_file_keeps_content_mode_and_mtime(self):
        write(self.p('a'), 'datos')
        os.chmod(self.p('a'), 0o640)
        os.utime(self.p('a'), (1000000000, 1000000000))
        os.mkdir(self.p('dest'))
        dst = fileops.copy(self.p('a'), self.p('dest'))
        self.assertEqual(dst, self.p('dest', 'a'))
        self.assertEqual(open(dst).read(), 'datos')
        st = os.stat(dst)
        self.assertEqual(st.st_mode & 0o777, 0o640)
        self.assertEqual(int(st.st_mtime), 1000000000)
        self.assertTrue(os.path.exists(self.p('a')))

    def test_copy_into_same_dir_makes_unique_name(self):
        write(self.p('a.txt'), '1')
        dst = fileops.copy(self.p('a.txt'), self.tmp)
        self.assertEqual(dst, self.p('a (2).txt'))
        self.assertEqual(open(dst).read(), '1')

    def test_copy_never_overwrites(self):
        write(self.p('a'), 'origen')
        os.mkdir(self.p('d'))
        write(self.p('d', 'a'), 'destino')
        dst = fileops.copy(self.p('a'), self.p('d'))
        self.assertEqual(open(self.p('d', 'a')).read(), 'destino')
        self.assertEqual(open(dst).read(), 'origen')

    def test_copy_tree_with_symlink(self):
        os.makedirs(self.p('src', 'sub'))
        write(self.p('src', 'sub', 'f'), 'abc')
        os.symlink('sub/f', self.p('src', 'enlace'))
        os.mkdir(self.p('dest'))
        dst = fileops.copy(self.p('src'), self.p('dest'))
        self.assertEqual(open(os.path.join(dst, 'sub', 'f')).read(), 'abc')
        link = os.path.join(dst, 'enlace')
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.readlink(link), 'sub/f')

    def test_copy_progress_is_monotonic_and_ends_at_total(self):
        write(self.p('big'), 'z' * (700 * 1024))
        os.mkdir(self.p('d'))
        seen = []
        fileops.copy(self.p('big'), self.p('d'),
                     progress=lambda done, total, name: seen.append(
                         (done, total)))
        self.assertTrue(len(seen) >= 3)
        self.assertEqual([d for d, _ in seen], sorted(d for d, _ in seen))
        self.assertEqual(seen[-1], (700 * 1024, 700 * 1024))

    def test_copy_folder_into_itself_is_refused(self):
        os.makedirs(self.p('a', 'b'))
        self.assertRaises(fileops.FileOpError, fileops.copy,
                          self.p('a'), self.p('a', 'b'))
        self.assertRaises(fileops.FileOpError, fileops.copy,
                          self.p('a'), self.p('a'))

    def test_copy_cancel_removes_partial(self):
        write(self.p('big'), 'z' * (900 * 1024))
        os.mkdir(self.p('d'))
        cancel = Gio.Cancellable()

        def stop(done, total, name):
            cancel.cancel()

        self.assertRaises(fileops.Cancelled, fileops.copy, self.p('big'),
                          self.p('d'), cancel, stop)
        self.assertEqual(os.listdir(self.p('d')), [])
        self.assertTrue(os.path.exists(self.p('big')))

    def test_copy_missing_source(self):
        self.assertRaises(fileops.FileOpError, fileops.copy,
                          self.p('nada'), self.tmp)


class MoveTests(Base):
    def test_move_file(self):
        write(self.p('a'), 'x')
        os.mkdir(self.p('d'))
        dst = fileops.move(self.p('a'), self.p('d'))
        self.assertEqual(dst, self.p('d', 'a'))
        self.assertFalse(os.path.exists(self.p('a')))

    def test_move_to_same_dir_is_noop(self):
        write(self.p('a'))
        self.assertEqual(fileops.move(self.p('a'), self.tmp), self.p('a'))
        self.assertTrue(os.path.exists(self.p('a')))

    def test_move_does_not_overwrite(self):
        write(self.p('a'), 'origen')
        os.mkdir(self.p('d'))
        write(self.p('d', 'a'), 'destino')
        dst = fileops.move(self.p('a'), self.p('d'))
        self.assertEqual(open(self.p('d', 'a')).read(), 'destino')
        self.assertEqual(open(dst).read(), 'origen')

    def test_move_across_filesystems_copies_and_deletes(self):
        os.makedirs(self.p('src', 'sub'))
        write(self.p('src', 'sub', 'f'), 'abc')
        os.mkdir(self.p('dest'))
        real_rename = os.rename

        def fake_rename(a, b):
            raise OSError(errno.EXDEV, 'Invalid cross-device link')

        os.rename = fake_rename
        try:
            dst = fileops.move(self.p('src'), self.p('dest'))
        finally:
            os.rename = real_rename
        self.assertEqual(open(os.path.join(dst, 'sub', 'f')).read(), 'abc')
        self.assertFalse(os.path.exists(self.p('src')))

    def test_failed_cross_move_keeps_source(self):
        write(self.p('a'), 'x')
        os.mkdir(self.p('d'))
        real_rename = os.rename
        cancel = Gio.Cancellable()
        cancel.cancel()

        def fake_rename(a, b):
            raise OSError(errno.EXDEV, 'Invalid cross-device link')

        os.rename = fake_rename
        try:
            self.assertRaises(fileops.Cancelled, fileops.move, self.p('a'),
                              self.p('d'), cancel)
        finally:
            os.rename = real_rename
        self.assertTrue(os.path.exists(self.p('a')))
        self.assertEqual(os.listdir(self.p('d')), [])

    def test_move_folder_into_itself_is_refused(self):
        os.makedirs(self.p('a', 'b'))
        self.assertRaises(fileops.FileOpError, fileops.move,
                          self.p('a'), self.p('a', 'b'))


class DeleteTests(Base):
    def test_delete_file_and_tree(self):
        write(self.p('a'))
        fileops.delete(self.p('a'))
        self.assertFalse(os.path.exists(self.p('a')))
        os.makedirs(self.p('t', 'u'))
        write(self.p('t', 'u', 'f'))
        fileops.delete(self.p('t'))
        self.assertFalse(os.path.exists(self.p('t')))

    def test_delete_does_not_follow_symlinks(self):
        os.mkdir(self.p('fuera'))
        write(self.p('fuera', 'importante'), 'no tocar')
        os.mkdir(self.p('d'))
        os.symlink(self.p('fuera'), self.p('d', 'enlace'))
        fileops.delete(self.p('d'))
        self.assertFalse(os.path.exists(self.p('d')))
        self.assertEqual(open(self.p('fuera', 'importante')).read(),
                         'no tocar')

    def test_delete_broken_symlink(self):
        os.symlink('no-existe', self.p('roto'))
        fileops.delete(self.p('roto'))
        self.assertFalse(os.path.lexists(self.p('roto')))

    def test_delete_refuses_root(self):
        self.assertRaises(fileops.FileOpError, fileops.delete, '/')

    def test_delete_missing(self):
        self.assertRaises(fileops.FileOpError, fileops.delete, self.p('x'))

    def test_delete_cancel_stops(self):
        os.mkdir(self.p('d'))
        for i in range(5):
            write(self.p('d', 'f%d' % i))
        cancel = Gio.Cancellable()
        cancel.cancel()
        self.assertRaises(fileops.Cancelled, fileops.delete, self.p('d'),
                          cancel)
        self.assertTrue(os.path.isdir(self.p('d')))


if __name__ == '__main__':
    unittest.main()
