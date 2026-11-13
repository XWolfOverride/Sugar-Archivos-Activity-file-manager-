# -*- coding: utf-8 -*-
"""Traducciones con gettext, leyendo directamente los ficheros ``.po``.

Los textos del código están en inglés: ``tr('Open')``. Para el plural se usa
``ntr('%d file', '%d files', n) % n``. No hay nada que compilar: se leen los
``po/<idioma>.po`` (los mismos que se traducen en Pootle/Weblate o a mano), con
las reglas de plural de su cabecera ``Plural-Forms``.

Idioma
    ``ARCHIVOS_LANG`` (por ejemplo ``es`` o ``es_ES``) manda sobre el entorno; si
    no, ``LANGUAGE`` (lista separada por ``:``), ``LC_ALL``, ``LC_MESSAGES`` y
    ``LANG``. ``es_ES.utf8`` busca ``po/es_ES.po`` y después ``po/es.po``. Sin
    fichero para ese idioma se ve el inglés del código.

Plugins
    Cada plugin tiene su propia carpeta ``po/`` y su propio traductor:
    ``make_translator(carpeta_po)``; así un plugin de terceros se traduce solo.

Herramientas (extraer textos, actualizar y comprobar): ``tools/translate.py``.
"""
import gettext
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
PO_DIR = os.path.join(_HERE, 'po')
_ENV_KEYS = ('ARCHIVOS_LANG', 'LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG')
_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}
_DEFAULT_PLURAL = 'nplurals=2; plural=(n != 1);'


# --------------------------------------------------------------------------
# Lectura de ficheros .po
# --------------------------------------------------------------------------

def _unquote(line):
    start, end = line.index('"'), line.rindex('"')
    return re.sub(r'\\(.)', lambda m: _ESCAPES.get(m.group(1), m.group(0)),
                  line[start + 1:end])


class PoEntry(object):
    """Una entrada de un .po (también se usa en las herramientas)."""

    def __init__(self):
        self.msgctxt = None
        self.msgid = ''
        self.msgid_plural = None
        self.msgstr = {}            # índice de plural -> texto
        self.flags = []
        self.refs = []
        self.comments = []          # comentarios del traductor ('# ...')
        self.extracted = []         # comentarios del programador ('#. ...')

    @property
    def fuzzy(self):
        return 'fuzzy' in self.flags

    def forms(self):
        """Los msgstr en orden: ['texto'] o ['singular', 'plural', ...]."""
        if not self.msgstr:
            return ['']
        return [self.msgstr.get(i, '') for i in range(max(self.msgstr) + 1)]

    def translated(self):
        return all(self.forms())


def parse_po(data):
    """Lee el contenido (bytes) de un .po y devuelve la lista de PoEntry."""
    entries, entry, field = [], None, None
    pending = {'flags': [], 'refs': [], 'comments': [], 'extracted': []}

    def new_entry():
        item = PoEntry()
        item.flags, item.refs = pending['flags'], pending['refs']
        item.comments, item.extracted = pending['comments'], pending['extracted']
        pending.update(flags=[], refs=[], comments=[], extracted=[])
        return item

    for raw in data.splitlines():
        line = raw.strip()
        if not line:
            if entry is not None:
                entries.append(entry)
                entry, field = None, None
            continue
        if line.startswith('#~'):
            continue                                  # entradas obsoletas
        if line.startswith('#,'):
            pending['flags'] += [f.strip() for f in line[2:].split(',')
                                 if f.strip()]
        elif line.startswith('#:'):
            pending['refs'] += line[2:].split()
        elif line.startswith('#.'):
            pending['extracted'].append(line[2:].strip())
        elif line.startswith('#'):
            pending['comments'].append(line[1:].strip())
        elif line.startswith('msgctxt') or (line.startswith('msgid')
                                            and not line.startswith('msgid_')):
            if entry is not None and entry.msgstr:      # ya vio su msgstr
                entries.append(entry)
                entry = None
            if entry is None:
                entry = new_entry()
            if line.startswith('msgctxt'):
                entry.msgctxt, field = _unquote(line), 'msgctxt'
            else:
                entry.msgid, field = _unquote(line), 'msgid'
        elif line.startswith('msgid_plural'):
            entry.msgid_plural, field = _unquote(line), 'msgid_plural'
        elif line.startswith('msgstr'):
            match = re.match(r'msgstr\[(\d+)\]', line)
            index = int(match.group(1)) if match else 0
            entry.msgstr[index] = _unquote(line)
            field = ('msgstr', index)
        elif line.startswith('"') and entry is not None:
            text = _unquote(line)
            if isinstance(field, tuple):
                entry.msgstr[field[1]] += text
            elif field == 'msgctxt':
                entry.msgctxt += text
            elif field == 'msgid':
                entry.msgid += text
            elif field == 'msgid_plural':
                entry.msgid_plural += text
    if entry is not None:
        entries.append(entry)
    return entries


