# -*- coding: utf-8 -*-
"""Plugin «Media player»: reproduce vídeo y audio con GStreamer.

Usa ``playbin`` con ``xvimagesink`` pintando en un ``Gtk.DrawingArea``
(``GstVideo.VideoOverlay``). Solo abre lo que el sistema decodifica (Theora y
VP8 con Vorbis, en Ogg o WebM); con otra cosa lo dice en la propia pestaña.
GStreamer se importa al abrir la primera pestaña, no al cargar el plugin, para
no gastar memoria en quien nunca reproduce nada.

Tres modos de ver: normal (estirado a la ventana, con la proporción), 1:1 (a su
tamaño, centrado, sin escalar) y pantalla completa (sin barras ni controles;
Esc vuelve al modo normal).
"""
import os

import gi
from gi.repository import Gdk, GLib, Gtk, Pango

import fileops
import pluginapi
from i18n import N_
from pluginui import PluginTab, icon_button
from videoutil import (NS, clamp, format_time, module_decoder_available,
                       mp3_decoder_available, score_for, seek_target)

_gst = None                       # (Gst, GstVideo) tras el primer uso


def _load_gst():
    global _gst
    if _gst is None:
        gi.require_version('Gst', '1.0')
        gi.require_version('GstVideo', '1.0')
        gi.require_version('GdkX11', '3.0')
        from gi.repository import GdkX11, Gst, GstVideo
        GdkX11.X11Window                    # get_xid() de las ventanas
        Gst.init(None)
        # gst-libav trae los decodificadores de MP3 con rango 0 (decodebin no los
        # elige solos): se sube el de coma fija, que en el Geode es ~40 % más rápido
        # que el de coma flotante.
        factory = Gst.ElementFactory.find('avdec_mp3')
        if factory is not None and factory.get_rank() == 0:
            factory.set_rank(Gst.Rank.MARGINAL)
        _gst = (Gst, GstVideo)
    return _gst


class Plugin(pluginapi.Plugin):
    id = 'video'
    name = N_('Media player')

    def handles(self, path, content_type):
        return score_for(content_type, mp3_decoder_available(),
                         module_decoder_available())

    def open_tab(self, path):
        _load_gst()
        return VideoTab(self.host, self, path)


