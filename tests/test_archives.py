# -*- coding: utf-8 -*-
"""Pruebas de archives (crear/extraer .tar y .tar.gz), sin pantalla."""
import io
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ['ARCHIVOS_LANG'] = 'en'

from gi.repository import Gio  # noqa: E402

import archives  # noqa: E402
import fileops  # noqa: E402


def write(path, data='x'):
    with open(path, 'wb') as handle:
        handle.write(data)


def read(path):
    with open(path, 'rb') as handle:
        return handle.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='archivos-arc-')
        self.addCleanup(self._cleanup)
        self.out = self.p('salida')
        os.mkdir(self.out)

    def _cleanup(self):
        for current, dirs, _files in os.walk(self.tmp):
            for name in dirs:
                try:
                    os.chmod(os.path.join(current, name), 0o700)
                except OSError:
                    pass
        shutil.rmtree(self.tmp, True)

    def p(self, *parts):
        return os.path.join(self.tmp, *parts)

    def make_tree(self):
        root = self.p('src')
        os.makedirs(os.path.join(root, 'sub'))
        os.makedirs(os.path.join(root, 'vacia'))
        write(os.path.join(root, 'f1'), 'uno')
        write(os.path.join(root, 'sub', 'f2'), 'dos' * 1000)
        os.chmod(os.path.join(root, 'f1'), 0o640)
        os.utime(os.path.join(root, 'f1'), (1000000000, 1000000000))
        os.symlink('f1', os.path.join(root, 'enlace'))
        os.link(os.path.join(root, 'f1'), os.path.join(root, 'duro'))
        return root

    def build_tar(self, name, members, mode='w'):
        """members: lista de (TarInfo, datos o None)."""
        path = self.p(name)
        with tarfile.open(path, mode) as tar:
            for info, data in members:
                if data is None:
                    tar.addfile(info)
                else:
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
        return path


def info(name, kind=tarfile.REGTYPE, mode=0o644, linkname=''):
    item = tarfile.TarInfo(name)
    item.type = kind
    item.mode = mode
    item.linkname = linkname
    item.mtime = 1000000000
    return item


class NameTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(archives.archive_kind('a.tar'), '.tar')
        self.assertEqual(archives.archive_kind('A.TAR.GZ'), '.tar.gz')
        self.assertEqual(archives.archive_kind('a.tgz'), '.tgz')
        self.assertEqual(archives.archive_kind('a.tar.gz'), '.tar.gz')
        self.assertTrue(archives.archive_kind('a.zip') is None)
        self.assertTrue(archives.archive_kind('.tar') is None)
        self.assertTrue(archives.archive_kind('tar') is None)

    def test_base_name(self):
        self.assertEqual(archives.archive_base_name('proy.tar.gz'), 'proy')
        self.assertEqual(archives.archive_base_name('proy.tgz'), 'proy')
        self.assertEqual(archives.archive_base_name('a.b.tar'), 'a.b')
        self.assertEqual(archives.archive_base_name('x.zip'), 'x.zip')


