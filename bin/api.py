"""The one way to ask Herdr anything.

Herdr answers on a unix socket, and the CLI is a client of that same socket.
Going through it spends a process per question, so the picker talks to the
socket.

There is no falling back from one to the other. The socket is Herdr: when it
does not answer, the CLI has nothing to answer from either.
"""

import json
import os
import socket

SOCKET = os.environ.get('HERDR_SOCKET_PATH',
                        os.path.expanduser('~/.config/herdr/herdr.sock'))
TIMEOUT = 5
MAX_REPLY = 1 << 20      # a pane list is a few KB; past this the peer is faulty


def call(*words, **params):
    """One request, by the words the CLI uses: call('pane', 'list').

    The method name is those words joined, which is how the CLI spells them
    too, so a call site reads the same either way.
    """
    method = '.'.join(word.replace('-', '_') for word in words)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(TIMEOUT)
            sock.connect(SOCKET)
            sock.sendall((json.dumps({'id': method, 'method': method,
                                      'params': params}) + '\n').encode())
            # one deadline for the whole reply, and a cap on it: a peer that
            # dribbles bytes without ever sending a newline would otherwise
            # hold the caller open and grow the buffer without bound
            reply = b''
            while not reply.endswith(b'\n') and len(reply) <= MAX_REPLY:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                reply += chunk
    except OSError:
        return {}
    try:
        answer = json.loads(reply.decode())
    except (ValueError, UnicodeDecodeError):
        return {}
    return answer.get('result') or {} if isinstance(answer, dict) else {}


def panes(**params):
    return call('pane', 'list', **params).get('panes', [])
