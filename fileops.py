# -*- coding: utf-8 -*-
"""Operaciones de archivos de Archivos.

Sin GTK: solo Gio/GLib para listar y la biblioteca estándar para copiar,
mover, renombrar y borrar. Así se puede probar desde SSH, sin pantalla.

Todas las rutas y nombres son ``str`` (bytes UTF-8) de principio a fin.
Los errores se señalan con FileOpError, con el mensaje ya traducido.
"""
import errno
import os
import stat
import time

from gi.repository import Gio

from i18n import N_, tr

try:
    unicode
except NameError:      # pragma: no cover
    unicode = str

_CHUNK = 256 * 1024
# Cada llamada de introspección de Gio cuesta ~0,2 ms en el XO, así que el
# listado usa os.listdir/os.lstat (C puro) y Gio solo una vez por tipo.
_types_by_key = {}       # extensión (o nombre sin extensión) -> tipo MIME
_icons_by_type = {}      # tipo MIME -> Gio.Icon (uno por tipo)


class FileOpError(Exception):
    """Fallo de una operación; el mensaje se puede mostrar al usuario."""


class Cancelled(FileOpError):
    """La operación se canceló a petición del usuario."""


class Entry(object):
    """Una fila del listado de una carpeta."""

    def __init__(self):
        self.name = ''
        self.display = ''
        self.is_dir = False
        self.is_link = False
        self.size = 0
        self.mtime = 0
        self.content_type = ''
        self.icon = None
        self.hidden = False


def _b(text):
    if isinstance(text, unicode):
        return text.encode('utf-8')
    return text


def _u(text):
    if isinstance(text, bytes):
        return text.decode('utf-8', 'replace')
    return text


def _clean(path):
    path = _b(path)
    if len(path) > 1:
        path = path.rstrip('/') or '/'
    return path


def _oserr(prefix, name, exc):
    reason = getattr(exc, 'strerror', None) or str(exc)
    return FileOpError('%s: %s (%s)' % (tr(prefix), reason, name))


def _check(cancellable):
    if cancellable is not None and cancellable.is_cancelled():
        raise Cancelled(tr('Cancelled'))


# --------------------------------------------------------------------------
# Listado
# --------------------------------------------------------------------------

def content_type_for(name, is_dir=False):
    """Tipo MIME por el nombre (sin leer el archivo), con caché por extensión."""
    if is_dir:
        return 'inode/directory'
    key = os.path.splitext(name)[1].lower() or name
    ctype = _types_by_key.get(key)
    if ctype is None:
        ctype = Gio.content_type_guess(name, None)[0]
        ctype = _types_by_key[key] = ctype or 'application/octet-stream'
    return ctype


def icon_for_type(ctype):
    icon = _icons_by_type.get(ctype)
    if icon is None:
        if ctype == 'inode/directory':
            # Gio pide 'inode-directory', que los temas de iconos no traen
            icon = Gio.ThemedIcon.new('folder')
        else:
            icon = Gio.content_type_get_icon(ctype)
        _icons_by_type[ctype] = icon
    return icon


def _display_name(name):
    try:
        name.decode('utf-8')
        return name
    except UnicodeDecodeError:
        return name.decode('utf-8', 'replace').encode('utf-8')


def _sort_key(entry):
    return (not entry.is_dir, _u(entry.display).lower())


def list_dir(path, show_hidden=False, cancellable=None):
    """Lista una carpeta: carpetas primero, después por nombre."""
    path = _clean(path)
    try:
        names = os.listdir(path)
    except OSError as exc:
        raise FileOpError('%s: %s' % (tr('Cannot read this folder'),
                                       exc.strerror or str(exc)))
    entries = []
    for count, name in enumerate(names):
        if count % 256 == 0:
            _check(cancellable)
        hidden = name.startswith('.') or name.endswith('~')
        if hidden and not show_hidden:
            continue
        full = os.path.join(path, name)
        try:
            st = os.lstat(full)
        except OSError:
            continue                      # desapareció mientras se listaba
        is_link = stat.S_ISLNK(st.st_mode)
        if is_link:
            try:
                st = os.stat(full)        # un enlace se muestra como su destino
            except OSError:
                pass                      # enlace roto: se queda como enlace
        entry = Entry()
        entry.name = name
        entry.display = _display_name(name)
        entry.is_dir = stat.S_ISDIR(st.st_mode)
        entry.is_link = is_link
        entry.size = 0 if entry.is_dir else st.st_size
        entry.mtime = int(st.st_mtime)
        entry.content_type = content_type_for(name, entry.is_dir)
        entry.icon = icon_for_type(entry.content_type)
        entry.hidden = hidden
        entries.append(entry)
    entries.sort(key=_sort_key)
    return entries


