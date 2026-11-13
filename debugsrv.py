# -*- coding: utf-8 -*-
"""Servidor de depuración de Archivos.

Solo se arranca si el entorno trae ARCHIVOS_DEBUG=1. Escucha en un socket
Unix (/tmp/archivos-debug.sock, permisos 600) y acepta una orden JSON por
línea. Permite desde SSH, sin tocar nada del sistema:

    {"cmd": "ping"}
    {"cmd": "eval", "code": "app.current_view().path"}   # app = la actividad
    {"cmd": "shot", "dir": "/tmp/archivos-shots"}         # PNG de CADA ventana
    {"cmd": "tree"}                                       # árbol de widgets

``shot`` solo captura las ventanas de esta actividad (la principal y los
menús desplegados), nunca el resto de la pantalla. Cliente: tools/dbg.py.
"""
import json
import os
import socket
import sys
import traceback

from gi.repository import Gdk, Gio, GLib, Gtk

try:
    from cStringIO import StringIO
except ImportError:             # pragma: no cover
    from io import StringIO

SOCK = os.environ.get('ARCHIVOS_DEBUG_SOCK', '/tmp/archivos-debug.sock')


def start(app):
    return DebugServer(app)


class FakeEvent(object):
    """Evento de ratón mínimo para llamar a los manejadores de FileView."""

    def __init__(self, etype, button=1, x=0, y=0, state=0, time=0):
        self.type, self.button, self.x, self.y = etype, button, x, y
        self.state, self.time = state, time


def click_row(view, name, button=1, state=0):
    """Pulsa y suelta ``button`` sobre la fila ``name`` de la vista."""
    tree_path = view._row_path(name)
    if tree_path is None:
        raise KeyError('no hay fila %r' % (name,))
    rect = view.tree.get_cell_area(tree_path, view._name_col)
    x, y = rect.x + 40, rect.y + rect.height // 2
    press = FakeEvent(Gdk.EventType.BUTTON_PRESS, button, x, y, state)
    release = FakeEvent(Gdk.EventType.BUTTON_RELEASE, button, x, y, state)
    handled = view._on_press(view.tree, press)
    view._on_release(view.tree, release)
    return handled


class DebugServer(object):

    def __init__(self, app):
        self.app = app
        try:
            os.unlink(SOCK)
        except OSError:
            pass
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(SOCK)
        os.chmod(SOCK, 0o600)
        self._srv.listen(2)
        self._srv.setblocking(False)
        try:
            GLib.io_add_watch(self._srv.fileno(), GLib.IO_IN, self._accept)
        except TypeError:
            GLib.io_add_watch(self._srv.fileno(), GLib.PRIORITY_DEFAULT,
                              GLib.IO_IN, self._accept)

    def _accept(self, *_args):
        try:
            conn, _addr = self._srv.accept()
        except socket.error:
            return True
        conn.settimeout(3)
        try:
            data = b''
            while not data.endswith(b'\n'):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            reply = self._handle(data)
            conn.sendall(json.dumps(reply).encode('utf-8') + b'\n')
        except Exception:
            try:
                conn.sendall(json.dumps(
                    {'ok': False, 'error': traceback.format_exc()}
                ).encode('utf-8') + b'\n')
            except socket.error:
                pass
        finally:
            conn.close()
        return True

    # ------------------------------------------------------------------

    def _handle(self, raw):
        try:
            request = json.loads(raw.decode('utf-8'))
            cmd = request.get('cmd')
        except ValueError:
            return {'ok': False, 'error': 'JSON no valido'}
        if cmd == 'ping':
            return {'ok': True, 'result': 'pong'}
        if cmd == 'eval':
            return self._eval(request.get('code', ''))
        if cmd == 'shot':
            return self._shot(request.get('dir', '/tmp/archivos-shots'))
        if cmd == 'tree':
            return {'ok': True, 'result': self._tree()}
        return {'ok': False, 'error': 'orden desconocida: %r' % (cmd,)}

    def _namespace(self):
        return {'app': self.app, 'view': self.app.current_view(),
                'tab': self.app.current_tab(), 'plugins': self.app._plugins,
                'Gtk': Gtk, 'Gdk': Gdk, 'GLib': GLib, 'Gio': Gio, 'os': os,
                'click_row': click_row, 'FakeEvent': FakeEvent}

    def _eval(self, code):
        namespace = self._namespace()
        out = StringIO()
        old_stdout = sys.stdout
        sys.stdout = out
        try:
            try:
                result = eval(compile(code, '<debug>', 'eval'), namespace)
            except SyntaxError:
                exec(compile(code, '<debug>', 'exec'), namespace)
                result = None
        except Exception:
            sys.stdout = old_stdout
            return {'ok': False, 'error': traceback.format_exc()}
        finally:
            sys.stdout = old_stdout
        return {'ok': True, 'result': repr(result) if result is not None
                else None, 'stdout': out.getvalue()}

    def _shot(self, directory):
        if not os.path.isdir(directory):
            os.makedirs(directory)
        shots = []
        for index, window in enumerate(Gtk.Window.list_toplevels()):
            gdk_window = window.get_window()
            if gdk_window is None or not window.get_visible():
                continue
            width, height = gdk_window.get_width(), gdk_window.get_height()
            pixbuf = Gdk.pixbuf_get_from_window(gdk_window, 0, 0, width,
                                                height)
            if pixbuf is None:
                continue
            path = os.path.join(directory, 'win%d.png' % index)
            pixbuf.savev(path, 'png', [], [])
            shots.append({'path': path, 'type': type(window).__name__,
                          'title': window.get_title(), 'size': [width,
                                                                height]})
        return {'ok': True, 'result': shots}

    def _tree(self):
        lines = []

        def walk(widget, depth):
            if depth > 14:
                return
            text = ''
            for getter in ('get_label', 'get_text'):
                if hasattr(widget, getter):
                    try:
                        value = getattr(widget, getter)()
                    except TypeError:
                        value = None
                    if value:
                        text = ' %r' % (value,)
                        break
            alloc = widget.get_allocation()
            lines.append('%s%s%s [%dx%d]%s%s' % (
                '  ' * depth, type(widget).__name__, text, alloc.width,
                alloc.height, '' if widget.get_visible() else ' (oculto)',
                '' if widget.get_sensitive() else ' (inactivo)'))
            if isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    walk(child, depth + 1)

        for window in Gtk.Window.list_toplevels():
            if window.get_visible():
                lines.append('== ventana: %s %r' % (type(window).__name__,
                                                    window.get_title()))
                walk(window, 1)
        return '\n'.join(lines)
