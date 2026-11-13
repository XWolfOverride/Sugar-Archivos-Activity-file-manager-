# -*- coding: utf-8 -*-
"""Funciones del visor de imágenes que no necesitan GTK (se prueban sin pantalla)."""
import os


def fit_size(width, height, max_width, max_height):
    """Tamaño de ``width``×``height`` ajustado a la caja, sin ampliar.

    Mantiene la proporción; si ya cabe, se queda como está.
    """
    if width <= 0 or height <= 0:
        return 0, 0
    scale = min(float(max_width) / width, float(max_height) / height, 1.0)
    return max(int(round(width * scale)), 1), max(int(round(height * scale)), 1)


def list_siblings(path, is_image):
    """Imágenes de la carpeta de ``path`` (por nombre) y la posición de ``path``.

    ``is_image(nombre)`` decide qué archivos cuentan. Si ``path`` no estuviera en
    la lista (por ejemplo, un nombre raro) se añade para no perderlo.
    """
    folder = os.path.dirname(path) or '.'
    try:
        names = [n for n in os.listdir(folder)
                 if not n.startswith('.') and is_image(n)
                 and os.path.isfile(os.path.join(folder, n))]
    except OSError:
        names = []
    names.sort(key=lambda n: n.decode('utf-8', 'replace').lower())
    paths = [os.path.join(folder, n) for n in names]
    if path not in paths:
        paths.append(path)
        paths.sort(key=lambda p: os.path.basename(p).decode(
            'utf-8', 'replace').lower())
    return paths, paths.index(path)


def megapixels(width, height):
    return width * height / 1000000.0
