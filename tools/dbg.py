#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""Cliente del servidor de depuración de Archivos (ver debugsrv.py).

    python tools/dbg.py ping
    python tools/dbg.py eval "app.current_view().path"
    python tools/dbg.py eval "view.open_name('Documents')"
    python tools/dbg.py shot [carpeta]
    python tools/dbg.py tree
"""
import json
import os
import socket
import sys

SOCK = os.environ.get('ARCHIVOS_DEBUG_SOCK', '/tmp/archivos-debug.sock')


def call(request):
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(float(os.environ.get('ARCHIVOS_DEBUG_TIMEOUT', '20')))
    conn.connect(SOCK)
    conn.sendall(json.dumps(request).encode('utf-8') + b'\n')
    data = b''
    while not data.endswith(b'\n'):
        chunk = conn.recv(65536)
        if not chunk:
            break
        data += chunk
    conn.close()
    return json.loads(data.decode('utf-8'))


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    request = {'cmd': cmd}
    if cmd == 'eval':
        request['code'] = ' '.join(argv[2:])
    elif cmd == 'shot' and len(argv) > 2:
        request['dir'] = argv[2]
    reply = call(request)
    if not reply.get('ok'):
        sys.stderr.write(reply.get('error', 'error') + '\n')
        return 1
    if reply.get('stdout'):
        sys.stdout.write(reply['stdout'])
    result = reply.get('result')
    if cmd == 'shot':
        for shot in result:
            print('%s  %s %r %sx%s' % (shot['path'], shot['type'],
                                       shot['title'], shot['size'][0],
                                       shot['size'][1]))
    elif result is not None:
        print(result)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
