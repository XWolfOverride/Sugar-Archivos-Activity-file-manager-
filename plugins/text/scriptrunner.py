# -*- coding: utf-8 -*-
"""Ejecuta ``build.sh`` y ``run.sh`` junto al archivo abierto (sin GTK).

Los botones de compilar y ejecutar del editor solo existen si en la carpeta del
archivo hay un ``build.sh`` o un ``run.sh``. El script se ejecuta con ``sh`` en
esa carpeta, con la salida (estándar y de errores) en un solo flujo que llega
poco a poco. Se lanza como grupo de procesos propio para poder pararlo entero,
también los programas que haya arrancado.

Por defecto se usa un ``bash -l`` (shell de inicio de sesión) para que el script
vea el mismo ``PATH`` que en una terminal (compiladores instalados en carpetas
del usuario, por ejemplo); las pruebas usan ``sh`` a secas.
"""
import atexit
import codecs
import os
import signal
import subprocess
import threading
import time

SCRIPT_NAMES = {'build': 'build.sh', 'run': 'run.sh'}
_CHUNK = 4096
_KILL_AFTER = 2.0          # s entre pedir que pare (TERM) y obligarlo (KILL)
_RUNNING = set()           # scripts en marcha: se paran al cerrar la actividad


def find_scripts(path):
    """{'build': ruta, 'run': ruta} de los scripts que hay junto a ``path``."""
    folder = os.path.dirname(os.path.abspath(path))
    found = {}
    for kind, name in SCRIPT_NAMES.items():
        script = os.path.join(folder, name)
        if os.path.isfile(script):
            found[kind] = script
    return found


def login_command(script):
    return ['/bin/bash', '-l', '-c', 'exec sh "$1"', 'archivos', script]


def plain_command(script):
    return ['/bin/sh', script]


class ScriptProcess(object):
    """Un script en marcha. ``on_output(texto)`` y ``on_done(código, error)``
    se llaman **desde un hilo**: quien las pase debe pasarlas al hilo de la
    interfaz (``GLib.idle_add``). ``código`` es negativo si lo mató una señal."""

    def __init__(self, script, on_output, on_done, command=login_command):
        self.script = script
        self._on_output = on_output
        self._on_done = on_done
        self._command = command
        self._process = None
        self._stopped = False

    @property
    def running(self):
        return self._process is not None and self._process.poll() is None

    def start(self):
        try:
            with open(os.devnull, 'rb') as nothing:
                self._process = subprocess.Popen(
                    self._command(self.script),
                    cwd=os.path.dirname(self.script), stdin=nothing,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    preexec_fn=os.setsid, close_fds=True)
        except (OSError, ValueError) as exc:
            self._on_done(None, getattr(exc, 'strerror', None) or str(exc))
            return
        _RUNNING.add(self)
        thread = threading.Thread(target=self._pump)
        thread.daemon = True
        thread.start()

    def _pump(self):
        decoder = codecs.getincrementaldecoder('utf-8')('replace')
        stream = self._process.stdout
        try:
            while True:
                data = os.read(stream.fileno(), _CHUNK)
                if not data:
                    break
                text = decoder.decode(data)
                if text:
                    self._on_output(text)
            tail = decoder.decode(b'', True)
            if tail:
                self._on_output(tail)
        except (OSError, ValueError):
            pass
        finally:
            code = self._process.wait()
            _RUNNING.discard(self)
            try:
                stream.close()
            except (OSError, IOError):
                pass
            self._on_done(code, None)

    def stop(self):
        """Pide que pare (TERM) a todo el grupo y, si no, lo obliga (KILL)."""
        process = self._process
        if process is None or process.poll() is not None:
            return
        self._stopped = True
        self._signal(signal.SIGTERM)
        timer = threading.Timer(_KILL_AFTER, self._signal, [signal.SIGKILL])
        timer.daemon = True
        timer.start()

    @property
    def was_stopped(self):
        return self._stopped

    def _signal(self, number):
        process = self._process
        if process is None:
            return
        try:
            os.killpg(os.getpgid(process.pid), number)
        except (OSError, ValueError):
            pass            # ya terminó


def stop_all(wait=1.0):
    """Para todos los scripts en marcha (TERM y, pasado ``wait`` s, KILL).

    Se ejecuta solo al salir el intérprete (atexit): al cerrar la actividad no
    debe quedar ningún programa suyo funcionando. Una pestaña que se cierra
    ya para el suyo con ``stop()``.
    """
    running = [p for p in list(_RUNNING) if p.running]
    for process in running:
        process._signal(signal.SIGTERM)
    deadline = time.time() + wait
    while time.time() < deadline and any(p.running for p in running):
        time.sleep(0.05)
    for process in running:
        if process.running:
            process._signal(signal.SIGKILL)


atexit.register(stop_all)


def trim_output(text, limit=300000):
    """Recorta el principio de un texto demasiado largo (por línea completa)."""
    if len(text) <= limit:
        return text
    cut = text.find(u'\n', len(text) - limit)
    return text[cut + 1:] if cut >= 0 else text[-limit:]