def _warm_up():
    """Toca desde el hilo principal los atributos de Gio que usa list_dir.

    PyGObject 3.4 carga los atributos de forma perezosa y no es seguro
    hacerlo por primera vez desde otro hilo (falla con AttributeError).
    """
    try:
        for name, is_dir in (('a.txt', False), ('d', True)):
            icon_for_type(content_type_for(name, is_dir))
        list_dir('/', True)
    except Exception:
        pass


def summarize(entries):
    """(carpetas, archivos, bytes de los archivos) de un listado."""
    folders = files = total = 0
    for entry in entries:
        if entry.is_dir:
            folders += 1
        else:
            files += 1
            total += entry.size
    return folders, files, total


def human_size(size):
    if size < 1024:
        return '%d B' % size
    value = float(size)
    for unit in ('KB', 'MB', 'GB', 'TB'):
        value /= 1024.0
        if value < 1024 or unit == 'TB':
            return '%.1f %s' % (value, unit)


def format_mtime(seconds):
    try:
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(seconds))
    except (ValueError, OverflowError, OSError):
        return ''


# --------------------------------------------------------------------------
# Nombres
# --------------------------------------------------------------------------

def validate_name(name):
    name = _b(name)
    if not name or name in ('.', '..') or '/' in name or '\0' in name:
        raise FileOpError(tr('Invalid name'))
    return name


def unique_name(directory, name):
    """Devuelve ``name`` o, si ya existe, ``name (2)``, ``name (3)``..."""
    directory = _clean(directory)
    name = _b(name)
    if not os.path.lexists(os.path.join(directory, name)):
        return name
    base, ext = os.path.splitext(name)
    if base.endswith('.tar'):
        base, ext = base[:-4], '.tar' + ext
    number = 2
    while True:
        candidate = '%s (%d)%s' % (base, number, ext)
        if not os.path.lexists(os.path.join(directory, candidate)):
            return candidate
        number += 1


# --------------------------------------------------------------------------
# Renombrar y crear carpetas
# --------------------------------------------------------------------------

def rename(path, new_name):
    path = _clean(path)
    new_name = validate_name(new_name)
    parent, old_name = os.path.split(path)
    if new_name == old_name:
        return path
    target = os.path.join(parent, new_name)
    if os.path.lexists(target):
        raise FileOpError(tr('A file with that name already exists'))
    try:
        os.rename(path, target)
    except OSError as exc:
        raise _oserr(N_('Could not rename'), old_name, exc)
    return target


def unique_name_in(taken, name):
    """Como ``unique_name`` pero contra un conjunto de nombres ya usados."""
    if name not in taken:
        return name
    base, ext = os.path.splitext(name)
    number = 2
    while '%s (%d)%s' % (base, number, ext) in taken:
        number += 1
    return '%s (%d)%s' % (base, number, ext)


def make_file(parent, name):
    """Crea un archivo vacío (0 bytes). Nunca sobrescribe uno existente."""
    parent = _clean(parent)
    name = validate_name(name)
    target = os.path.join(parent, name)
    try:
        # O_EXCL: falla si ya existe (incluso si es un enlace roto)
        handle = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise FileOpError(tr('A file with that name already exists'))
        raise _oserr(N_('Could not create the file'), name, exc)
    os.close(handle)
    return target


def make_dir(parent, name):
    parent = _clean(parent)
    name = validate_name(name)
    target = os.path.join(parent, name)
    if os.path.lexists(target):
        raise FileOpError(tr('A file with that name already exists'))
    try:
        os.mkdir(target)
    except OSError as exc:
        raise _oserr(N_('Could not create the folder'), name, exc)
    return target


# --------------------------------------------------------------------------
# Tamaños
# --------------------------------------------------------------------------

def tree_size(path):
    """Bytes de datos bajo ``path`` (sin seguir enlaces simbólicos)."""
    total = 0
    pending = [_clean(path)]
    while pending:
        current = pending.pop()
        try:
            st = os.lstat(current)
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode):
            try:
                names = os.listdir(current)
            except OSError:
                continue
            pending.extend(os.path.join(current, n) for n in names)
        elif stat.S_ISREG(st.st_mode):
            total += st.st_size
    return total


def count_nodes(path):
    count = 0
    pending = [_clean(path)]
    while pending:
        current = pending.pop()
        count += 1
        try:
            st = os.lstat(current)
            if stat.S_ISDIR(st.st_mode):
                pending.extend(os.path.join(current, n)
                               for n in os.listdir(current))
        except OSError:
            continue
    return count


# --------------------------------------------------------------------------
# Copiar
# --------------------------------------------------------------------------

def _is_inside(child, parent):
    child = os.path.realpath(child)
    parent = os.path.realpath(parent)
    return child == parent or child.startswith(parent.rstrip('/') + '/')


def _report(progress, state, total, name):
    if progress is not None:
        progress(state['done'], total, name)


