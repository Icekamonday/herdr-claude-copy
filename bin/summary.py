"""The summary of a run that is over, and its terminal output as plain text.

    <run>/summary       one line per step with its status, then the last lines
                        of its output
    <run>/<n>/tty.txt   tty.log of step n without the header and the footer
                        of script, the escape sequences and the control
                        characters

The waiter writes both before the wake, so that the agent reads one small file
in the common case. The summary keeps the last lines of a step whatever tool
wrote them: it knows no pattern of a tool.
"""

import collections
import os
import re

NAME = 'summary'
# the bytes of the summary; the last lines of the steps share what the status
# lines leave
SIZE = 2048
INDENT = b'  '
TRUNCATED = b' [...]'
SHORTEST = 20               # the shortest start of a line worth showing alone
FILES = 5                   # how many other files of a step the summary names
# a control string, such as an OSC, up to its BEL or its ST
STRING = re.compile(rb'\x1b[P\]X^_][^\x07\x1b]*(?:\x07|\x1b\\)')
# a CSI sequence, then any other escape sequence, such as a keypad mode or a
# character set
SEQUENCE = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]|\x1b[ -/]*[0-~]')
# a character, of one byte or of several in UTF-8, and the backspace after it
ERASED = re.compile(rb'(?:[\xc0-\xff][\x80-\xbf]+|[^\x08])\x08')
CONTROL = re.compile(rb'[\x00-\x08\x0a-\x1f\x7f]')
UNSEEN = re.compile(r'[\x00-\x1f\x7f]')


def plain(line):
    """A line that a terminal received, as plain text.

    A carriage return inside a line keeps the last text written after it, as
    a progress bar shows its last state.
    """
    line = SEQUENCE.sub(b'', STRING.sub(b'', line.rstrip(b'\n')))
    shown = [part for part in line.split(b'\r') if part.strip()]
    line = shown[-1] if shown else b''
    erased = b'\x08' in line
    while erased:
        line, erased = ERASED.subn(b'', line)
    return CONTROL.sub(b'', line).rstrip()


def framing(line):
    """Whether a line of a tty.log is the header or the footer of script.

    script writes both in the language of the user, so their words cannot
    tell them. It writes them itself and ends them on a bracket, while a step
    writes through the terminal, which ends each line on a carriage return.
    """
    return line.endswith(b']\n') and b'\r' not in line


def lines(fp):
    """The lines of a tty.log, without the header and the footer of script.

    A shell that closed during the step leaves no footer, and may leave no
    header either.
    """
    held = collections.deque()
    for n, line in enumerate(fp):
        if n == 0 and framing(line):
            continue
        held.append(line)
        if len(held) > 2:
            yield held.popleft()
    if held and framing(held[-1]):
        held.pop()
        # script writes a newline of its own before its footer
        if held and held[-1] == b'\n':
            held.pop()
    yield from held


def weight(line):
    """The bytes that a line of output takes in the summary."""
    return len(INDENT) + len(line) + 1 if line else 1


class Output:
    """The terminal output of a step, as tty.txt holds it."""

    def __init__(self, name):
        self.name = name        # the file to read: tty.txt, or tty.log if tty.txt was there
        self.lines = 0
        self.size = 0
        self.tail = collections.deque()     # the last lines, up to SIZE bytes in the summary
        self.cost = 0
        self.blank = 0

    def add(self, line):
        self.lines += 1
        self.size += len(line) + 1
        if not line:
            # a blank line enters the tail only once a line follows it, so
            # that a step that ends on blank lines still shows its text
            self.blank += 1
            return
        blanks = min(self.blank, SIZE)
        self.tail.extend([b''] * blanks + [line])
        self.cost += blanks + weight(line)
        self.blank = 0
        while self.cost > SIZE and len(self.tail) > 1:
            self.cost -= weight(self.tail.popleft())


