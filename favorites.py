# -*- coding: utf-8 -*-
"""Carpetas favoritas de la aplicación (sin GTK).

Se guardan en ``~/.config/archivos/favorites.json`` (o bajo
``$XDG_CONFIG_HOME``): son de la aplicación y las comparten todas sus
instancias, no de una entrada del Diario (que es por instancia: «Empezar
nuevo» partiría sin favoritos). Se leen cada vez que se necesitan, así dos
instancias abiertas a la vez se ven entre sí; se escriben de forma atómica.
"""
import json
import os


def store_path():
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')
    return os.path.join(base, 'archivos', 'favorites.json')


def _norm(path):
    return os.path.normpath(path)


def load(store=None):
    """Lista de rutas (``str``) en el orden en que se marcaron."""
    try:
        with open(store or store_path(), 'rb') as handle:
            data = json.loads(handle.read().decode('utf-8'))
    except (IOError, OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    items = []
    for value in data:
        if isinstance(value, (type(u''), str)) and value:
            text = value.encode('utf-8') if isinstance(value, type(u'')) \
                else value
            text = _norm(text)
            if text not in items:
                items.append(text)
    return items


def save(items, store=None):
    store = store or store_path()
    folder = os.path.dirname(store)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    data = json.dumps([i.decode('utf-8', 'replace') for i in items],
                      indent=1)
    temp = store + '.part'
    with open(temp, 'wb') as handle:
        handle.write(data.encode('utf-8'))
    os.rename(temp, store)


def is_favorite(path, store=None):
    return _norm(path) in load(store)


def add(path, store=None):
    items = load(store)
    path = _norm(path)
    if path not in items:
        items.append(path)
        save(items, store)


def remove(path, store=None):
    items = load(store)
    path = _norm(path)
    if path in items:
        items.remove(path)
        save(items, store)


def set_favorite(path, flag, store=None):
    (add if flag else remove)(path, store)


def remove_missing(store=None):
    """Quita las que ya no existen; devuelve cuántas."""
    items = load(store)
    keep = [p for p in items if os.path.isdir(p)]
    if len(keep) != len(items):
        save(keep, store)
    return len(items) - len(keep)
