# -*- coding: utf-8 -*-
"""Funciones del reproductor multimedia que no necesitan GTK ni GStreamer."""
import os

# Lo que GStreamer del XO decodifica de serie: Theora y VP8 con audio Vorbis,
# en Ogg o WebM (no hay H.264, MPEG-4 ni MP3).
SURE_TYPES = frozenset((
    'video/ogg', 'video/x-theora+ogg', 'video/x-ogm+ogg', 'video/webm',
    'audio/ogg', 'audio/x-vorbis+ogg', 'audio/webm'))
# Contenedores que pueden llevar de todo: se ofrecen, pero no con un clic.
MAYBE_TYPES = frozenset(('application/ogg', 'video/x-matroska',
                         'audio/x-matroska'))

# MP3: el sistema no trae decodificador; si se instala uno (libav, mad o mpg123 para
# GStreamer) el plugin lo ofrece con un clic. Se detecta por el fichero del plugin de
# GStreamer, sin cargar GStreamer.
MP3_TYPES = frozenset(('audio/mpeg', 'audio/mp3', 'audio/x-mp3', 'audio/x-mpeg'))
MP3_PLUGINS = ('libgstlibav.so', 'libgstmad.so', 'libgstmpg123.so')
PLUGIN_DIRS = ('/usr/lib/gstreamer-1.0', '/usr/lib64/gstreamer-1.0',
               '/usr/lib/i386-linux-gnu/gstreamer-1.0')

# Módulos de tracker (.mod, .xm, .it, .s3m...): los decodifica el elemento ``modplug``
# de GStreamer (paquete gstreamer1-plugins-bad-free-extras + libmodplug).
MODULE_TYPES = frozenset(('audio/x-mod', 'audio/x-xm', 'audio/x-it',
                          'audio/x-s3m', 'audio/x-stm'))
MODULE_PLUGINS = ('libgstmodplug.so',)

NS = 1000000000


def _has_plugin(names, dirs):
    return any(os.path.exists(os.path.join(d, n))
               for d in dirs for n in names)


def mp3_decoder_available(dirs=PLUGIN_DIRS):
    """¿Hay un plugin de GStreamer que decodifique MP3?"""
    return _has_plugin(MP3_PLUGINS, dirs)


def module_decoder_available(dirs=PLUGIN_DIRS):
    """¿Hay un plugin de GStreamer que decodifique módulos de tracker?"""
    return _has_plugin(MODULE_PLUGINS, dirs)


def score_for(content_type, mp3=False, modules=False):
    """Puntuación del plugin (ver ``pluginapi``) para un tipo MIME; ``mp3`` y
    ``modules`` dicen si hay decodificador de MP3 y de módulos de tracker (sin él,
    solo se ofrecen en «Abrir con»)."""
    if content_type in MP3_TYPES:
        return 100 if mp3 else 20
    if content_type in MODULE_TYPES:
        return 100 if modules else 20
    if content_type in SURE_TYPES:
        return 100
    if content_type == 'application/ogg':
        return 60                      # casi siempre es audio o vídeo Ogg
    if content_type in MAYBE_TYPES:
        return 30
    return 0


def format_time(nanoseconds):
    """``m:ss`` (o ``h:mm:ss``) de una duración en nanosegundos."""
    seconds = max(int(nanoseconds // NS), 0) if nanoseconds else 0
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return '%d:%02d:%02d' % (hours, minutes, seconds)
    return '%d:%02d' % (minutes, seconds)


def clamp(value, low, high):
    return max(low, min(high, value))


def seek_target(position, delta_seconds, duration):
    """Nueva posición (ns) al saltar ``delta_seconds`` desde ``position``."""
    target = position + int(delta_seconds * NS)
    top = duration if duration and duration > 0 else target
    return clamp(target, 0, top)
