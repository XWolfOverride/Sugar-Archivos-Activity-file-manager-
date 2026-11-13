#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""Herramientas de traducción de Archivos (no necesitan gettext instalado).

    python tools/translate.py extract          genera/actualiza los .pot
    python tools/translate.py update           pasa los textos nuevos a los .po
    python tools/translate.py update --new ca  crea po/ca.po (y el de cada plugin)
    python tools/translate.py check            comprueba los .po (código de salida 1
                                          si hay algo sin traducir o roto)

Un «dominio» es la actividad (``po/Archivos.pot``) o un plugin
(``plugins/<id>/po/<id>.pot``). Se extraen las llamadas ``tr('..')``,
``ntr('..', '..', n)`` y los textos marcados con ``N_('..')``, con la ruta y la
línea de cada uno.
"""
from __future__ import print_function

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import i18n  # noqa: E402

_SKIP_DIRS = ('tests', 'tools', 'plugins', 'po', '.git', '__pycache__')
_FORMAT = re.compile(r'%(?:\([^)]+\))?[#0\- +]*\d*(?:\.\d+)?[sdifrx%]')


def _bytes(value):
    return value.encode('utf-8') if not isinstance(value, bytes) else value


def domains():
    """[(nombre, carpeta de fuentes, ¿es el principal?, carpeta po)]."""
    found = [('Archivos', ROOT, True, os.path.join(ROOT, 'po'))]
    plugins = os.path.join(ROOT, 'plugins')
    if os.path.isdir(plugins):
        for name in sorted(os.listdir(plugins)):
            folder = os.path.join(plugins, name)
            if os.path.isfile(os.path.join(folder, 'plugin.py')):
                found.append((name, folder, False, os.path.join(folder, 'po')))
    return found


def source_files(folder, main):
    for current, dirs, files in os.walk(folder):
        if main:
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        else:
            dirs[:] = [d for d in dirs if d not in ('po', 'tests',
                                                     '__pycache__')]
        for name in sorted(files):
            if name.endswith('.py'):
                yield os.path.join(current, name)


def extract_file(path):
    """[(msgid, msgid_plural o None, línea)] de un fichero fuente."""
    with open(path, 'rb') as handle:
        tree = ast.parse(handle.read(), path)
    found = []

    def text(node):
        if isinstance(node, ast.Str):
            return _bytes(node.s)
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (func.id if isinstance(func, ast.Name) else
                func.attr if isinstance(func, ast.Attribute) else None)
        if name in ('tr', 'N_') and node.args:
            msgid = text(node.args[0])
            if msgid:
                found.append((msgid, None, node.lineno))
        elif name == 'ntr' and len(node.args) >= 2:
            singular, plural = text(node.args[0]), text(node.args[1])
            if singular and plural:
                found.append((singular, plural, node.lineno))
    return found


def extract_domain(folder, main):
    """OrderedDict-like: lista de (msgid, plural, [refs]) sin repetidos."""
    order, table = [], {}
    for path in source_files(folder, main):
        ref_base = os.path.relpath(path, ROOT).replace(os.sep, '/')
        for msgid, plural, line in extract_file(path):
            key = (msgid, plural)
            if key not in table:
                table[key] = []
                order.append(key)
            table[key].append('%s:%d' % (ref_base, line))
    return [(k[0], k[1], table[k]) for k in order]


# --------------------------------------------------------------------------
# Escritura de .po / .pot
# --------------------------------------------------------------------------

def _quote(text):
    text = (text.replace('\\', '\\\\').replace('"', '\\"')
            .replace('\n', '\\n').replace('\t', '\\t').replace('\r', '\\r'))
    return '"%s"' % text


def format_entry(entry):
    lines = []
    lines += ['# ' + c for c in entry.comments]
    lines += ['#. ' + c for c in entry.extracted]
    if entry.refs:
        lines.append('#: ' + ' '.join(entry.refs))
    if entry.flags:
        lines.append('#, ' + ', '.join(entry.flags))
    if entry.msgctxt is not None:
        lines.append('msgctxt ' + _quote(entry.msgctxt))
    lines.append('msgid ' + _quote(entry.msgid))
    if entry.msgid_plural is not None:
        lines.append('msgid_plural ' + _quote(entry.msgid_plural))
        for index in sorted(entry.msgstr) or [0, 1]:
            lines.append('msgstr[%d] %s' % (index,
                                             _quote(entry.msgstr.get(index, ''))))
    else:
        lines.append('msgstr ' + _quote(entry.msgstr.get(0, '')))
    return '\n'.join(lines)


def header_entry(name, language=None, plural='nplurals=2; plural=(n != 1);'):
    header = i18n.PoEntry()
    header.flags = ['fuzzy'] if language is None else []
    text = ['Project-Id-Version: %s\\n' % name]
    if language:
        text.append('Language: %s\\n' % language)
    text += ['MIME-Version: 1.0\\n',
             'Content-Type: text/plain; charset=UTF-8\\n',
             'Content-Transfer-Encoding: 8bit\\n']
    if language:
        text.append('Plural-Forms: %s\\n' % plural)
    header.msgstr = {0: ''.join(text).replace('\\n', '\n')}
    return header


def write_po(path, entries):
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    body = '\n\n'.join(format_entry(e) for e in entries) + '\n'
    with open(path, 'wb') as handle:
        handle.write(body)


def pot_entries(name, messages):
    entries = [header_entry(name)]
    for msgid, plural, refs in messages:
        entry = i18n.PoEntry()
        entry.msgid, entry.msgid_plural, entry.refs = msgid, plural, refs
        if '%' in msgid or (plural and '%' in plural):
            entry.flags = ['python-format']
        entry.msgstr = {0: '', 1: ''} if plural else {0: ''}
        entries.append(entry)
    return entries


def merge(name, language, pot, old):
    """Entradas nuevas: textos del .pot con las traducciones que ya había."""
    previous = {}
    header = None
    for entry in old:
        if entry.msgid == '' and entry.msgctxt is None:
            header = entry
        else:
            previous[(entry.msgid, entry.msgid_plural)] = entry
    merged = [header if header is not None else header_entry(name, language)]
    plural_count = 2
    if header is not None:
        match = re.search(r'nplurals\s*=\s*(\d+)', header.msgstr.get(0, ''))
        plural_count = int(match.group(1)) if match else 2
    for entry in pot[1:]:
        base = previous.get((entry.msgid, entry.msgid_plural))
        item = i18n.PoEntry()
        item.msgid, item.msgid_plural = entry.msgid, entry.msgid_plural
        item.refs, item.flags = entry.refs, list(entry.flags)
        if base is not None:
            item.msgstr = dict(base.msgstr)
            item.comments = base.comments
            if base.fuzzy:
                item.flags.append('fuzzy')
        else:
            count = plural_count if entry.msgid_plural else 1
            item.msgstr = dict((i, '') for i in range(count))
        merged.append(item)
    return merged


# --------------------------------------------------------------------------
# Órdenes
# --------------------------------------------------------------------------

def cmd_extract():
    for name, folder, main, po_dir in domains():
        messages = extract_domain(folder, main)
        write_po(os.path.join(po_dir, name + '.pot'),
                 pot_entries(name, messages))
        print('%-10s %3d textos -> %s' % (
            name, len(messages),
            os.path.relpath(os.path.join(po_dir, name + '.pot'), ROOT)))


def po_languages(po_dir):
    if not os.path.isdir(po_dir):
        return []
    return sorted(n[:-3] for n in os.listdir(po_dir) if n.endswith('.po'))


def cmd_update(new_language=None):
    cmd_extract()
    for name, folder, main, po_dir in domains():
        pot = i18n.read_po(os.path.join(po_dir, name + '.pot'))
        languages = po_languages(po_dir)
        if new_language and new_language not in languages:
            languages.append(new_language)
        for language in languages:
            path = os.path.join(po_dir, language + '.po')
            old = i18n.read_po(path) if os.path.isfile(path) else []
            entries = merge(name, language, pot, old)
            write_po(path, entries)
            todo = sum(1 for e in entries[1:] if not e.translated()
                       or e.fuzzy)
            print('%-10s %-6s %3d textos, %d por traducir' % (
                name, language, len(entries) - 1, todo))


def _specs(text):
    return sorted(s for s in _FORMAT.findall(text) if s != '%%')


def check_domain(name, folder, main, po_dir):
    """Lista de problemas (texto) de los .po de un dominio."""
    problems = []
    messages = extract_domain(folder, main)
    wanted = {}
    for msgid, plural, _refs in messages:
        wanted[(msgid, plural)] = True
    for language in po_languages(po_dir):
        path = os.path.join(po_dir, language + '.po')
        entries = i18n.read_po(path)
        have = {}
        for entry in entries:
            if entry.msgid == '' and entry.msgctxt is None:
                continue
            have[(entry.msgid, entry.msgid_plural)] = entry
            for index, form in enumerate(entry.forms()):
                source = entry.msgid if index == 0 else (
                    entry.msgid_plural or entry.msgid)
                if form and _specs(form) != _specs(source):
                    problems.append('%s/%s: marcas de formato distintas en %r'
                                    % (name, language, entry.msgid))
            if entry.fuzzy:
                problems.append('%s/%s: dudoso (fuzzy): %r'
                                % (name, language, entry.msgid))
            elif not entry.translated():
                problems.append('%s/%s: sin traducir: %r'
                                % (name, language, entry.msgid))
        for key in wanted:
            if key not in have:
                problems.append('%s/%s: falta el texto %r (ejecuta '
                                '`tools/translate.py update`)'
                                % (name, language, key[0]))
        for key in have:
            if key not in wanted:
                problems.append('%s/%s: sobra %r (ya no está en el código)'
                                % (name, language, key[0]))
    return problems


def cmd_check():
    problems = []
    for name, folder, main, po_dir in domains():
        problems += check_domain(name, folder, main, po_dir)
    for problem in problems:
        print(problem)
    print('%d problemas' % len(problems))
    return 1 if problems else 0


def main(argv):
    command = argv[1] if len(argv) > 1 else ''
    if command == 'extract':
        cmd_extract()
    elif command == 'update':
        new = argv[argv.index('--new') + 1] if '--new' in argv else None
        cmd_update(new)
    elif command == 'check':
        return cmd_check()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
