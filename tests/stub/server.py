"""A stand-in for the Herdr server, so the picker can be driven on a socket.

The picker asks the socket and nothing else. This answers the reads from
tests/fixtures/world.json and accepts every write: the picker is checked for
what it asks and what it prints, not for its effect on a server.
"""

import json
import os
import socket
import threading

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(HERE, 'fixtures', 'world.json')) as _fp:
    WORLD = json.load(_fp)

# Claude sets the terminal title of its pane to the name of its session; a
# test that gives a pane a title clears it when it is done
TITLES = {}


def titled(panes):
    return [dict(pane, terminal_title_stripped=TITLES[pane['pane_id']])
            if pane['pane_id'] in TITLES else pane for pane in panes]


READS = {
    'pane.list': lambda p: {'panes': titled(WORLD['panes']), 'type': 'pane_list'},
    'pane.read': lambda p: {'read': {'pane_id': p.get('pane_id'),
                                     'text': WORLD['screens'].get(p.get('pane_id'), '')},
                            'type': 'pane_read'},
}


def answer(request):
    method = request.get('method', '')
    params = request.get('params') or {}
    # what the picker asked for is part of what it does, and the values matter
    # as much as the method: the text it pastes, and the pane it pastes into
    log = os.environ.get('HERDR_STUB_LOG')
    if log:
        said = ' '.join(str(v) for v in params.values() if not isinstance(v, bool))
        with open(log, 'a') as fp:
            fp.write(f'{method} {said}'.rstrip() + '\n')
    make = READS.get(method)
    return {'id': request.get('id'), 'result': make(params) if make else {}}


def serve(path, stop):
    """One request per connection, which is how the real server is spoken to."""
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(path)
    listener.listen(16)
    listener.settimeout(0.2)
    while not stop.is_set():
        try:
            client, _ = listener.accept()
        except OSError:
            continue
        with client:
            client.settimeout(2)
            try:
                line = client.makefile('rb').readline()
                client.sendall(
                    (json.dumps(answer(json.loads(line))) + '\n').encode())
            except (OSError, ValueError):
                pass
    listener.close()


def start(path):
    """Serve on that path until the returned stop is set."""
    stop = threading.Event()
    thread = threading.Thread(target=serve, args=(path, stop), daemon=True)
    thread.start()
    return stop
