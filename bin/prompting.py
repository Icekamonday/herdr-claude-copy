"""Which agent a key typed for, and whether its box can take a line.

A key fires from wherever you stand, and that is as often a shell of the tab
as the agent itself, so the agent is found from the tab. A line typed there
goes where you type, so it goes only into a box that can take it: an agent at
work would queue it behind the turn, a blocked one would take it as the answer
to its dialog, a box already holding a draft would take it as its tail, and a
box in shell mode would run it as a command.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api

MARK = '❯'          # the mark Claude opens its prompt box with
# the mark of the box in shell mode, where a line runs as a command. A
# no-break space follows it, and a plain space follows the ! of the footer
# that names the mode
SHELL = '!'
SHELL_OPENS = SHELL + '\xa0'
# a styled read carries CSI sequences, whose SGR holds the style, and OSC ones
ESCAPE = re.compile(r'\x1b\[([0-?]*)[ -/]*([@-~])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)')
# the SGR codes of a background in the eight colors and the eight bright ones;
# 48 names its color in the values after it
BACKGROUNDS = {str(code) for code in (*range(40, 48), *range(100, 108))}


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
    """The mark that the prompt box on that screen opens on, and what the box
    holds, or None when it is not there. The mark tells the mode: SHELL in
    shell mode, else MARK, even for a line that opens on a !.

    Claude opens its box and every message you have sent with the same mark,
    and draws a sent message on a background. So the box is the lowest mark
    on no background, and a screen with none is scrolled away from the box.

    A styled screen tells a suggestion from a typed line. Claude Code draws
    its suggestion for the next prompt dim, and typing dismisses it, so the
    box holds only the characters that are not dim.
    """
    for row in reversed(screen.splitlines()):
        plain = ESCAPE.sub('', row).lstrip()
        mark = MARK if plain.startswith(MARK) else SHELL if plain.startswith(SHELL_OPENS) \
            else None
        if mark and not on_background(row):
            return mark, typed(row).strip().removeprefix(mark).strip()
    return None


def pieces(row):
    """The text of that row between its escapes, each piece with whether it is
    drawn dim and whether it lies on a background."""
    dim = background = False
    at = 0
    for escape in ESCAPE.finditer(row):
        yield row[at:escape.start()], dim, background
        if escape.group(2) == 'm':
            dim, background = style_after(escape.group(1), dim, background)
        at = escape.end()
    yield row[at:], dim, background


def typed(row):
    """The characters of that row that are not drawn dim, with no escapes."""
    return ''.join(text for text, dim, _ in pieces(row) if not dim)


def on_background(row):
    """Whether the first character of that row that is not a space lies on a
    background."""
    return next((background for text, _, background in pieces(row) if text.strip()), False)


def style_after(params, dim, background):
    """Whether the text after an SGR with those parameters is drawn dim, and
    whether it lies on a background.

    A color names its values after 38, 48 or 58, and the 2 of a true color
    among them is no dim, as a 48 among them is no background.
    """
    codes = iter(params.split(';'))
    for code in codes:
        if code in ('', '0'):
            dim = background = False
        elif code == '22':
            dim = False
        elif code == '2':
            dim = True
        elif code == '49':
            background = False
        elif code in BACKGROUNDS:
            background = True
        elif code in ('38', '48', '58'):
            if code == '48':
                background = True
            for _ in range({'5': 1, '2': 3}.get(next(codes, ''), 0)):
                next(codes, None)
    return dim, background


def box_refusal(pane):
    """Why the prompt box of that pane cannot take a line now, or None."""
    found = box(screen(pane, styled=True))
    if found is None:
        return 'the prompt box is not on screen'
    mark, held = found
    if mark == SHELL:
        return 'the prompt box is in shell mode'
    return 'the prompt box already holds a line' if held else None


def screen(pane, styled=False):
    """The visible screen of that pane, with its SGR escapes when styled."""
    style = {'format': 'ansi', 'strip_ansi': False} if styled else {}
    read = api.call('pane', 'read', pane_id=pane['pane_id'], source='visible',
                    **style).get('read') or {}
    return read.get('text') or ''
