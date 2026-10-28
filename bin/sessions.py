"""Which Claude session a Herdr pane runs, and where its transcript is.

Herdr learns the identity once, when the agent starts, and keeps it through a
resume: the pane then names a session that stopped days ago, and
`report-agent-session` is ignored whatever source or sequence it carries.

What a pane always tells the truth about is its terminal title, which Claude
sets to the name of the session running in it. That is the strongest link,
and the only one that separates two sessions sharing a directory.
"""

import json
import os
import re
import time

# where a status line hook copies the payload of each session, if one does
STATE = os.environ.get('CLAUDE_TMUX_STATE') or os.path.join(
    os.environ.get('XDG_STATE_HOME') or os.path.expanduser('~/.local/state'),
    'claude-tmux')
RENAMED_WITHIN = 86400        # a transcript quiet for longer runs in no pane
NAME_WINDOW = 65536           # Claude Code writes the name again at each turn
FIND_WINDOW = 4 << 20         # but one turn can write megabytes after it
PAYLOAD_MOST = 65536          # a payload holds about 2 KB
UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
PROJECT = re.compile(r'[A-Za-z0-9-]+')    # what project() leaves of a cwd
NAMED = ('custom-title', 'agent-name')    # the records of a name that the user gave
GUESSED = 'ai-title'                      # the record of the name that Claude Code gave


def _names(path, window):
    """The last name that the user gave a session, and the last one that
    Claude Code gave it, from the tail of its transcript."""
    try:
        with open(path, 'rb') as fp:
            fp.seek(0, 2)
            fp.seek(max(0, fp.tell() - window))
            tail = fp.read()
    except (OSError, TypeError):
        return '', ''
    guessed = ''
    for line in reversed(tail.splitlines()):
        if not any(kind.encode() in line for kind in (*NAMED, GUESSED)):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get('type') in NAMED:
            given = (record.get('customTitle') or record.get('agentName') or '').strip()
            if given:
                return given, guessed
        elif record.get('type') == GUESSED and not guessed:
            guessed = (record.get('aiTitle') or '').strip()
    return '', guessed


def _named(stamp, state):
    """The name that a session carries now.

    The payload takes the name of a session when Claude redraws its status
    line, and a /rename does not wait for that: the transcript has the new
    name at once, and again at each turn, near its end. So a transcript
    written after its payload, lately, is asked first.

    For a session that nobody named, the payload already holds the name
    that Claude Code gave it. That name counts only when the payload has
    none, since a name that the user gave always wins.
    """
    name = (state.get('session_name') or '').strip()
    path = state.get('transcript_path')
    try:
        written = os.path.getmtime(path)
    except (OSError, TypeError):
        return name
    if written <= stamp or time.time() - written > RENAMED_WITHIN:
        return name
    given, guessed = _names(path, NAME_WINDOW)
    return given or name or guessed


# what the CLI writes in the title while it has nothing of its own to say
TRANSIENT = ('claude', 'claude · resume', 'claude - resume')


def _title(pane):
    title = (pane.get('terminal_title_stripped') or '').strip()
    return '' if title.lower() in TRANSIENT else title


def resolve_all(panes, published):
    """Give each pane its session, one session to one pane.

    Two keys, the surer first: the title the pane carries, then the identity
    Herdr holds. A session taken by one pane is out of reach of the others.
    The directory answers for no pane, since a session that once ran there
    under another name would answer for it.
    """
    answer, claimed, names = {}, set(), {}

    def name_of(stamp, state):
        if state['session_id'] not in names:
            names[state['session_id']] = _named(stamp, state)
        return names[state['session_id']]

    def take(pane, state):
        answer[pane['pane_id']] = state
        claimed.add(state['session_id'])

    for pane in panes:                        # the title, freshest of its name
        title = _title(pane)
        if not title:
            continue
        for stamp, state in published:
            if state['session_id'] not in claimed \
                    and name_of(stamp, state) == title:
                take(pane, state)
                break

    for pane in panes:                        # what Herdr remembers
        if pane['pane_id'] in answer:
            continue
        sid = (pane.get('agent_session') or {}).get('value')
        for _, state in published:
            if state['session_id'] == sid and sid not in claimed:
                take(pane, state)
                break
    return answer


def project(cwd):
    """The directory of ~/.claude/projects where Claude Code keeps the
    transcripts of a cwd.

    Past 200 characters, Claude Code cuts the name and adds a hash of the
    path, which this name lacks. A caller that finds no transcript under it
    searches every project.
    """
    return re.sub(r'[^a-zA-Z0-9]', '-', cwd)


def sources_file():
    return os.path.join(os.environ.get('XDG_CONFIG_HOME')
                        or os.path.expanduser('~/.config'), 'herdr-claude-copy', 'sources')


def sources():
    """Where the finder looks: pairs of a projects root and a directory of
    payloads, or None for a root without one.

    The host paths come first, and each line of the sources file adds a
    root, then an optional directory, with `#` for a comment. A session in
    a container keeps its files elsewhere, and a host pane of the same
    workspace must still find its own.
    """
    config = os.environ.get('CLAUDE_CONFIG_DIR') or os.path.expanduser('~/.claude')
    found = [(os.path.join(config, 'projects'), STATE)]
    try:
        with open(sources_file()) as fp:
            lines = fp.read().splitlines()
    except (OSError, ValueError):
        return found
    for line in lines:
        words = [os.path.expanduser(word) for word in line.split('#', 1)[0].split()]
        if words:
            found.append((words[0], words[1] if len(words) > 1 else None))
    return found