class VideoTab(PluginTab):

    # Pestañas vivas: el audio (ALSA directo, sin mezclador) y el overlay Xv del XO
    # los abre un solo reproductor a la vez; al empezar uno, los demás se sueltan.
    _instances = []
    _IDLE_AUDIO = 10          # s en pausa antes de soltar el dispositivo (audio)
    _IDLE_VIDEO = 120         # idem con vídeo (se pierde el fotograma)
    _IDLE_END = 10            # idem tras llegar al final

    def __init__(self, host, plugin, path):
        PluginTab.__init__(self, host, plugin, path)
        self._Gst, self._GstVideo = _load_gst()
        self._player = None
        self._bus = None
        self._xid = None
        self._playing = False
        self._started = False
        self._duration = 0
        self._volume = 1.0
        self._pending_seek = None
        self._timer = None
        self._failed = False
        self._ended = False
        self._mode = 'fit'               # 'fit' (normal) o 'actual' (1:1)
        self._fullscreen = False
        self._video_size = (0, 0)
        self._rect = None                # zona de la ventana que usa el vídeo
        # ¿hay imagen? None = aún no se sabe; False = solo audio (panel negro y sin
        # botones de modos de vídeo)
        self._holds_port = False         # ¿usa el puerto Xv (solo hay uno)?
        self._idle_id = None
        self._released = False           # pestaña oculta con el reproductor soltado
        self._resume_at = 0
        self._has_video = None
        ctype = fileops.content_type_for(os.path.basename(path))
        if (ctype or '').startswith('audio/'):
            self._has_video = False
        self._build()
        VideoTab._instances.append(self)

    # ------------------------------------------------------------------
    # Interfaz
    # ------------------------------------------------------------------

    def _build(self):
        tr = self.plugin.tr
        self._area = Gtk.DrawingArea()
        self._area.override_background_color(Gtk.StateFlags.NORMAL,
                                             Gdk.RGBA(0, 0, 0, 1))
        self._area.set_can_focus(True)
        # El vídeo (overlay Xv) lo pinta GStreamer directamente en la ventana: con
        # el doble búfer de GTK se borraría en cada repintado y sin fondo propio
        # GDK lo taparía con negro.
        self._area.set_double_buffered(False)
        self._area.set_app_paintable(True)
        self._area.add_events(Gdk.EventMask.KEY_PRESS_MASK |
                              Gdk.EventMask.BUTTON_PRESS_MASK)
        self._area.connect('realize', self._on_realize)
        self._area.connect('draw', self._on_draw)
        self._area.connect('size-allocate', self._on_size_allocate)
        self._area.connect('key-press-event', self._on_key)
        self._area.connect('button-press-event', self._on_click)
        self.pack_start(self._area, True, True, 0)

        self._bar = Gtk.EventBox()
        self._bar.override_background_color(Gtk.StateFlags.NORMAL,
                                            Gdk.RGBA(0.16, 0.16, 0.16, 1))
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_border_width(4)
        self._play = icon_button('media-playback-start', tr('Play'),
                                 lambda _b: self.toggle())
        row.pack_start(self._play, False, False, 0)
        self._seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,
                                              0, 1, 1)
        self._seek.set_draw_value(False)
        self._seek.set_sensitive(False)
        self._seek.connect('change-value', self._on_seek)
        row.pack_start(self._seek, True, True, 8)
        self._label = Gtk.Label()
        self._label.override_color(Gtk.StateFlags.NORMAL,
                                   Gdk.RGBA(1, 1, 1, 1))
        row.pack_start(self._label, False, False, 4)
        self._vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,
                                             0, 1, 0.05)
        self._vol.set_draw_value(False)
        self._vol.set_value(self._volume)
        self._vol.set_size_request(110, -1)
        self._vol.set_tooltip_text(tr('Volume'))
        self._vol.connect('value-changed', self._on_volume)
        row.pack_start(self._vol, False, False, 0)
        # Modos de ver: normal y 1:1 se excluyen; la pantalla completa es una
        # acción (se sale con Esc).
        self._fit = icon_button('archivos-video-fit',
                                tr('Normal: fit to the window'),
                                self._on_fit_toggled, toggle=True)
        self._actual = icon_button('archivos-video-actual',
                                   tr('Actual size (1:1)'),
                                   self._on_actual_toggled, toggle=True)
        self._full = icon_button('archivos-video-full', tr('Full screen'),
                                 lambda _b: self.set_fullscreen(True))
        for button in (self._fit, self._actual, self._full):
            row.pack_start(button, False, False, 0)
        self._mode_buttons = (self._fit, self._actual, self._full)
        self._sync_mode_buttons()
        self._bar.add(row)
        self.pack_start(self._bar, False, False, 0)
        self._set_time(0)
        self.show_all()
        self._update_video_ui()

    def _update_video_ui(self):
        """Los botones de modos de vídeo solo si hay vídeo."""
        for button in self._mode_buttons:
            button.set_no_show_all(True)
            button.set_visible(self._has_video is not False)

    def _set_time(self, position):
        self._label.set_text('%s / %s' % (format_time(position),
                                          format_time(self._duration)))

    def _set_playing(self, playing):
        self._playing = playing
        tr = self.plugin.tr
        icon = 'media-playback-pause' if playing else 'media-playback-start'
        button = self._play
        button.get_child().props.icon_name = icon
        button.set_tooltip_text(tr('Pause') if playing else tr('Play'))
        self._ensure_timer()
        if playing:
            self._cancel_idle()
        elif self._player is not None:
            self._schedule_idle(self._IDLE_VIDEO if self._has_video
                                else self._IDLE_AUDIO)

    # ------------------------------------------------------------------
    # Modos de ver y colocación del vídeo
    # ------------------------------------------------------------------

    def _sync_mode_buttons(self):
        for button, handler, mode in ((self._fit, self._on_fit_toggled, 'fit'),
                                      (self._actual, self._on_actual_toggled,
                                       'actual')):
            button.handler_block_by_func(handler)
            button.set_active(self._mode == mode)
            button.handler_unblock_by_func(handler)

    def _set_mode(self, mode):
        self._mode = mode
        self._sync_mode_buttons()
        self._apply_layout()

    def _on_fit_toggled(self, button):
        self._set_mode('fit')

    def _on_actual_toggled(self, button):
        self._set_mode('actual')

    def set_fullscreen(self, on):
        """Pantalla completa: sin barras ni controles. Siempre ajustado a la
        pantalla; al salir vuelve al modo normal."""
        if on == self._fullscreen:
            return
        if on and self._has_video is False:
            return
        self._fullscreen = on
        if on:
            self._mode = 'fit'
            self._sync_mode_buttons()
        self._bar.set_visible(not on)
        self.host.set_fullscreen(on)
        window = self._area.get_window()
        if window is not None:
            window.set_cursor(Gdk.Cursor.new(Gdk.CursorType.BLANK_CURSOR)
                              if on else None)
        self._area.grab_focus()
        self._apply_layout()
        GLib.timeout_add(300, self._apply_layout)     # cuando la ventana ya cambió de tamaño

    def _read_video_size(self):
        """Tamaño en píxeles del vídeo (0, 0 si aún no se conoce)."""
        if self._video_size[0] or self._player is None:
            return self._video_size
        try:
            pad = self._player.emit('get-video-pad', 0)
            caps = pad.get_current_caps() if pad is not None else None
            if caps is not None:
                structure = caps.get_structure(0)
                ok_w, width = structure.get_int('width')
                ok_h, height = structure.get_int('height')
                if ok_w and ok_h:
                    self._video_size = (width, height)
        except Exception:
            pass
        return self._video_size

    def _apply_layout(self):
        """Coloca el vídeo en la ventana según el modo."""
        if self._player is None or self._failed or self._has_video is False:
            return False
        alloc = self._area.get_allocation()
        width, height = alloc.width, alloc.height
        if width <= 1 or height <= 1:
            return False
        rect = (0, 0, width, height)
        if self._mode == 'actual' and not self._fullscreen:
            vw, vh = self._read_video_size()
            if vw and vh and vw <= width and vh <= height:
                rect = ((width - vw) // 2, (height - vh) // 2, vw, vh)
        self._rect = rect
        self._overlay().set_render_rectangle(self._player, *rect)
        self._area.queue_draw()
        self._overlay().expose(self._player)
        return False

    def _on_size_allocate(self, _area, _allocation):
        GLib.idle_add(self._apply_layout)

    def _on_draw(self, widget, cr):
        if self._has_video is not True:
            # Sin imagen (solo audio, o aún no se sabe): panel negro. El área no
            # tiene fondo ni doble búfer, así que si no se pinta se ve lo de debajo.
            cr.set_source_rgb(0, 0, 0)
            cr.paint()
            return False
        # Las franjas negras alrededor del vídeo en modo 1:1 (el vídeo lo pinta
        # GStreamer directamente en la ventana)
        rect = self._rect
        if rect is not None:
            alloc = widget.get_allocation()
            x, y, w, h = rect
            if (w, h) != (alloc.width, alloc.height):
                cr.set_source_rgb(0, 0, 0)
                cr.rectangle(0, 0, alloc.width, y)
                cr.rectangle(0, y + h, alloc.width, alloc.height - y - h)
                cr.rectangle(0, y, x, h)
                cr.rectangle(x + w, y, alloc.width - x - w, h)
                cr.fill()
        if self._started and not self._failed and self._player is not None:
            self._overlay().expose(self._player)
        return False

    # ------------------------------------------------------------------
    # GStreamer
    # ------------------------------------------------------------------

    def _overlay(self):
        return self._GstVideo.VideoOverlay

    def _on_realize(self, area):
        window = area.get_window()
        window.ensure_native()
        window.set_background_pattern(None)
        self._xid = window.get_xid()
        area.grab_focus()
        GLib.idle_add(self._start)

    def _start(self, paused=False):
        if self._started or self._player is not None:
            return False
        self._release_others()
        Gst = self._Gst
        player = Gst.ElementFactory.make('playbin', 'archivos-player')
        if self._has_video is False:
            # Solo audio: un sumidero que no toca el puerto Xv (en el Geode hay
            # uno solo y, ocupado, un vídeo en otra pestaña no se puede abrir)
            sink = Gst.ElementFactory.make('fakesink', None)
        else:
            sink = Gst.ElementFactory.make('xvimagesink', None)
            self._holds_port = sink is not None
        if player is None:
            self._fail(self.plugin.tr('GStreamer is not available'))
            return False
        if sink is not None:
            if self._holds_port:
                sink.set_property('handle-events', False)   # los eventos son de GTK
            player.set_property('video-sink', sink)
        player.set_property('uri', 'file://' + _quote(self.path))
        player.set_property('volume', self._volume)
        self._player = player
        if self._holds_port:
            self._overlay().set_window_handle(player, self._xid)
        self._bus = player.get_bus()
        self._bus.add_signal_watch()
        self._bus.connect('message::eos', self._on_eos)
        self._bus.connect('message::error', self._on_error)
        self._bus.connect('message::async-done', self._on_async_done)
        self._started = True
        if paused:
            player.set_state(Gst.State.PAUSED)
            self._set_playing(False)
        else:
            player.set_state(Gst.State.PLAYING)
            self._set_playing(True)
        return False

    def _on_async_done(self, _bus, _msg):
        self._read_duration()
        self._detect_video()
        self._apply_layout()
        if self._pending_seek:
            target, self._pending_seek = self._pending_seek, None
            self._seek_to(target)

    def _on_eos(self, _bus, _msg):
        self._ended = True
        self._player.set_state(self._Gst.State.PAUSED)
        self._seek_to(0)
        self._set_playing(False)
        self._seek.set_value(0)
        self._set_time(0)
        self._schedule_idle(self._IDLE_END)

    def _on_error(self, _bus, msg):
        error, _debug = msg.parse_error()
        tr = self.plugin.tr
        text = error.message
        if 'audiosink' in text:
            text = tr('The sound device is busy')
        elif 'videosink' in text:
            text = tr('The video output is busy')
        self._fail('%s: %s' % (tr('Could not play'), text))

    def _fail(self, text):
        self._failed = True
        self.set_fullscreen(False)
        self._label.set_text(text)
        self._label.set_ellipsize(Pango.EllipsizeMode.END)
        self._stop_player()
        self._set_playing(False)
        self._seek.set_sensitive(False)
        self.host.show_message(text, self.plugin.display_name())

    def _release_others(self):
        for tab in list(VideoTab._instances):
            if tab is not self:
                tab._release()

    def _schedule_idle(self, seconds):
        self._cancel_idle()
        self._idle_id = GLib.timeout_add_seconds(seconds, self._idle_release)

    def _cancel_idle(self):
        if self._idle_id is not None:
            GLib.source_remove(self._idle_id)
            self._idle_id = None

    def _idle_release(self):
        self._idle_id = None
        if not self._playing:
            self._release()
        return False

    def _resume(self, play):
        """Recrea el reproductor soltado, en la posición en que se dejó."""
        self._released = False
        self._pending_seek = int(self._resume_at)
        self._start(paused=not play)

    def _release(self):
        """Suelta el reproductor (y el puerto Xv) al ocultarse la pestaña,
        recordando la posición; al volver se recrea en pausa."""
        if self._player is None:
            return
        self._resume_at = 0 if self._ended else self._position()
        self._cancel_idle()
        self._released = True
        self._stop_player()
        self._started = False
        self._holds_port = False
        self._set_playing(False)

    def _stop_player(self):
        if self._bus is not None:
            self._bus.remove_signal_watch()
            self._bus = None
        if self._player is not None:
            self._player.set_state(self._Gst.State.NULL)
            self._player = None

    def _detect_video(self):
        if self._has_video is None and self._player is not None:
            self._has_video = self._player.get_property('n-video') > 0
            self._update_video_ui()
            self._area.queue_draw()

    def _read_duration(self):
        if self._player is None:
            return
        ok, duration = self._player.query_duration(self._Gst.Format.TIME)
        if ok and duration > 0:
            self._duration = duration
            seconds = max(duration / float(NS), 1.0)
            self._seek.set_range(0, seconds)
            self._seek.set_sensitive(True)

    def _position(self):
        if self._player is None:
            return 0
        ok, position = self._player.query_position(self._Gst.Format.TIME)
        return position if ok else 0

    def _seek_to(self, nanoseconds):
        if self._player is None:
            return
        Gst = self._Gst
        self._player.seek_simple(Gst.Format.TIME,
                                 Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                                 int(nanoseconds))

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------

    def toggle(self):
        self._ended = False
        if self._failed:
            return
        if self._player is None:
            if self._released:
                self._resume(play=True)
            return
        Gst = self._Gst
        if self._playing:
            self._player.set_state(Gst.State.PAUSED)
            self._set_playing(False)
        else:
            self._player.set_state(Gst.State.PLAYING)
            self._set_playing(True)

    def _on_seek(self, _scale, _scroll, value):
        self._ended = False
        if self._released and self._duration > 0:
            seconds = clamp(value, 0, self._duration / float(NS))
            self._resume_at = seconds * NS
            self._set_time(self._resume_at)
            return False
        if self._player is None or self._duration <= 0:
            return False
        seconds = clamp(value, 0, self._duration / float(NS))
        self._seek_to(seconds * NS)
        self._set_time(seconds * NS)
        return False

    def _on_volume(self, scale):
        self._volume = scale.get_value()
        if self._player is not None:
            self._player.set_property('volume', self._volume)

    def _on_click(self, _widget, event):
        self._area.grab_focus()
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 1:
            self.toggle()
        return True

    def _on_key(self, _widget, event):
        name = Gdk.keyval_name(event.keyval) or ''
        if name in ('space', 'Return', 'KP_Enter', 'p'):
            self.toggle()
        elif name == 'Escape':
            if not self._fullscreen:
                return False
            self.set_fullscreen(False)
        elif name in ('f', 'F11'):
            self.set_fullscreen(not self._fullscreen)
        elif name in ('Right', 'Left', 'Page_Up', 'Page_Down'):
            step = {'Right': 5, 'Left': -5, 'Page_Up': 30,
                    'Page_Down': -30}[name]
            self._seek_to(seek_target(self._position(), step,
                                      self._duration))
        elif name in ('Up', 'Down'):
            self._vol.set_value(clamp(self._volume +
                                      (0.1 if name == 'Up' else -0.1), 0, 1))
        else:
            return False
        return True

    # ------------------------------------------------------------------
    # Posición en pantalla
    # ------------------------------------------------------------------

    def _ensure_timer(self):
        if self._playing and self._timer is None:
            self._timer = GLib.timeout_add(500, self._tick)

    def _tick(self):
        if not self._playing or self._player is None:
            self._timer = None
            return False
        if self._duration <= 0:
            self._read_duration()
        position = self._position()
        self._set_time(position)
        if self._duration > 0:
            self._seek.set_value(position / float(NS))
        return True

    # ------------------------------------------------------------------
    # Contrato de PluginTab
    # ------------------------------------------------------------------

    def get_state(self):
        position = self._resume_at if self._released else self._position()
        return {'position': 0 if self._ended else int(position // NS),
                'volume': self._volume, 'mode': self._mode}

    def restore_state(self, state):
        volume = state.get('volume')
        if isinstance(volume, (int, float)):
            self._volume = clamp(float(volume), 0.0, 1.0)
            self._vol.set_value(self._volume)
        position = state.get('position')
        if isinstance(position, (int, float)) and position > 0:
            self._pending_seek = int(position) * NS
        if state.get('mode') == 'actual':
            self._mode = 'actual'
            self._sync_mode_buttons()

    def on_shown(self):
        if self._released and not self._failed and self._has_video:
            self._resume(play=False)
        self._area.grab_focus()
        GLib.idle_add(self._apply_layout)

    def on_hidden(self):
        self.set_fullscreen(False)
        # Un vídeo oculto suelta el puerto Xv (hay uno solo) y se pausa; el audio
        # sigue sonando en segundo plano.
        if self._holds_port:
            self._release()

    def dispose(self):
        self.set_fullscreen(False)
        self._cancel_idle()
        if self in VideoTab._instances:
            VideoTab._instances.remove(self)
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None
        self._playing = False
        self._stop_player()


def _quote(path):
    """Ruta como parte de una URI ``file://`` (sin la cabecera)."""
    from urllib import quote
    return quote(path, safe='/')