def output(step):
    """Copy the tty.log of a step to tty.txt as plain text, and return the
    Output, or None if the step left no tty.log."""
    try:
        source = os.open(os.path.join(step, 'tty.log'), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with open(source, 'rb') as fp:
        # a file that is already there may be a link that an agent planted
        try:
            copy = os.open(os.path.join(step, 'tty.txt'),
                           os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            found = Output('tty.txt')
        except FileExistsError:
            copy = os.open(os.devnull, os.O_WRONLY)
            found = Output('tty.log')
        with open(copy, 'wb') as target:
            for line in lines(fp):
                line = plain(line)
                target.write(line + b'\n')
                found.add(line)
    return found


def size(n):
    """A number of bytes, in the unit that keeps it short: bytes, kB or MB."""
    if n < 1000:
        return f'{n} byte{"" if n == 1 else "s"}'
    if n < 999_500:
        return f'{n / 1000:.0f} kB'
    return f'{n / 1e6:.1f} MB'


def others(step):
    """The other files of a step, such as the log of its tool, with their size."""
    try:
        with os.scandir(step) as entries:
            files = sorted((UNSEEN.sub('?', entry.name),
                            entry.stat(follow_symlinks=False).st_size)
                           for entry in entries if entry.is_file(follow_symlinks=False)
                           and entry.name not in ('tty.log', 'tty.txt'))
    except OSError:
        return ''
    named = ', '.join(f'{name} ({size(n)})' for name, n in files[:FILES])
    return named + (f' and {len(files) - FILES} more' if len(files) > FILES else '')


def shares(needs, budget):
    """Share budget between needs in equal parts. A need that takes less
    than its part leaves the rest to the others. Returns the parts, and what
    is left of budget."""
    parts = {}
    waiting = sorted(needs.items(), key=lambda item: item[1])
    while waiting:
        key, need = waiting.pop(0)
        parts[key] = min(need, budget // (len(waiting) + 1))
        budget -= parts[key]
    return parts, budget


def last(tail, budget):
    """The last lines of a tail that fit in budget bytes of the summary.

    If even the last line does not fit, its start does, truncated between two
    characters.
    """
    shown, cost = [], 0
    for line in reversed(tail):
        if cost + weight(line) > budget:
            break
        shown.append(line)
        cost += weight(line)
    room = budget - len(INDENT) - len(TRUNCATED) - 1
    if not shown and tail and room >= SHORTEST:
        line = tail[-1]
        while room and line[room] & 0xc0 == 0x80:
            room -= 1
        shown.append(line[:room] + TRUNCATED)
    shown.reverse()
    while shown and not shown[0]:
        shown.pop(0)
    return shown


def said(k):
    """The end of the status line of a step that shows k lines."""
    return '' if not k else '. The last line:' if k == 1 else f'. The last {k}:'


def status(n, rc, closed, found, step):
    """The status line of a step, without its end."""
    if rc is not None:
        line = f'step {n} rc={rc}'
    elif closed:
        line = f'step {n}, the shell closed during this step'
    else:
        return f'step {n}, not run'
    if found is None or not found.tail:
        line += ', no output'
    elif found.name == 'tty.txt':
        line += (f', {found.lines} line{"" if found.lines == 1 else "s"} in {n}/tty.txt '
                 f'({size(found.size)})')
    else:
        line += f', {n}/tty.txt was already there: read {n}/tty.log'
    files = others(step)
    return line + (f'; {n}/ also holds {files}' if files else '')


def write(run, job, cut):
    """Write the tty.txt of each step and the summary of a run that is over.

    The status line of every step shows. The last lines of the steps share
    what is left of SIZE bytes: the steps that failed, or whose shell closed,
    take their part first, and the steps that passed share the rest. Returns
    False when a file was already at the path of the summary.
    """
    ends = dict(job['ends'])
    steps, budget = [], SIZE
    for n in range(1, job['steps'] + 1):
        rc = ends.get(str(n))
        closed = n == cut
        step = os.path.join(run, str(n))
        found = output(step) if rc is not None or closed else None
        tail = found.tail if found else ()
        line = status(n, rc, closed, found, step).encode('utf-8', 'surrogateescape')
        # the end of the line grows with the lines shown, which the parts decide
        budget -= len(line) + (max(len(said(1)), len(said(len(tail)))) if tail else 0) + 1
        steps.append((line, tail, rc not in ('0', None) or closed))

    def needs(failed):
        return {i: sum(map(weight, tail)) for i, (_, tail, bad) in enumerate(steps)
                if tail and bad == failed}

    first, budget = shares(needs(True), max(budget, 0))
    parts = {**first, **shares(needs(False), budget)[0]}
    text = []
    for i, (line, tail, _) in enumerate(steps):
        shown = last(tail, parts.get(i, 0))
        text.append(line + said(len(shown)).encode())
        text.extend(INDENT + row if row else b'' for row in shown)
    try:
        fd = os.open(os.path.join(run, NAME), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with open(fd, 'wb') as fp:
        fp.write(b'\n'.join(text) + b'\n')
    return True
