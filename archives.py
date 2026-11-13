# -*- coding: utf-8 -*-
"""Crear y extraer archivos .tar y .tar.gz (sin GTK, se prueba sin pantalla).

Crear
    ``create_archive(fuentes, carpeta, gz)`` escribe primero en un fichero
    oculto ``.nombre.part`` y lo renombra al terminar, así nunca queda a medias
    un archivo con el nombre final. Nunca sobrescribe (``a (2).tar.gz``). No
    guarda propietario (uid/gid 0, sin nombres) para que el archivo sea
    portable y no revele usuarios.

Extraer
    ``extract_archive(archivo, carpeta)`` lee en modo flujo (poca memoria, sirve
    para archivos grandes en un equipo pequeño) y extrae a una carpeta oculta
    temporal junto al destino; solo si todo va bien la deja con su nombre final:
    si el archivo tiene una única entrada en la raíz, esa entrada pasa a la
    carpeta de destino; si tiene varias, se crea una carpeta con el nombre del
    archivo. Nunca sobrescribe y, si falla o se cancela, no deja restos.

Seguridad al extraer (los archivos pueden venir de cualquier sitio)
    - Las rutas absolutas se hacen relativas y las que contienen ``..`` se
      rechazan: no se puede escribir fuera de la carpeta de destino.
    - No se escribe a través de enlaces simbólicos que apunten fuera de ella.
    - Los enlaces duros solo pueden apuntar a algo ya extraído dentro.
    - Se descartan setuid/setgid/sticky, dispositivos, tuberías y sockets.
    - El propietario siempre conserva acceso (archivos rw, carpetas rwx) para
      poder gestionar lo extraído.
"""
import gzip
import os
import stat
import struct
import tarfile
import tempfile
import zlib

import fileops
from fileops import Cancelled, FileOpError, _check, _clean, _report
from i18n import tr

_SUFFIXES = ('.tar.gz', '.tgz', '.tar')      # los más largos, primero
_CHUNK = 64 * 1024
_O_NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0)
_GZIP_LEVEL = 6


# --------------------------------------------------------------------------
# Nombres
# --------------------------------------------------------------------------

def archive_kind(name):
    """'.tar', '.tar.gz' o '.tgz' según el nombre; None si no es compatible."""
    low = fileops._b(name).lower()
    for suffix in _SUFFIXES:
        if low.endswith(suffix) and len(low) > len(suffix):
            return suffix
    return None


def is_archive(name):
    return archive_kind(name) is not None


def archive_base_name(name):
    """Nombre sin la extensión del archivo (``a.tar.gz`` -> ``a``)."""
    name = fileops._b(name)
    kind = archive_kind(name)
    return name[:-len(kind)] if kind else name


# --------------------------------------------------------------------------
# Crear
# --------------------------------------------------------------------------

class _CountingReader(object):
    """Envuelve un fichero para contar lo leído y poder cancelar a mitad."""

    def __init__(self, handle, state, total, name, cancellable, progress):
        self._handle = handle
        self._state = state
        self._total = total
        self._name = name
        self._cancellable = cancellable
        self._progress = progress

    def read(self, size=-1):
        _check(self._cancellable)
        data = self._handle.read(size)
        self._state['done'] += len(data)
        _report(self._progress, self._state, self._total, self._name)
        return data


def _add_node(tar, path, arcname, state, total, cancellable, progress):
    _check(cancellable)
    mode = os.lstat(path).st_mode
    if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode)):
        return                       # sockets, tuberías y dispositivos: fuera
    info = tar.gettarinfo(path, arcname)
    if info is None:
        return
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    if info.isreg():
        with open(path, 'rb') as handle:
            tar.addfile(info, _CountingReader(handle, state, total,
                                              os.path.basename(path),
                                              cancellable, progress))
    else:
        tar.addfile(info)
    if info.isdir():
        for name in sorted(os.listdir(path)):
            _add_node(tar, os.path.join(path, name),
                      arcname + '/' + name, state, total, cancellable,
                      progress)