def _under(root, folder, sid, strays):
    """The transcript of a session in a project directory of a root, or None.

    A container can write the payloads and the projects of its source, so
    each part is checked before it is joined, and the file must stay in
    the root. A link out of it could lead to any file of the user: its path
    goes to strays, for the refusal to name.
    """
    if not (isinstance(folder, str) and PROJECT.fullmatch(folder)
            and isinstance(sid, str) and UUID.fullmatch(sid)):
        return None
    path = os.path.join(root, folder, f'{sid}.jsonl')
    if not os.path.isfile(path):
        return None
    top, real = os.path.realpath(root), os.path.realpath(path)
    if os.path.commonpath([top, real]) != top:
        strays.append((path, root))
        return None
    return real


def _payloads(places, strays):
    """The payloads of every source, newest first, each one pointing at its
    transcript under the root of its source.

    The path that a payload names is never opened: only its last two parts
    are kept, and they must name the session of the payload.
    """
    out = []
    for root, room in places:
        try:
            names = os.listdir(room) if room else []
        except OSError:
            continue
        for name in names:
            path = os.path.join(room, name)
            if not name.endswith('.raw.json') or not os.path.isfile(path):
                continue
            try:
                with open(path, 'rb') as fp:
                    blob = fp.read(PAYLOAD_MOST + 1)
                state = json.loads(blob) if len(blob) <= PAYLOAD_MOST else None
                stamp = os.path.getmtime(path)
            except (OSError, ValueError):
                continue
            if not isinstance(state, dict):
                continue
            sid = state.get('session_id')
            parts = str(state.get('transcript_path') or '').split('/')[-2:]
            if len(parts) < 2 or parts[1] != f'{sid}.jsonl':
                continue
            transcript = _under(root, parts[0], sid, strays)
            if transcript:
                out.append((stamp, dict(state, transcript_path=transcript)))
    out.sort(key=lambda pair: pair[0], reverse=True)
    return out


def _by_identity(root, cwd, sid, strays):
    """The transcript of a session id: in the project of the cwd, else in
    any project, since /cd moves a session to the project of its new cwd."""
    found = _under(root, project(cwd or ''), sid, strays)
    if found:
        return found
    try:
        folders = sorted(os.listdir(root))
    except OSError:
        return None
    return next(filter(None, (_under(root, folder, sid, strays) for folder in folders)),
                None)


def _recent(root, cwd):
    """The transcripts of the project of a cwd, written in the last day, as
    (written, project directory, session id).

    A cwd without a project takes that of its nearest parent, as `devcontainer
    exec` starts Claude at the top of the workspace. Only the dates are read:
    a project can hold hundreds of transcripts.
    """
    here = cwd or ''
    while here and not os.path.isdir(os.path.join(root, project(here))):
        parent = os.path.dirname(here)
        here = parent if parent != here else ''
    if not here:
        return []
    folder, since, found = project(here), time.time() - RENAMED_WITHIN, []
    try:
        entries = list(os.scandir(os.path.join(root, folder)))
    except OSError:
        return []
    for entry in entries:
        if not entry.name.endswith('.jsonl'):
            continue
        try:
            written = entry.stat().st_mtime
        except OSError:
            continue
        if written >= since:
            found.append((written, folder, entry.name[:-len('.jsonl')]))
    return found


def _name(path):
    given, guessed = _names(path, FIND_WINDOW)
    return given or guessed


class NoTranscript(Exception):
    """Why the finder gives up, in words that say what to do."""


def find(pane, panes):
    """The transcript of the session that a pane runs, for a reader that
    must not guess.

    The title decides, then the identity that Herdr holds: through the
    payloads first, then through the transcripts alone, for a user with no
    status line hook. The cwd only narrows the search, so a session that
    once ran there under another name never answers.

    If the title names no session, the identity decides alone: Claude Code
    can leave the title that the shell set.
    """
    places, strays = sources(), []
    taken = resolve_all(panes, _payloads(places, strays))
    if pane['pane_id'] in taken:
        return taken[pane['pane_id']]['transcript_path']
    title = _title(pane)
    sid = (pane.get('agent_session') or {}).get('value')
    if not title and not sid:
        raise NoTranscript('name this session with /rename, then press the key again')
    claimed = {state['session_id'] for state in taken.values()}

    held = None
    if sid and sid not in claimed:
        for root, _ in places:
            path = _by_identity(root, pane.get('cwd'), sid, strays)
            # after a /resume, Herdr still holds the identity of the session before
            if path and (not title or _name(path) == title):
                return path
            held = held or path

    if title:
        recent = [(written, root, folder, stem) for root, _ in places
                  for written, folder, stem in _recent(root, pane.get('cwd'))]
        for _, root, folder, stem in sorted(recent, reverse=True):
            path = _under(root, folder, stem, strays) if stem not in claimed else None
            if path and _name(path) == title:
                return path

    if held:
        return held

    if strays:
        path, root = strays[0]
        raise NoTranscript(f'check {path}: it resolves outside {root}')
    raise NoTranscript(f'add the projects directory of this session to {sources_file()}: '
                       f'no transcript carries its {"name" if title else "id"}')

