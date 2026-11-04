"""Which agent a key typed for, and whether its box can take a line.

A key fires from wherever you stand, and that is as often a shell of the tab
as the agent itself, so the agent is found from the tab. A line typed there
goes where you type, so it goes only into a box that can take it: an agent at
work would queue it behind the turn, a blocked one would take it as the answer
to its dialog, and a box already holding a draft would take it as its tail.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api

MARK = '❯'          # the mark Claude opens its prompt box with
# a styled read carries CSI sequences, whose SGR holds the style, and OSC ones
ESCAPE = re.compile(r'\x1b\[([0-?]*)[ -/]*([@-~])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)')


def standing():
    """The pane that a key was pressed in.

    A popup has no pane of its own, and Herdr names the pane under it in the
    context of the plugin. A shell, or a script run by hand, names its own
    pane in HERDR_PANE_ID.
    """
    try:
        context = json.loads(os.environ.get('HERDR_PLUGIN_CONTEXT_JSON') or '{}')
    except ValueError:
        context = {}
    under = context.get('focused_pane_id') if isinstance(context, dict) else None
    return under or os.environ.get('HERDR_PANE_ID')


def target(panes, standing):
    """The agent of the tab you stand in, or None.

    A tab holds one agent and a few shells. One with two agents names one
    only when you stand in it: from a shell, either could be meant.
    """
    here = api.pane(standing, panes) \
        or next((pane for pane in panes if pane.get('focused')), None)
    if not here:
        return None
    if here.get('agent'):
        return here
    agents = [pane for pane in panes
              if pane.get('tab_id') == here.get('tab_id') and pane.get('agent')]
    return agents[0] if len(agents) == 1 else None


def box(screen):
    """What the prompt box on that screen holds, or None when it is not there.

    Claude opens its box and every message you have sent with the same mark,
    so the box is the lowest of them. A screen carrying none is one scrolled
    away from it.

    A styled screen tells a suggestion from a typed line. Claude Code draws
    its suggestion for the next prompt dim, and typing dismisses it, so the
    box holds only the characters that are not dim.
    """
    rows = [row for row in screen.splitlines()
            if ESCAPE.sub('', row).strip().startswith(MARK)]
    return typed(rows[-1]).strip().removeprefix(MARK).strip() if rows else None


def typed(row):
    """The characters of that row that are not drawn dim, with no escapes."""
    kept, dim, at = [], False, 0
    for escape in ESCAPE.finditer(row):
        if not dim:
            kept.append(row[at:escape.start()])
        if escape.group(2) == 'm':
            dim = dim_after(escape.group(1), dim)
        at = escape.end()
    if not dim:
        kept.append(row[at:])
    return ''.join(kept)


def dim_after(params, dim):
    """Whether the text after an SGR with those parameters is drawn dim.

    A color names its values after 38, 48 or 58, and the 2 of a true color
    among them is no dim.
    """
    codes = iter(params.split(';'))
    for code in codes:
        if code in ('', '0', '22'):
            dim = False
        elif code == '2':
            dim = True
        elif code in ('38', '48', '58'):
            for _ in range({'5': 1, '2': 3}.get(next(codes, ''), 0)):
                next(codes, None)
    return dim


def box_refusal(pane):
    """Why the prompt box of that pane cannot take a line now, or None."""
    held = box(screen(pane, styled=True))
    if held is None:
        return 'the prompt box is not on screen'
    return 'the prompt box already holds a line' if held else None


def screen(pane, styled=False):
    """The visible screen of that pane, with its SGR escapes when styled."""
    style = {'format': 'ansi', 'strip_ansi': False} if styled else {}
    read = api.call('pane', 'read', pane_id=pane['pane_id'], source='visible',
                    **style).get('read') or {}
    return read.get('text') or ''