def create_archive(sources, dst_dir, gz=False, cancellable=None,
                   progress=None):
    """Crea un .tar (o .tar.gz) con ``sources`` dentro de ``dst_dir``.

    El nombre sale de la única fuente o, si son varias, de la carpeta de
    destino. Devuelve la ruta creada. ``progress(hecho, total, nombre)``
    recibe bytes de datos de origen.
    """
    sources = [_clean(s) for s in sources]
    dst_dir = _clean(dst_dir)
    if not sources:
        raise FileOpError(tr('Nothing to archive'))
    for source in sources:
        if not os.path.lexists(source):
            raise FileOpError('%s (%s)' % (tr('The item no longer exists'),
                                            os.path.basename(source)))
    if len(sources) == 1:
        base = os.path.basename(sources[0])
    else:
        base = os.path.basename(dst_dir) or tr('archive')
    final_name = fileops.unique_name(dst_dir,
                                     base + ('.tar.gz' if gz else '.tar'))
    final = os.path.join(dst_dir, final_name)
    part = os.path.join(dst_dir, '.' + final_name + '.part')
    total = sum(fileops.tree_size(s) for s in sources)
    state = {'done': 0}
    tar = None
    try:
        if gz:
            tar = tarfile.open(part, 'w:gz', compresslevel=_GZIP_LEVEL)
        else:
            tar = tarfile.open(part, 'w')
        used = set()
        for source in sources:
            arcname = os.path.basename(source)
            if arcname in used:      # dos fuentes con el mismo nombre
                arcname = fileops.unique_name_in(used, arcname)
            used.add(arcname)
            _add_node(tar, source, arcname, state, total, cancellable,
                      progress)
        tar.close()
        tar = None
        os.rename(part, final)
    except Cancelled:
        _discard(tar, part)
        raise
    except (OSError, IOError, tarfile.TarError) as exc:
        _discard(tar, part)
        reason = getattr(exc, 'strerror', None) or str(exc)
        raise FileOpError('%s: %s (%s)' % (tr('Could not create the archive'),
                                            reason, final_name))
    except BaseException:
        _discard(tar, part)
        raise
    if progress is not None:
        progress(total, total, final_name)
    return final


def _discard(tar, part):
    if tar is not None:
        try:
            tar.close()
        except Exception:
            pass
    try:
        os.unlink(part)
    except OSError:
        pass


# --------------------------------------------------------------------------
# Extraer
# --------------------------------------------------------------------------

def _safe_parts(name):
    """Componentes de una ruta del archivo, ya sin ``/`` inicial ni ``.``."""
    parts = [p for p in fileops._b(name).split('/') if p not in ('', '.')]
    if '..' in parts:
        raise FileOpError(tr('Unsafe archive: a path leaves the '
                             'destination folder'))
    return parts


def _inside(root_real, path):
    real = os.path.realpath(path)
    return real == root_real or real.startswith(root_real.rstrip('/') + '/')


def _ensure_parent(root, root_real, parts):
    """Crea (con cuidado) las carpetas que contienen la entrada ``parts``."""
    current = root
    for part in parts[:-1]:
        current = os.path.join(current, part)
        if os.path.islink(current) and not _inside(root_real, current):
            raise FileOpError(tr('Unsafe archive: a path leaves the '
                                 'destination folder'))
        if not os.path.lexists(current):
            os.mkdir(current, 0o700)
        elif not os.path.isdir(current):
            raise FileOpError(tr('Not a valid archive'))
    if not _inside(root_real, current):
        raise FileOpError(tr('Unsafe archive: a path leaves the '
                             'destination folder'))
    return os.path.join(current, parts[-1])


