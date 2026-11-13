# -*- coding: utf-8 -*-
"""Sitios a los que ir: las unidades extraíbles que Sugar tiene montadas.

Sugar monta las memorias USB (cada partición, por separado) y las tarjetas en
``/run/media/<usuario>/<etiqueta>``. Se consultan al abrir el menú, no antes:
así no hay que vigilar nada ni gastar memoria mientras no se usan.
"""
import os

_ROOTS = ('/run/media/', '/media/')


def is_removable_path(path):
    """True si ``path`` está dentro de las carpetas donde se montan los USB."""
    path = path.rstrip('/') + '/'
    return any(path.startswith(root) and len(path) > len(root)
               for root in _ROOTS)


def removable_mounts():
    """``[(nombre, ruta)]`` de las unidades extraíbles montadas, por ruta.

    Gio se importa aquí para que el resto del módulo (y sus pruebas) no lo
    necesiten.
    """
    found = []
    try:
        from gi.repository import Gio
        mounts = Gio.VolumeMonitor.get().get_mounts()
    except Exception:
        return found
    for mount in mounts:
        try:
            if mount.is_shadowed():
                continue
            path = mount.get_root().get_path()
            if not path or not is_removable_path(path) \
                    or not os.path.isdir(path):
                continue
            found.append((mount.get_name() or os.path.basename(path), path))
        except Exception:
            continue
    found.sort(key=lambda entry: entry[1])
    return found
