"""Type blocks of code into a free shell of the tab, as a run of steps.

The picker types the run into a shell of the tab and sends no Enter, as it
does for a command in the prompt box of Claude. The user reads the blocks
where they will run, on the host and with the rights of the user, and
starts the run with Enter. Each block runs under script, which keeps its
terminal output in a directory of its own, and a job file records when each
step starts and ends. Before the first step, the run starts waking.py, which
reads the job file and tells the agent how the run ended:

    agent <pane id of the agent>
    shell <pane id of the shell>
    step <step>                 one per step, all before the first START
    === START <step>
    === END <step> rc=<status>
    === DONE                    after every step, or after a Ctrl+C (status 130)

A run whose shell closes gets no DONE.

A run writes only under a directory that the picker makes. An agent that
could write there could plant a link at the path of a log, and script would
follow the link and write over a file of the user.
"""

import datetime
import itertools
import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api
import prompting
import waking

# the Python of the picker, which runs the waiter of a run
WAITER = (sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       'waking.py'))

# how a prompt with nothing typed after it ends. Herdr reports no cursor, so
# a last line that ends otherwise may hold a command that the user is typing,
# and the run would join it
PROMPT_ENDS = ('$', '#', '%', '>', '❯')
# the shells that read the heredoc of a run
SHELLS = ('bash', 'zsh', 'sh', 'dash', 'ksh', 'mksh', 'ash')
STEP = '# ---- step'
END = 'END_OF_STEPS'

# POSIX sh runs this whatever the shell of the pane is. script runs each block
# in the shell of the pane, as the user would type it there: the $SHELL that
# the pane inherited may name another shell, such as the login shell
RUNNER = '''\
# one run of herdr-claude-copy: each block of its input is a step under script
run={run}
step_shell=$(command -v {name}) || {{
    echo "add {name} to the PATH: the steps of this run use it" >&2
    exit 1
}}
if ! (set -C; : > "$run/job") 2>/dev/null; then
    echo "this run has already started: press * in the picker for a new one" >&2
    exit 1
fi
mark() {{ printf '%s\\n' "$*" >> "$run/job"; printf '%s\\n' "$*"; }}
printf 'agent %s\\nshell %s\\n' {agent} {shell} >> "$run/job"
# every block is read before the first step runs, since a step takes the
# terminal as its input and the blocks come on the input of this script
n=1
open=
while IFS= read -r line; do
    case $line in
        '{step}'*) if [ -n "$open" ]; then n=$((n + 1)); open=; fi; continue;;
    esac
    if [ -z "$open" ]; then
        mkdir -m 700 "$run/$n"
        printf 'step %s\\n' "$n" >> "$run/job"
        open=1
    fi
    printf '%s\\n' "$line" >> "$run/$n.sh"
done
# the agent hears of the end of the run from a waiter that outlives this
# shell, so a Ctrl+C or a shell that closes is told too
waiting=
if {waiter} "$run" "$$"; then
    waiting=1
else
    echo "Claude will not hear of this run when it ends" >&2
fi
input=/dev/null
if (exec < /dev/tty) 2>/dev/null; then input=/dev/tty; fi
n=1
while [ -f "$run/$n.sh" ]; do
    mark "=== START $n"
    SHELL="$step_shell" STEP_DIR="$run/$n" \\
        script -qefc "$(cat "$run/$n.sh")" "$run/$n/tty.log" < "$input"
    rc=$?
    mark "=== END $n rc=$rc"
    # a step that Ctrl+C stopped: the user wants the whole run stopped, and
    # not only its step
    if [ "$rc" -eq {ctrl_c} ]; then break; fi
    n=$((n + 1))
done
mark "=== DONE"
if [ -n "$waiting" ]; then
    echo "Claude hears of this run once its prompt box is free. To cancel, run: touch $run/{quiet}"
fi
'''


class NoRun(Exception):
    """Why a run cannot be typed, in the words that the picker shows."""


