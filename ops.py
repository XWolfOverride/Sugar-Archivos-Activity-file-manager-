# -*- coding: utf-8 -*-
"""Cola de operaciones largas (copiar, mover, borrar) en un hilo aparte.

Las funciones de retorno se ejecutan siempre en el hilo principal de GTK
(vía GLib.idle_add), así que pueden tocar la interfaz.
"""
import os
import threading
import time

from gi.repository import Gio, GLib

import archives
import fileops

COPY, MOVE, DELETE = 'copy', 'move', 'delete'
TAR, TARGZ, EXTRACT = 'tar', 'targz', 'extract'


class OpRunner(object):
    """Ejecuta de uno en uno los trabajos que se le envían.

    on_start(kind, count)                         al empezar un trabajo
    on_progress(kind, index, count, fraction, name)
    on_finish(kind, results, errors, cancelled, dst_dir)
    """

    def __init__(self, on_start, on_progress, on_finish):
        self._on_start = on_start
        self._on_progress = on_progress
        self._on_finish = on_finish
        self._queue = []
        self._lock = threading.Lock()
        self._worker = None
        self._cancellable = None

    def busy(self):
        with self._lock:
            return self._worker is not None

    def submit(self, kind, sources, dst_dir=None):
        with self._lock:
            self._queue.append((kind, list(sources), dst_dir))
            if self._worker is None:
                self._worker = threading.Thread(target=self._run)
                self._worker.daemon = True
                self._worker.start()

    def cancel(self):
        cancellable = self._cancellable
        if cancellable is not None:
            cancellable.cancel()

    def _run(self):
        while True:
            with self._lock:
                if not self._queue:
                    self._worker = None
                    return
                job = self._queue.pop(0)
            self._execute(*job)

    def _execute(self, kind, sources, dst_dir):
        cancellable = Gio.Cancellable()
        self._cancellable = cancellable
        # Crear un archivo comprimido es UNA operación con todas las fuentes;
        # las demás se hacen una por una.
        if kind in (TAR, TARGZ):
            units = [list(sources)]
        else:
            units = [[s] for s in sources]
        count = len(units)
        GLib.idle_add(self._on_start, kind, count)
        results, errors, cancelled = [], [], False
        for index, unit in enumerate(units):
            source = unit[0]
            name = os.path.basename(source.rstrip('/')) or source
            if len(unit) > 1:
                name = '%s (+%d)' % (name, len(unit) - 1)
            last = [0.0]

            def progress(done, total, current, index=index, name=name,
                         last=last):
                now = time.time()
                if now - last[0] < 0.15 and done < total:
                    return
                last[0] = now
                fraction = (float(done) / total) if total else 1.0
                GLib.idle_add(self._on_progress, kind, index, count,
                              min(fraction, 1.0), name)

            try:
                if kind == COPY:
                    results.append(fileops.copy(source, dst_dir,
                                                cancellable, progress))
                elif kind == MOVE:
                    results.append(fileops.move(source, dst_dir,
                                                cancellable, progress))
                elif kind in (TAR, TARGZ):
                    results.append(archives.create_archive(
                        unit, dst_dir, kind == TARGZ, cancellable, progress))
                elif kind == EXTRACT:
                    results.append(archives.extract_archive(
                        source, dst_dir, cancellable, progress))
                else:
                    fileops.delete(source, cancellable, progress)
                    results.append(source)
            except fileops.Cancelled:
                cancelled = True
                break
            except fileops.FileOpError as exc:
                errors.append(str(exc))
            except Exception as exc:      # error inesperado: no matar el hilo
                errors.append('%s: %s' % (name, exc))
        self._cancellable = None
        GLib.idle_add(self._on_finish, kind, results, errors, cancelled,
                      dst_dir)
