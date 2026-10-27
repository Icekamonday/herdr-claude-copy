"""Which agent a key typed for, and whether its box can take a line.

A key fires from wherever you stand, and that is as often a shell of the tab
as the agent itself, so the agent is found from the tab. A line typed there
goes where you type, so it goes only into a box that can take it: an agent at
work would queue it behind the turn, a blocked one would take it as the answer
to its dialog, and a box already holding a draft would take it as its tail.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api

MARK = '❯'          # the mark Claude opens its prompt box with


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
    here = next((pane for pane in panes if pane['pane_id'] == standing), None) \
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
    """
    boxes = [row.strip() for row in screen.splitlines()
             if row.strip().startswith(MARK)]
    return boxes[-1][len(MARK):].strip() if boxes else None


def screen(pane):
    read = api.call('pane', 'read', pane_id=pane['pane_id'],
                    source='visible').get('read') or {}
    return read.get('text') or ''
