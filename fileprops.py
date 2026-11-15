# -*- coding: utf-8 -*-
"""Datos, propietario y permisos de un archivo o carpeta (sin GTK).

Lo usa el diálogo de propiedades (``propsdialog.py``). Cambiar los permisos
solo puede quien es el propietario (o root); cambiar el propietario, solo
root; el grupo, el propietario a uno de sus grupos.
"""
import grp
import os
import pwd
import stat

import fileops
from i18n import tr

_BITS = (stat.S_IRUSR, stat.S_IWUSR, stat.S_IXUSR,
         stat.S_IRGRP, stat.S_IWGRP, stat.S_IXGRP,
         stat.S_IROTH, stat.S_IWOTH, stat.S_IXOTH)
PERM_MASK = 0o777


class Info(object):
    """Lo que se enseña de un elemento (``describe``)."""

    def __init__(self):
        self.path = ''
        self.name = ''
        self.is_dir = False
        self.is_link = False
        self.link_target = None
        self.size = 0
        self.items = None          # elementos de una carpeta (None si no se pudo)
        self.mime = ''
        self.type_description = ''
        self.mode = 0
        self.uid = 0
        self.gid = 0
        self.owner = ''
        self.group = ''
        self.atime = 0
        self.mtime = 0
        self.ctime = 0
        self.created = None        # fecha de creación si el sistema la guarda


def user_name(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def group_name(gid):
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def _mime(path, is_dir):
    try:
        from gi.repository import Gio
        info = Gio.File.new_for_path(path).query_info(
            'standard::content-type,time::created',
            Gio.FileQueryInfoFlags.NONE, None)
        ctype = info.get_content_type()
        desc = Gio.content_type_get_description(ctype) or ''
        created = info.get_attribute_uint64('time::created') or None
        return ctype, desc, created
    except Exception:
        return fileops.content_type_for(os.path.basename(path), is_dir), '', \
            None


def describe(path):
    """Un ``Info`` del elemento. Lanza ``fileops.FileOpError`` si no existe."""
    info = Info()
    path = os.path.normpath(path)
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise fileops.FileOpError('%s: %s' % (tr('Could not read'),
                                              exc.strerror))
    info.path = path
    info.name = os.path.basename(path) or '/'
    info.is_link = stat.S_ISLNK(st.st_mode)
    if info.is_link:
        try:
            info.link_target = os.readlink(path)
            st_real = os.stat(path)
        except OSError:
            st_real = st
    else:
        st_real = st
    info.is_dir = stat.S_ISDIR(st_real.st_mode)
    info.size = st.st_size
    if info.is_dir:
        try:
            info.items = len(os.listdir(path))
        except OSError:
            info.items = None
    info.mime, info.type_description, info.created = _mime(path, info.is_dir)
    info.mode = stat.S_IMODE(st.st_mode)
    info.uid, info.gid = st.st_uid, st.st_gid
    info.owner, info.group = user_name(st.st_uid), group_name(st.st_gid)
    info.atime, info.mtime, info.ctime = st.st_atime, st.st_mtime, st.st_ctime
    return info


def mode_string(mode):
    """``rwxr-xr-x`` de los nueve bits de permisos."""
    return ''.join(c if mode & bit else '-'
                   for bit, c in zip(_BITS, 'rwxrwxrwx'))


def bits_from_flags(flags):
    """Nueve booleanos (r w x del propietario, grupo, otros) → bits."""
    mode = 0
    for bit, on in zip(_BITS, flags):
        if on:
            mode |= bit
    return mode


def flags_from_mode(mode):
    return [bool(mode & bit) for bit in _BITS]


def can_chmod(info):
    return os.geteuid() == 0 or os.geteuid() == info.uid


def can_chown_owner():
    return os.geteuid() == 0


def can_chown_group(info):
    return os.geteuid() == 0 or os.geteuid() == info.uid


def my_groups():
    """Nombres de los grupos a los que se puede pasar un archivo propio."""
    gids = set(os.getgroups())
    gids.add(os.getegid())
    return sorted(group_name(g) for g in gids)


def lookup_user(name):
    try:
        return pwd.getpwnam(name).pw_uid
    except KeyError:
        raise fileops.FileOpError('%s: %s' % (tr('Unknown user'), name))


def lookup_group(name):
    try:
        return grp.getgrnam(name).gr_gid
    except KeyError:
        raise fileops.FileOpError('%s: %s' % (tr('Unknown group'), name))


def apply_changes(info, perm_bits=None, owner=None, group=None):
    """Aplica lo que haya cambiado respecto a ``info``; devuelve cuántas cosas
    se cambiaron. Los bits especiales (setuid, setgid, sticky) se conservan."""
    changed = 0
    uid, gid = -1, -1
    if owner is not None and owner != info.owner:
        uid = lookup_user(owner)
    if group is not None and group != info.group:
        gid = lookup_group(group)
    try:
        if uid != -1 or gid != -1:
            os.lchown(info.path, uid, gid)
            changed += 1
        if perm_bits is not None and \
                (perm_bits & PERM_MASK) != (info.mode & PERM_MASK) \
                and not info.is_link:
            new = (info.mode & ~PERM_MASK) | (perm_bits & PERM_MASK)
            os.chmod(info.path, new)
            changed += 1
    except OSError as exc:
        raise fileops.FileOpError('%s: %s' % (tr('Could not change'),
                                              exc.strerror))
    return changed