def _copy_file(src, dst, st, cancellable, progress, state, total):
    name = os.path.basename(src)
    fin = open(src, 'rb')
    try:
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        fout = os.fdopen(fd, 'wb')
        try:
            while True:
                _check(cancellable)
                chunk = fin.read(_CHUNK)
                if not chunk:
                    break
                fout.write(chunk)
                state['done'] += len(chunk)
                _report(progress, state, total, name)
        finally:
            fout.close()
    finally:
        fin.close()
    os.chmod(dst, stat.S_IMODE(st.st_mode))
    try:
        os.utime(dst, (st.st_atime, st.st_mtime))
    except OSError:
        pass


def _copy_node(src, dst, cancellable, progress, state, total):
    _check(cancellable)
    st = os.lstat(src)
    mode = st.st_mode
    if stat.S_ISLNK(mode):
        os.symlink(os.readlink(src), dst)
    elif stat.S_ISDIR(mode):
        os.mkdir(dst, 0o700)
        for name in sorted(os.listdir(src)):
            _copy_node(os.path.join(src, name), os.path.join(dst, name),
                       cancellable, progress, state, total)
        os.chmod(dst, stat.S_IMODE(mode))
        try:
            os.utime(dst, (st.st_atime, st.st_mtime))
        except OSError:
            pass
    elif stat.S_ISREG(mode):
        _copy_file(src, dst, st, cancellable, progress, state, total)
    # sockets, tuberías y dispositivos: se ignoran


def _remove_quiet(path):
    try:
        delete(path)
    except FileOpError:
        pass


def copy(src, dst_dir, cancellable=None, progress=None):
    """Copia ``src`` dentro de ``dst_dir`` y devuelve la ruta nueva.

    Si el nombre ya existe en el destino se usa uno libre (``a (2).txt``).
    ``progress(hecho, total, nombre)`` recibe bytes. Si se cancela o falla,
    se elimina lo copiado a medias.
    """
    src = _clean(src)
    dst_dir = _clean(dst_dir)
    if not os.path.lexists(src):
        raise FileOpError('%s (%s)' % (tr('The item no longer exists'),
                                        os.path.basename(src)))
    if (os.path.isdir(src) and not os.path.islink(src)
            and _is_inside(dst_dir, src)):
        raise FileOpError(tr('Cannot copy a folder into itself'))
    name = unique_name(dst_dir, os.path.basename(src))
    dst = os.path.join(dst_dir, name)
    total = tree_size(src)
    state = {'done': 0}
    try:
        _copy_node(src, dst, cancellable, progress, state, total)
    except Cancelled:
        _remove_quiet(dst)
        raise
    except (OSError, IOError) as exc:
        _remove_quiet(dst)
        raise _oserr(N_('Could not copy'), os.path.basename(src), exc)
    if progress is not None:
        progress(total, total, name)
    return dst


# --------------------------------------------------------------------------
# Mover
# --------------------------------------------------------------------------

def move(src, dst_dir, cancellable=None, progress=None):
    """Mueve ``src`` a ``dst_dir``. Entre sistemas de ficheros copia y borra."""
    src = _clean(src)
    dst_dir = _clean(dst_dir)
    if not os.path.lexists(src):
        raise FileOpError('%s (%s)' % (tr('The item no longer exists'),
                                        os.path.basename(src)))
    if os.path.dirname(src) == dst_dir:
        return src
    if (os.path.isdir(src) and not os.path.islink(src)
            and _is_inside(dst_dir, src)):
        raise FileOpError(tr('Cannot copy a folder into itself'))
    name = unique_name(dst_dir, os.path.basename(src))
    dst = os.path.join(dst_dir, name)
    try:
        os.rename(src, dst)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise _oserr(N_('Could not move'), os.path.basename(src), exc)
    else:
        if progress is not None:
            progress(1, 1, name)
        return dst
    new_path = copy(src, dst_dir, cancellable, progress)
    delete(src)
    return new_path


# --------------------------------------------------------------------------
# Borrar
# --------------------------------------------------------------------------

def delete(path, cancellable=None, progress=None):
    """Borra un archivo o una carpeta entera. Los enlaces no se siguen."""
    path = _clean(path)
    if path == '/' or os.path.realpath(path) == '/':
        raise FileOpError(tr('Refusing to operate on the root folder'))
    if not os.path.lexists(path):
        raise FileOpError('%s (%s)' % (tr('The item no longer exists'),
                                        os.path.basename(path)))
    total = count_nodes(path) if progress is not None else 0
    done = [0]

    def remove(current):
        _check(cancellable)
        st = os.lstat(current)
        if stat.S_ISDIR(st.st_mode):
            for name in os.listdir(current):
                remove(os.path.join(current, name))
            os.rmdir(current)
        else:
            os.unlink(current)
        done[0] += 1
        if progress is not None:
            progress(done[0], total, os.path.basename(current))

    try:
        remove(path)
    except (OSError, IOError) as exc:
        raise _oserr(N_('Could not delete'), os.path.basename(path), exc)


_warm_up()