def _extract_members(tar, raw, root, total, cancellable, progress):
    root_real = os.path.realpath(root)
    state = {'done': 0}
    dirs = []                       # (ruta, modo, mtime): se ajustan al final
    skipped = 0

    def tick(name):
        state['done'] = min(raw.tell(), total)
        _report(progress, state, total, name)

    for member in tar:
        _check(cancellable)
        parts = _safe_parts(member.name)
        if not parts:
            continue                # la raíz del archivo ('./')
        name = parts[-1]
        target = _ensure_parent(root, root_real, parts)
        if member.isdir():
            if not os.path.lexists(target):
                os.mkdir(target, 0o700)
            dirs.append((target, member.mode, member.mtime))
        elif member.isreg():
            if os.path.islink(target):
                os.unlink(target)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC |
                         _O_NOFOLLOW, 0o600)
            handle = os.fdopen(fd, 'wb')
            written = 0
            try:
                source = tar.extractfile(member)
                while True:
                    _check(cancellable)
                    chunk = source.read(_CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    written += len(chunk)
                    tick(name)
            finally:
                handle.close()
            if written != member.size:      # archivo cortado a mitad de dato
                raise FileOpError(tr('Not a valid archive'))
            os.chmod(target, (member.mode & 0o777) | 0o600)
            try:
                os.utime(target, (member.mtime, member.mtime))
            except OSError:
                pass
        elif member.issym():
            if os.path.lexists(target) and not os.path.isdir(target):
                os.unlink(target)
            os.symlink(member.linkname, target)
        elif member.islnk():
            link_parts = _safe_parts(member.linkname)
            origin = os.path.join(root, *link_parts) if link_parts else None
            if (origin is None or not os.path.isfile(origin)
                    or os.path.islink(origin)
                    or not _inside(root_real, origin)):
                raise FileOpError(tr('Unsafe archive: a path leaves the '
                                     'destination folder'))
            if os.path.lexists(target):
                os.unlink(target)
            os.link(origin, target)
        else:
            skipped += 1            # dispositivos, tuberías, sockets
        tick(name)
    for path, mode, mtime in reversed(dirs):
        os.chmod(path, (mode & 0o777) | 0o700)
        try:
            os.utime(path, (mtime, mtime))
        except OSError:
            pass
    return skipped


def _open_stream(raw):
    """(flujo sin comprimir, es_gzip). Se mira el contenido, no la extensión."""
    magic = raw.read(2)
    raw.seek(0)
    if magic == '\x1f\x8b':
        stream = gzip.GzipFile(fileobj=raw, mode='rb')
        # Por defecto lee hasta 10 MB de golpe y el progreso (posición en el
        # fichero) saltaría al 100 % de inmediato.
        stream.max_read_chunk = _CHUNK
        return stream, True
    return raw, False


def _verify_end(stream, is_gzip, end_of_data, size):
    """Comprueba que el archivo termina bien, no que se cortó sin avisar.

    ``tarfile`` toma un fin de fichero inesperado por el final del archivo, así
    que un archivo truncado "se extraería" a medias sin error. En gzip basta con
    leer hasta el final: ahí se comprueban el CRC y la longitud. En un .tar sin
    comprimir debe haber al menos un bloque de ceros tras la última entrada.
    """
    if is_gzip:
        while stream.read(_CHUNK):
            pass
    elif end_of_data >= size:
        raise FileOpError(tr('Not a valid archive'))


def _finalize(tmp, dst_dir, base):
    entries = os.listdir(tmp)
    if len(entries) == 1:
        only = entries[0]
        name = fileops.unique_name(dst_dir, only)
        final = os.path.join(dst_dir, name)
        os.rename(os.path.join(tmp, only), final)
        os.rmdir(tmp)
        return final
    name = fileops.unique_name(dst_dir, base)
    final = os.path.join(dst_dir, name)
    os.chmod(tmp, 0o755)
    os.rename(tmp, final)
    return final


def extract_archive(path, dst_dir, cancellable=None, progress=None):
    """Extrae un .tar/.tar.gz en ``dst_dir`` y devuelve la ruta resultante."""
    path = _clean(path)
    dst_dir = _clean(dst_dir)
    if not os.path.isfile(path):
        raise FileOpError('%s (%s)' % (tr('The item no longer exists'),
                                        os.path.basename(path)))
    if archive_kind(path) is None:
        raise FileOpError('%s (%s)' % (tr('Not a supported archive'),
                                        os.path.basename(path)))
    size = os.path.getsize(path)
    total = max(size, 1)
    base = archive_base_name(os.path.basename(path))
    label = os.path.basename(path)
    try:
        tmp = tempfile.mkdtemp(prefix='.' + base[:40] + '.',
                               suffix='.extracting', dir=dst_dir)
    except OSError as exc:
        raise FileOpError('%s: %s (%s)' % (tr('Could not extract'),
                                            exc.strerror, label))
    try:
        with open(path, 'rb') as raw:
            stream, is_gzip = _open_stream(raw)
            tar = tarfile.open(fileobj=stream, mode='r|')
            try:
                _extract_members(tar, raw, tmp, total, cancellable, progress)
                end_of_data = tar.offset
            finally:
                tar.close()
            _verify_end(stream, is_gzip, end_of_data, size)
        final = _finalize(tmp, dst_dir, base)
    except Cancelled:
        _remove(tmp)
        raise
    except FileOpError:
        _remove(tmp)
        raise
    except (tarfile.TarError, zlib.error, EOFError, struct.error):
        _remove(tmp)
        raise FileOpError('%s (%s)' % (tr('Not a valid archive'), label))
    except (OSError, IOError) as exc:
        _remove(tmp)
        if getattr(exc, 'errno', None) is None:
            # IOError sin errno: lo lanza gzip ("Not a gzipped file", CRC...)
            raise FileOpError('%s (%s)' % (tr('Not a valid archive'), label))
        reason = getattr(exc, 'strerror', None) or str(exc)
        raise FileOpError('%s: %s (%s)' % (tr('Could not extract'), reason,
                                            label))
    except BaseException:
        _remove(tmp)
        raise
    if progress is not None:
        progress(total, total, label)
    return final


def _remove(path):
    # Una carpeta ya extraída a medias puede tener carpetas sin permisos.
    for current, dirs, _files in os.walk(path):
        for name in dirs:
            try:
                os.chmod(os.path.join(current, name), 0o700)
            except OSError:
                pass
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    try:
        fileops.delete(path)
    except FileOpError:
        pass