class CreateTests(Base):
    def test_create_tar_roundtrip(self):
        root = self.make_tree()
        out = archives.create_archive([root], self.out)
        self.assertEqual(out, self.p('salida', 'src.tar'))
        with tarfile.open(out) as tar:
            names = sorted(tar.getnames())
            self.assertEqual(names, ['src', 'src/duro', 'src/enlace',
                                     'src/f1', 'src/sub', 'src/sub/f2',
                                     'src/vacia'])
            self.assertEqual(tar.extractfile('src/f1').read(), 'uno')
            self.assertEqual(tar.getmember('src/enlace').linkname, 'f1')
            # el segundo de los dos enlaces duros se guarda como enlace
            kinds = sorted([tar.getmember('src/duro').islnk(),
                            tar.getmember('src/f1').islnk()])
            self.assertEqual(kinds, [False, True])
            self.assertEqual(tar.getmember('src/f1').mode & 0o777, 0o640)

    def test_create_targz_is_really_gzip(self):
        root = self.make_tree()
        out = archives.create_archive([root], self.out, gz=True)
        self.assertEqual(out, self.p('salida', 'src.tar.gz'))
        self.assertEqual(read(out)[:2], '\x1f\x8b')
        with tarfile.open(out, 'r:gz') as tar:
            self.assertIn('src/sub/f2', tar.getnames())

    def test_gzip_actually_compresses(self):
        write(self.p('grande'), 'a' * 500000)
        out = archives.create_archive([self.p('grande')], self.out, gz=True)
        self.assertTrue(os.path.getsize(out) < 20000)

    def test_several_sources_use_the_destination_folder_name(self):
        write(self.p('a.txt'), 'A')
        write(self.p('b.txt'), 'B')
        out = archives.create_archive([self.p('a.txt'), self.p('b.txt')],
                                      self.out)
        self.assertEqual(os.path.basename(out), 'salida.tar')
        with tarfile.open(out) as tar:
            self.assertEqual(sorted(tar.getnames()), ['a.txt', 'b.txt'])

    def test_same_basename_from_different_folders(self):
        os.makedirs(self.p('x'))
        os.makedirs(self.p('y'))
        write(self.p('x', 'f'), '1')
        write(self.p('y', 'f'), '2')
        out = archives.create_archive([self.p('x', 'f'), self.p('y', 'f')],
                                      self.out)
        with tarfile.open(out) as tar:
            self.assertEqual(sorted(tar.getnames()), ['f', 'f (2)'])

    def test_never_overwrites_an_existing_archive(self):
        write(self.p('a.txt'), 'A')
        first = archives.create_archive([self.p('a.txt')], self.out)
        second = archives.create_archive([self.p('a.txt')], self.out)
        self.assertEqual(os.path.basename(first), 'a.txt.tar')
        self.assertEqual(os.path.basename(second), 'a.txt (2).tar')

    def test_owner_is_not_stored(self):
        write(self.p('a.txt'), 'A')
        out = archives.create_archive([self.p('a.txt')], self.out)
        with tarfile.open(out) as tar:
            member = tar.getmembers()[0]
            self.assertEqual((member.uid, member.gid), (0, 0))
            self.assertEqual((member.uname, member.gname), ('', ''))

    def test_special_files_are_skipped(self):
        os.makedirs(self.p('d'))
        write(self.p('d', 'f'), 'x')
        os.mkfifo(self.p('d', 'tuberia'))
        out = archives.create_archive([self.p('d')], self.out)
        with tarfile.open(out) as tar:
            self.assertEqual(sorted(tar.getnames()), ['d', 'd/f'])

    def test_progress_is_monotonic_and_ends_at_total(self):
        write(self.p('big'), 'z' * (700 * 1024))
        seen = []
        archives.create_archive([self.p('big')], self.out,
                                progress=lambda d, t, n: seen.append((d, t)))
        self.assertTrue(len(seen) > 3)
        self.assertEqual([d for d, _ in seen], sorted(d for d, _ in seen))
        self.assertEqual(seen[-1], (700 * 1024, 700 * 1024))

    def test_cancel_leaves_nothing_behind(self):
        write(self.p('big'), 'z' * (900 * 1024))
        cancel = Gio.Cancellable()
        self.assertRaises(fileops.Cancelled, archives.create_archive,
                          [self.p('big')], self.out, True, cancel,
                          lambda d, t, n: cancel.cancel())
        self.assertEqual(os.listdir(self.out), [])
        self.assertTrue(os.path.exists(self.p('big')))

    def test_no_partial_file_is_visible_while_writing(self):
        write(self.p('big'), 'z' * (300 * 1024))
        names = []

        def peek(done, total, name):
            names.append(sorted(os.listdir(self.out)))

        archives.create_archive([self.p('big')], self.out, progress=peek)
        self.assertTrue(all(n == ['.big.tar.part'] for n in names[:-1]))
        self.assertEqual(os.listdir(self.out), ['big.tar'])

    def test_missing_source_and_empty_list(self):
        self.assertRaises(fileops.FileOpError, archives.create_archive,
                          [self.p('nada')], self.out)
        self.assertRaises(fileops.FileOpError, archives.create_archive,
                          [], self.out)
        self.assertEqual(os.listdir(self.out), [])

    def test_unwritable_destination_leaves_nothing(self):
        write(self.p('a'), 'A')
        self.assertRaises(fileops.FileOpError, archives.create_archive,
                          [self.p('a')], self.p('no-existe'))

    def test_source_is_not_modified(self):
        root = self.make_tree()
        archives.create_archive([root], self.out, gz=True)
        self.assertEqual(read(os.path.join(root, 'f1')), 'uno')
        self.assertTrue(os.path.islink(os.path.join(root, 'enlace')))


