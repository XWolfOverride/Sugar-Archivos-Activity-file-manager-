# -*- coding: utf-8 -*-
"""Actividades de Sugar instaladas que saben abrir un tipo de archivo.

Las actividades no son aplicaciones de escritorio (no hay ``.desktop``), así
que ``Gio`` no las conoce. Aquí se leen sus ``activity.info`` (la clave
``mime_types``) y se lanza la elegida pasándole el archivo como ``uri``, que es
lo que hace la propia shell de Sugar (``activityfactory.create_with_uri``) y
evita copiar el archivo al Diario (ocuparía flash interna).

Sin GTK a propósito: solo se importa ``Gio`` (perezosamente) para el árbol de
tipos MIME, y ``sugar3`` al lanzar.
"""
import os

try:                                    # Python 2
    import ConfigParser as configparser
except ImportError:                     # pragma: no cover
    import configparser

# Tipos que casi cualquier actividad declara «por si acaso»: no bastan para
# abrir un archivo con un clic, solo para ofrecerlos en «Abrir con».
GENERIC_TYPES = ('text/plain', 'application/zip', 'application/octet-stream')

_OWN_DIR = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))

_cache = {'stamp': None, 'items': []}


class SugarActivity(object):
    """Los datos de ``activity.info`` que hacen falta para ofrecerla."""

    def __init__(self, path, name, bundle_id, mime_types):
        self.path = path
        self.name = name
        self.bundle_id = bundle_id
        self.mime_types = mime_types

    def __repr__(self):
        return '<SugarActivity %s>' % self.bundle_id


def search_roots():
    """Carpetas donde se instalan las actividades (existan o no)."""
    roots = [os.path.expanduser('~/Activities'),
             '/usr/share/sugar/activities']
    extra = os.environ.get('SUGAR_ACTIVITIES_PATH')
    if extra:
        roots = [p for p in extra.split(os.pathsep) if p] + roots
    return roots


def parse_info(path):
    """Lee ``<path>/activity/activity.info``; ``None`` si no es una actividad."""
    info = os.path.join(path, 'activity', 'activity.info')
    parser = configparser.RawConfigParser()
    try:
        if not parser.read(info) or not parser.has_section('Activity'):
            return None
        get = lambda key: (parser.get('Activity', key)
                           if parser.has_option('Activity', key) else '')
        bundle_id = get('bundle_id').strip()
        if not bundle_id:
            return None
        mimes = [m.strip() for m in get('mime_types').split(';') if m.strip()]
        return SugarActivity(path, get('name').strip() or bundle_id,
                             bundle_id, mimes)
    except configparser.Error:
        return None


def _stamp(roots):
    stamp = []
    for root in roots:
        try:
            stamp.append((root, os.stat(root).st_mtime))
        except OSError:
            stamp.append((root, None))
    return stamp


def installed(roots=None):
    """Las actividades instaladas, por nombre. Se vuelve a leer solo si cambió
    alguna carpeta de instalación (barato: unos cuantos ``stat``)."""
    use_cache = roots is None
    if roots is None:
        roots = search_roots()
    stamp = _stamp(roots)
    if use_cache and _cache['stamp'] == stamp:
        return _cache['items']
    found = {}
    for root in roots:
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            if not name.endswith('.activity'):
                continue
            path = os.path.join(root, name)
            if os.path.realpath(path) == _OWN_DIR:
                continue                # esta misma actividad
            item = parse_info(path)
            if item is not None and item.bundle_id not in found:
                found[item.bundle_id] = item      # gana la primera carpeta
    items = sorted(found.values(), key=lambda a: a.name.lower())
    if use_cache:
        _cache['stamp'], _cache['items'] = stamp, items
    return items


def _is_a(content_type, parent):
    if content_type == parent:
        return True
    try:
        from gi.repository import Gio
        return Gio.content_type_is_a(content_type, parent)
    except Exception:
        return False


def handlers_for(content_type, strict=False, activities=None):
    """Actividades que declaran el tipo ``content_type`` (o uno del que
    derive). Con ``strict`` se ignoran los tipos genéricos de
    ``GENERIC_TYPES``: es lo que decide si un clic basta para abrir."""
    if not content_type:
        return []
    if activities is None:
        activities = installed()
    result = []
    for act in activities:
        for mime in act.mime_types:
            if strict and mime in GENERIC_TYPES:
                continue
            if _is_a(content_type, mime):
                result.append(act)
                break
    return result


def launch(activity, path):
    """Abre ``path`` en una instancia nueva de ``activity``.

    El ``uri`` es ``file://`` + ruta **sin codificar**: así lo espera Read (y
    la shell de Sugar lo pasa tal cual), que quita el prefijo y usa el resto
    como ruta.
    """
    from sugar3.activity import activityfactory
    from sugar3.bundle.activitybundle import ActivityBundle
    activityfactory.create_with_uri(ActivityBundle(activity.path),
                                    'file://' + path)