def home():
    return os.path.join(os.environ.get('XDG_STATE_HOME')
                        or os.path.expanduser('~/.local/state'), 'herdr-claude-copy', 'runs')


def at_prompt(info):
    """Whether a shell has the terminal back.

    A shell hands the terminal to the command that it runs, and takes it back
    when the command ends. A pane whose foreground group is not its shell runs
    something: a build, a panel, or a shell in a container.
    """
    shell = info.get('shell_pid')
    return shell is not None and info.get('foreground_process_group_id') == shell


def shell_name(info):
    return next((proc.get('name') or '' for proc in info.get('foreground_processes') or []
                 if proc.get('pid') == info.get('shell_pid')), '')


def empty_line(screen):
    """Whether the last line on that screen is a prompt with nothing after it."""
    last = next((row.rstrip() for row in reversed(screen.splitlines()) if row.strip()), '')
    return last.endswith(PROMPT_ENDS)


def free_shell(panes, agent, standing):
    """The shell that a run of the agent goes to, and the name of its program.

    It is a pane of the tab of the agent, with no agent, at its prompt: the
    one you stand in, else the first. Nothing runs before the Enter of the
    user, so a shell that was not meant costs only a line to clear.
    """
    tab = [pane for pane in panes
           if pane.get('tab_id') == agent.get('tab_id') and not pane.get('agent')]
    for shell in sorted(tab, key=lambda pane: pane['pane_id'] != standing):
        info = api.call('pane', 'process_info', pane_id=shell['pane_id']) \
            .get('process_info') or {}
        if at_prompt(info):
            break
    else:
        raise NoRun('open a shell in this tab, or wait for its command to end')
    name = shell_name(info)
    if name not in SHELLS:
        raise NoRun(f"open bash or zsh in this tab: a run is a heredoc, which "
                    f"{name or 'this shell'} may not read")
    if not empty_line(prompting.screen(shell)):
        raise NoRun('clear the line of the free shell first: it does not end on a prompt')
    return shell, name


def check(blocks):
    """Refuse a block with a line that would cut the run where it stands."""
    for block in blocks:
        for row in block.split('\n'):
            if row == END or row.startswith(STEP):
                raise NoRun(f'copy this block with $ instead: its line "{row}" '
                            f'would cut the run')


def _fresh(root, day):
    """A new directory for a run of that day.

    mkdir fails on any entry already there, a link included, so a run never
    writes through a path that it did not make.
    """
    for n in itertools.count(1):
        path = os.path.join(root, f'{day}-{n}')
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            continue
        return path


def prepare(agent, shell, name, day=None):
    """Write the script of a run in the shell of that name, and return the
    directory of the run."""
    root = home()
    os.makedirs(root, mode=0o700, exist_ok=True)
    # the waiters keep their locks beside the runs, in a directory that must be
    # the user's alone, whatever made it first
    os.chmod(os.path.dirname(root), 0o700)
    run = _fresh(root, day or datetime.date.today().isoformat())
    with open(os.path.join(run, 'run'), 'x') as fp:
        fp.write(RUNNER.format(run=shlex.quote(run), agent=shlex.quote(agent['pane_id']),
                               shell=shlex.quote(shell['pane_id']), name=shlex.quote(name),
                               step=STEP, waiter=shlex.join(WAITER),
                               ctrl_c=waking.CTRL_C, quiet=waking.QUIET))
    return run


def typed(run, blocks):
    """The text typed into the shell: the script of the run, with the blocks
    on its input. It ends with no newline, so the Enter is the user's."""
    path = os.path.join(run, 'run')
    mine = os.path.expanduser('~') + os.sep
    path = '~/' + shlex.quote(path[len(mine):]) if path.startswith(mine) \
        else shlex.quote(path)
    steps = ''.join(f'{STEP} {n}\n{block}\n' for n, block in enumerate(blocks, 1))
    return f"sh {path} <<'{END}'\n{steps}{END}"