class ExtractTests(Base):
    def test_roundtrip_tar_and_targz(self):
        root = self.make_tree()
        for gz in (False, True):
            dest = self.p('dest%d' % gz)
            os.mkdir(dest)
            arc = archives.create_archive([root], self.out, gz=gz)
            final = archives.extract_archive(arc, dest)
            self.assertEqual(final, os.path.join(dest, 'src'))
            self.assertEqual(read(os.path.join(final, 'f1')), 'uno')
            self.assertEqual(read(os.path.join(final, 'sub', 'f2')),
                             'dos' * 1000)
            self.assertTrue(os.path.isdir(os.path.join(final, 'vacia')))
            link = os.path.join(final, 'enlace')
            self.assertTrue(os.path.islink(link))
            self.assertEqual(os.readlink(link), 'f1')
            self.assertEqual(os.stat(os.path.join(final, 'duro')).st_ino,
                             os.stat(os.path.join(final, 'f1')).st_ino)
            st = os.stat(os.path.join(final, 'f1'))
            self.assertEqual(st.st_mode & 0o777, 0o640)
            self.assertEqual(int(st.st_mtime), 1000000000)
            os.unlink(arc)

    def test_single_root_entry_is_not_nested_in_a_new_folder(self):
        arc = self.build_tar('proy.tar.gz', [
            (info('proy', tarfile.DIRTYPE, 0o755), None),
            (info('proy/a.txt'), 'A')], 'w:gz')
        final = archives.extract_archive(arc, self.out)
        self.assertEqual(final, self.p('salida', 'proy'))
        self.assertEqual(os.listdir(self.out), ['proy'])
        self.assertEqual(read(self.p('salida', 'proy', 'a.txt')), 'A')

    def test_several_root_entries_go_into_a_folder_named_like_the_archive(self):
        arc = self.build_tar('suelto.tar', [
            (info('a.txt'), 'A'), (info('b.txt'), 'B')])
        final = archives.extract_archive(arc, self.out)
        self.assertEqual(final, self.p('salida', 'suelto'))
        self.assertEqual(sorted(os.listdir(final)), ['a.txt', 'b.txt'])

    def test_never_overwrites_existing_results(self):
        arc = self.build_tar('proy.tar', [(info('proy/a.txt'), 'NUEVO')])
        os.makedirs(self.p('salida', 'proy'))
        write(self.p('salida', 'proy', 'a.txt'), 'VIEJO')
        final = archives.extract_archive(arc, self.out)
        self.assertEqual(final, self.p('salida', 'proy (2)'))
        self.assertEqual(read(self.p('salida', 'proy', 'a.txt')), 'VIEJO')
        self.assertEqual(read(os.path.join(final, 'a.txt')), 'NUEVO')

    def test_leading_slash_and_dot_slash_are_relative(self):
        arc = self.build_tar('r.tar', [
            (info('./a.txt'), 'A'), (info('/abs/b.txt'), 'B')])
        final = archives.extract_archive(arc, self.out)
        self.assertEqual(read(os.path.join(final, 'a.txt')), 'A')
        self.assertEqual(read(os.path.join(final, 'abs', 'b.txt')), 'B')
        self.assertFalse(os.path.exists('/abs/b.txt'))

    def test_parent_traversal_is_rejected_and_cleaned_up(self):
        arc = self.build_tar('mal.tar', [
            (info('ok.txt'), 'ok'), (info('../fuera.txt'), 'MAL')])
        self.assertRaises(fileops.FileOpError, archives.extract_archive,
                          arc, self.out)
        self.assertFalse(os.path.exists(self.p('fuera.txt')))
        self.assertEqual(os.listdir(self.out), [])

    def test_nested_traversal_is_rejected(self):
        arc = self.build_tar('mal.tar', [
            (info('a/../../fuera.txt'), 'MAL')])
        self.assertRaises(fileops.FileOpError, archives.extract_archive,
                          arc, self.out)
        self.assertFalse(os.path.exists(self.p('fuera.txt')))

    def test_writing_through_a_symlink_that_escapes_is_blocked(self):
        os.mkdir(self.p('victima'))
        arc = self.build_tar('mal.tar', [
            (info('enlace', tarfile.SYMTYPE, 0o777, self.p('victima')), None),
            (info('enlace/pwned.txt'), 'MAL')])
        self.assertRaises(fileops.FileOpError, archives.extract_archive,
                          arc, self.out)
        self.assertEqual(os.listdir(self.p('victima')), [])
        self.assertEqual(os.listdir(self.out), [])

    def test_symlink_to_a_folder_inside_is_allowed(self):
        arc = self.build_tar('ok.tar', [
            (info('d', tarfile.DIRTYPE, 0o755), None),
            (info('l', tarfile.SYMTYPE, 0o777, 'd'), None),
            (info('l/f.txt'), 'dentro')])
        final = archives.extract_archive(arc, self.out)
        self.assertEqual(read(os.path.join(final, 'd', 'f.txt')), 'dentro')

    def test_hardlink_to_the_outside_is_refused(self):
        write(self.p('secreto'), 'S')
        arc = self.build_tar('mal.tar', [
            (info('h', tarfile.LNKTYPE, 0o644, '../secreto'), None)])
        self.assertRaises(fileops.FileOpError, archives.extract_archive,
                          arc, self.out)
        self.assertEqual(os.listdir(self.out), [])
        self.assertEqual(os.stat(self.p('secreto')).st_nlink, 1)

    def test_hardlink_to_a_missing_target_is_refused(self):
        arc = self.build_tar('mal.tar', [
            (info('h', tarfile.LNKTYPE, 0o644, 'no-existe'), None)])
        self.assertRaises(fileops.FileOpError, archives.extract_archive,
                          arc, self.out)

    def test_devices_and_fifos_are_skipped(self):
        arc = self.build_tar('esp.tar', [
            (info('dev', tarfile.CHRTYPE, 0o666), None),
            (info('fifo', tarfile.FIFOTYPE, 0o666), None),
            (info('normal.txt'), 'N'), (info('otro.txt'), 'O')])
        final = archives.extract_archive(arc, self.out)
        self.assertEqual(sorted(os.listdir(final)),
                         ['normal.txt', 'otro.txt'])

    def test_setuid_and_sticky_bits_are_dropped(self):
        arc = self.build_tar('suid.tar', [
            (info('a', mode=0o4755), 'x'), (info('b', mode=0o2755), 'y'),
            (info('c', mode=0o1777), 'z')])
        final = archives.extract_archive(arc, self.out)
        for name in ('a', 'b', 'c'):
            mode = os.stat(os.path.join(final, name)).st_mode
            self.assertEqual(mode & 0o7000, 0, name)

    def test_owner_always_keeps_access(self):
        arc = self.build_tar('perm.tar', [
            (info('d', tarfile.DIRTYPE, 0o000), None),
            (info('d/f', mode=0o000), 'x')])
        final = archives.extract_archive(arc, self.out)
        self.assertEqual(os.stat(final).st_mode & 0o700, 0o700)
        self.assertEqual(os.stat(os.path.join(final, 'f')).st_mode & 0o600,
                         0o600)
        fileops.delete(final)
        self.assertFalse(os.path.exists(final))

    def test_read_only_dir_does_not_block_its_own_contents(self):
        arc = self.build_tar('ro.tar', [
            (info('d', tarfile.DIRTYPE, 0o555), None),
            (info('d/f'), 'x')])
        final = archives.extract_archive(arc, self.out)
        self.assertEqual(read(os.path.join(final, 'f')), 'x')

    def test_garbage_is_not_a_valid_archive(self):
        write(self.p('basura.tar'), 'esto no es un tar' * 100)
        self.assertRaises(fileops.FileOpError, archives.extract_archive,
                          self.p('basura.tar'), self.out)
        self.assertEqual(os.listdir(self.out), [])

    def test_truncated_gzip_is_rejected_without_leftovers(self):
        write(self.p('datos'), os.urandom(200000))
        arc = archives.create_archive([self.p('datos')], self.out, gz=True)
        data = read(arc)
        os.unlink(arc)
        write(self.p('corto.tar.gz'), data[:len(data) // 2])
        self.assertRaises(fileops.FileOpError, archives.extract_archive,
                          self.p('corto.tar.gz'), self.out)
        self.assertEqual(os.listdir(self.out), [])

    def test_tar_cut_exactly_between_entries_is_rejected(self):
        arc = self.build_tar('dos.tar', [(info('a'), 'A' * 100),
                                         (info('b'), 'B' * 100)])
        data = read(arc)
        # cabecera(512) + datos(512) de la primera entrada, y se corta ahí
        write(self.p('cortado.tar'), data[:1024])
        self.assertRaises(fileops.FileOpError, archives.extract_archive,
                          self.p('cortado.tar'), self.out)
        self.assertEqual(os.listdir(self.out), [])

    def test_tar_cut_in_the_middle_of_a_file_is_rejected(self):
        arc = self.build_tar('uno.tar', [(info('a'), 'A' * 5000)])
        write(self.p('cortado.tar'), read(arc)[:1500])
        self.assertRaises(fileops.FileOpError, archives.extract_archive,
                          self.p('cortado.tar'), self.out)
        self.assertEqual(os.listdir(self.out), [])

    def test_gzip_cut_at_the_trailer_is_rejected(self):
        write(self.p('datos'), 'q' * 3000)
        arc = archives.create_archive([self.p('datos')], self.out, gz=True)
        write(self.p('sin-cola.tar.gz'), read(arc)[:-8])    # sin CRC ni tamaño
        self.assertRaises(fileops.FileOpError, archives.extract_archive,
                          self.p('sin-cola.tar.gz'), self.out)
        self.assertEqual(sorted(os.listdir(self.out)), [os.path.basename(arc)])

    def test_gzip_with_a_corrupted_byte_is_rejected(self):
        write(self.p('datos'), os.urandom(50000))
        arc = archives.create_archive([self.p('datos')], self.out, gz=True)
        data = bytearray(read(arc))
        data[len(data) // 2] ^= 0xFF
        write(self.p('roto.tar.gz'), bytes(data))
        self.assertRaises(fileops.FileOpError, archives.extract_archive,
                          self.p('roto.tar.gz'), self.out)
        self.assertEqual(sorted(os.listdir(self.out)), [os.path.basename(arc)])

    def test_content_decides_not_the_extension(self):
        # un tar sin comprimir con nombre .tar.gz y un gzip con nombre .tar
        plain = self.build_tar('plano.tar.gz', [(info('a.txt'), 'A'),
                                                (info('b.txt'), 'B')])
        final = archives.extract_archive(plain, self.out)
        self.assertEqual(sorted(os.listdir(final)), ['a.txt', 'b.txt'])
        gzipped = self.build_tar('comprimido.tar', [(info('c.txt'), 'C')],
                                 'w:gz')
        final = archives.extract_archive(gzipped, self.out)
        self.assertEqual(read(final), 'C')

    def test_unsupported_extension_and_missing_file(self):
        write(self.p('a.zip'), 'x')
        self.assertRaises(fileops.FileOpError, archives.extract_archive,
                          self.p('a.zip'), self.out)
        self.assertRaises(fileops.FileOpError, archives.extract_archive,
                          self.p('no.tar'), self.out)

    def test_cancel_cleans_up(self):
        write(self.p('big'), 'z' * (900 * 1024))
        arc = archives.create_archive([self.p('big')], self.p('salida'))
        os.mkdir(self.p('d2'))
        cancel = Gio.Cancellable()
        self.assertRaises(fileops.Cancelled, archives.extract_archive, arc,
                          self.p('d2'), cancel,
                          lambda d, t, n: cancel.cancel())
        self.assertEqual(os.listdir(self.p('d2')), [])

    def test_progress_ends_at_the_archive_size(self):
        write(self.p('big'), 'z' * (400 * 1024))
        arc = archives.create_archive([self.p('big')], self.out, gz=True)
        os.mkdir(self.p('d2'))
        seen = []
        archives.extract_archive(arc, self.p('d2'),
                                 progress=lambda d, t, n: seen.append((d, t)))
        self.assertEqual(seen[-1], (os.path.getsize(arc),) * 2)
        self.assertEqual([d for d, _ in seen], sorted(d for d, _ in seen))

    def test_empty_archive_makes_an_empty_folder(self):
        arc = self.build_tar('vacio.tar', [])
        final = archives.extract_archive(arc, self.out)
        self.assertEqual(final, self.p('salida', 'vacio'))
        self.assertEqual(os.listdir(final), [])

    def test_unicode_names(self):
        write(self.p('canci\xc3\xb3n.txt'), 'la')
        arc = archives.create_archive([self.p('canci\xc3\xb3n.txt')],
                                      self.out, gz=True)
        os.mkdir(self.p('d2'))
        final = archives.extract_archive(arc, self.p('d2'))
        self.assertEqual(read(final), 'la')
        self.assertEqual(os.path.basename(final), 'canci\xc3\xb3n.txt')


if __name__ == '__main__':
    unittest.main()
