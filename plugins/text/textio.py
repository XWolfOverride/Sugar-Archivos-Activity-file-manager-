# -*- coding: utf-8 -*-
"""Lectura y escritura de texto del editor (sin GTK, se prueba sin pantalla).

- Detecta UTF-8 (con o sin BOM) y, si no lo es, usa Latin-1 (nunca pierde datos).
- Recuerda los finales de línea (LF, CRLF o CR) para guardar igual que estaban.
- El texto va siempre como ``unicode`` con ``\\n`` internamente.
- Guarda de forma atómica: escribe un temporal y lo renombra, así un corte a
  mitad no deja el archivo roto.
"""
import codecs
import os

MAX_SIZE = 10 * 1024 * 1024        # más grande que esto no se abre
BIG_SIZE = 2 * 1024 * 1024         # a partir de aquí se avisa de que será lento
EOL = {'LF': u'\n', 'CRLF': u'\r\n', 'CR': u'\r'}


class TextError(Exception):
    """Fallo al abrir o guardar; el mensaje no está traducido (lo hace el plugin)."""

    def __init__(self, code, detail=''):
        Exception.__init__(self, code)
        self.code = code            # 'too-big', 'binary', 'read', 'write'
        self.detail = detail


class Document(object):
    """Lo que hay que recordar de un archivo para devolverlo como estaba."""

    def __init__(self):
        self.text = u''
        self.encoding = 'utf-8'
        self.eol = 'LF'
        self.bom = False
        self.mtime = 0
        self.size = 0


def looks_binary(data):
    return b'\0' in data[:8192]


def decode(data):
    """(texto, codificación, finales de línea, ¿tenía BOM?) de unos bytes."""
    bom = data.startswith(codecs.BOM_UTF8)
    if bom:
        data = data[len(codecs.BOM_UTF8):]
    try:
        text, encoding = data.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        text, encoding = data.decode('latin-1'), 'latin-1'
        bom = False
    crlf = text.count(u'\r\n')
    lone_lf = text.count(u'\n') - crlf
    lone_cr = text.count(u'\r') - crlf
    if crlf and crlf >= lone_lf and crlf >= lone_cr:
        eol = 'CRLF'
    elif lone_cr > lone_lf and lone_cr > crlf:
        eol = 'CR'
    else:
        eol = 'LF'
    if u'\r' in text:
        text = text.replace(u'\r\n', u'\n').replace(u'\r', u'\n')
    return text, encoding, eol, bom


def read_document(path):
    """Lee ``path`` como texto. Falla con TextError si es enorme o binario."""
    try:
        stat = os.stat(path)
        if stat.st_size > MAX_SIZE:
            raise TextError('too-big', str(stat.st_size))
        with open(path, 'rb') as handle:
            data = handle.read()
    except (IOError, OSError) as exc:
        raise TextError('read', exc.strerror or str(exc))
    if looks_binary(data):
        raise TextError('binary')
    doc = Document()
    doc.text, doc.encoding, doc.eol, doc.bom = decode(data)
    doc.mtime, doc.size = stat.st_mtime, stat.st_size
    return doc


def encode(text, doc):
    """(bytes, codificación usada) para guardar ``text`` como estaba el original."""
    if doc.eol != 'LF':
        text = text.replace(u'\n', EOL[doc.eol])
    used = doc.encoding
    try:
        data = text.encode(used)
    except UnicodeEncodeError:
        used = 'utf-8'                  # se escribió algo que Latin-1 no tiene
        data = text.encode(used)
    if used == 'utf-8' and doc.bom:
        data = codecs.BOM_UTF8 + data
    return data, used


def write_atomic(path, data):
    """Escribe ``data`` en ``path`` sin dejarlo nunca a medias."""
    target = os.path.realpath(path)              # un enlace: se guarda en su destino
    folder, name = os.path.split(target)
    temp = os.path.join(folder, '.%s.%d.tmp' % (name, os.getpid()))
    try:
        mode = os.stat(target).st_mode & 0o7777
    except OSError:
        mode = 0o644
    try:
        with open(temp, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.rename(temp, target)
    except (IOError, OSError) as exc:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise TextError('write', exc.strerror or str(exc))
    return target


def save_document(path, text, doc):
    """Guarda y actualiza ``doc``. Devuelve la codificación realmente usada."""
    data, used = encode(text, doc)
    target = write_atomic(path, data)
    stat = os.stat(target)
    doc.mtime, doc.size = stat.st_mtime, stat.st_size
    doc.encoding = used
    return used


def changed_on_disk(path, doc):
    """¿Cambió el archivo (o desapareció) desde que se leyó o guardó?"""
    try:
        stat = os.stat(path)
    except OSError:
        return True
    return stat.st_mtime != doc.mtime or stat.st_size != doc.size