def read_po(path):
    with open(path, 'rb') as handle:
        return parse_po(handle.read())


# --------------------------------------------------------------------------
# Catálogo y traductor
# --------------------------------------------------------------------------

class Catalog(object):
    """Los textos traducidos de un idioma."""

    def __init__(self, entries):
        header = ''
        self._single, self._plural = {}, {}
        for entry in entries:
            if entry.msgid == '' and entry.msgctxt is None:
                header = entry.msgstr.get(0, '')
        match = re.search(r'plural\s*=\s*([^;]+)', header)
        try:
            self._plural_index = gettext.c2py(match.group(1).strip()
                                              if match else '(n != 1)')
        except (ValueError, SyntaxError):
            self._plural_index = lambda n: int(n != 1)
        for entry in entries:
            if entry.msgid == '' or entry.fuzzy or not any(
                    entry.msgstr.values()):
                continue
            key = entry.msgid if entry.msgctxt is None else (
                entry.msgctxt + '\x04' + entry.msgid)
            if entry.msgid_plural is not None:
                self._plural[key] = entry.forms()
            elif entry.msgstr.get(0):
                self._single[key] = entry.msgstr[0]

    def gettext(self, msgid):
        return self._single.get(msgid, msgid)

    def ngettext(self, singular, plural, number):
        forms = self._plural.get(singular)
        if forms:
            index = min(int(self._plural_index(number)), len(forms) - 1)
            if forms[index]:
                return forms[index]
        return singular if number == 1 else plural


def language_candidates(env=None):
    """Idiomas a probar, del más al menos específico (``es_ES`` y ``es``)."""
    env = os.environ if env is None else env
    forced = env.get('ARCHIVOS_LANG')
    raw = [forced] if forced else (
        env.get('LANGUAGE', '').split(':') +
        [env.get(k) for k in ('LC_ALL', 'LC_MESSAGES', 'LANG')])
    found = []
    for item in raw:
        if not item:
            continue
        item = item.split('.')[0].split('@')[0]
        if item in ('C', 'POSIX'):
            continue
        for candidate in (item, item.split('_')[0]):
            if candidate and candidate not in found:
                found.append(candidate)
    return found


class Translator(object):
    """Traductor de una carpeta ``po/`` (el de la actividad o el de un plugin)."""

    def __init__(self, po_dir, languages=None):
        self.language = None
        self._catalog = None
        for language in (language_candidates() if languages is None
                         else languages):
            path = os.path.join(po_dir, language + '.po')
            if os.path.isfile(path):
                try:
                    self._catalog = Catalog(read_po(path))
                    self.language = language
                    break
                except (IOError, OSError, ValueError, IndexError):
                    continue

    def tr(self, text):
        return text if self._catalog is None else self._catalog.gettext(text)

    def ntr(self, singular, plural, number):
        if self._catalog is None:
            return singular if number == 1 else plural
        return self._catalog.ngettext(singular, plural, number)

    def decimal(self, text):
        """Cambia el punto decimal por el del idioma («12.4 MB» -> «12,4 MB»)."""
        separator = self.tr('DECIMAL_SEPARATOR')
        return text.replace('.', ',') if separator == ',' else text


def make_translator(po_dir, languages=None):
    return Translator(po_dir, languages)


def N_(text):
    """Marca un texto para traducirlo más tarde (lo ve ``tools/translate.py``)."""
    return text


# --------------------------------------------------------------------------
# Traductor de la actividad (se rehace si cambia el idioma del entorno)
# --------------------------------------------------------------------------

_main = {'key': None, 'translator': None}


def translator():
    key = tuple(os.environ.get(k) for k in _ENV_KEYS)
    if _main['key'] != key:
        _main['key'], _main['translator'] = key, Translator(PO_DIR)
    return _main['translator']


def tr(text):
    return translator().tr(text)


def ntr(singular, plural, number):
    return translator().ntr(singular, plural, number)


def decimal(text):
    return translator().decimal(text)
