"""Tell the agent of a run how its steps ended, once the run is over.

    waking.py <run> <pid of the run>

The run starts this before its first step, and this leaves the session of the
shell at once. A Ctrl+C or a shell that closes then ends the run and never the
wait, so the agent hears of both. The wait has two halves: the end of the run,
then a prompt box that can take a line. wake.log, in the directory of the
run, says how the wait ended.

Claude arms no Monitor on a run, so this wake is how it learns that its
commands ran. One wake per run, at its end: a failed step does not stop the
run, and a wake costs a turn.
"""

import fcntl
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api
import prompting

TICK = 1                    # how often the end of a run, or the turn of a wake, is looked for
HOLD = 2                    # how often a held wake looks at the box again
STARTED = 5                 # how long a wake waits for Herdr to show its turn
GIVE_UP = 24 * 3600         # past this after the end of a run, its wake is old news
CTRL_C = '130'
QUIET = 'no-wake'           # the file that cancels a wake, in the directory of the run
# a line typed then would wait for the turn, or answer the dialog
HELD = ('working', 'blocked')


def born(pid):
    """When that process began, or None once it has ended.

    A process that ends leaves its pid to the next one, which never began at
    the same clock tick.
    """
    try:
        with open(f'/proc/{pid}/stat') as fp:
            stat = fp.read()
    except OSError:
        return None
    # the name of the command comes in parentheses, and may hold a space
    fields = stat[stat.rindex(')') + 2:].split()
    # Z: a process that ended, and that its parent has not reaped yet
    return None if fields[0] == 'Z' else fields[19]


def job(run):
    """The agent of a run, its number of steps, the status of each step that
    ended, and whether the run reached its end."""
    found = {'agent': None, 'steps': 0, 'ends': [], 'done': False}
    with open(os.path.join(run, 'job')) as fp:
        for line in fp:
            # the run appends a mark while this reads, and only a whole line
            # is one
            if not line.endswith('\n'):
                break
            words = line.split()
            if len(words) == 2 and words[0] == 'agent':
                found['agent'] = words[1]
            elif words[:1] == ['step']:
                found['steps'] += 1
            elif len(words) == 4 and words[:2] == ['===', 'END']:
                found['ends'].append((words[2], words[3].removeprefix('rc=')))
            elif words == ['===', 'DONE']:
                found['done'] = True
    return found


def over(job):
    """Whether nothing more will end in that run.

    A step that Ctrl+C stopped stops the run, and the job then ends on DONE;
    a read between the two lines must already find the run over.
    """
    return job['done'] or stopped(job['ends']) or 0 < job['steps'] <= len(job['ends'])


def stopped(ends):
    """Whether the last step that ended was stopped by Ctrl+C."""
    return bool(ends) and ends[-1][1] == CTRL_C


def wake_text(run, job, cut):
    """The line that tells an agent how the steps of its run ended, and where
    their files are, enough to read a step with no skill.

    With cut, the shell of the run closed before the run reached its end.
    """
    ends = job['ends']
    said = ', '.join(f'step {step} {"ended with" if n == 0 else "with"} rc={rc}'
                     for n, (step, rc) in enumerate(ends))
    if stopped(ends):
        said += ', a Ctrl+C, and the run stopped there'
    elif cut:
        closed = f'the shell closed during step {len(ends) + 1}'
        said = f'{said}, and {closed}' if said else closed
    said = said[:1].upper() + said[1:]
    return (f'The user ran blocks of your answer in a shell of this tab, as run '
            f'{os.path.basename(run)}, and the run is over. {said}. The files of step N '
            f'are in {os.path.join(run, "N")}: the log of its tool if there is one, then '
            f'tty.log, its terminal output with the header of script and color codes. '
            f'Read them, then go on with the task.')


def end(run, pid, began):
    """Wait until the run is over, and return its job, and whether its shell
    closed first."""
    while True:
        # looked at before the job, so that a run found ended has written
        # all its marks
        alive = born(pid) == began
        found = job(run)
        if over(found) or not alive:
            return found, not over(found)
        time.sleep(TICK)


def lock(run, agent):
    """Hold the lock of that agent, or return None while another wake holds it.

    Two runs of one agent may end together, and the second wake would be
    typed into the turn that the first one started. The locks sit beside the
    directory of the runs, one per agent pane.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(run)), f'wake-{agent}.lock')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def refusal(agent):
    """Why the box of that agent cannot take a line now, or None.

    A turn would queue the line, a dialog would take it as its answer, and a
    draft would take it as its tail.
    """
    status = agent.get('agent_status')
    if status in HELD:
        return f'the agent is {status}'
    held = prompting.box(prompting.screen(agent))
    if held is None:
        return 'the prompt box is not on screen'
    if held:
        return 'the prompt box holds a line'
    return None


def started(pane):
    """Wait until Herdr shows the turn that a wake started, so that the next
    wake to take the lock finds the agent at work."""
    deadline = time.time() + STARTED
    while time.time() < deadline:
        agent = next((p for p in api.panes() if p['pane_id'] == pane), {})
        if agent.get('agent_status') in HELD:
            return
        time.sleep(TICK)


def knock(pane, text):
    """Type the wake into the box of that agent if the box can take it: how
    the wait ended, or None and why it goes on."""
    panes = api.panes()
    # an empty pane list is a server that did not answer, and would read as
    # every agent gone
    if not panes:
        return None, 'the server did not answer'
    agent = next((p for p in panes if p['pane_id'] == pane), None)
    if not (agent and agent.get('agent')):
        return f'{pane} holds no agent, no wake', None
    why = refusal(agent)
    if why:
        return None, why
    prompted = api.call('agent', 'prompt', target=pane, text=text)
    if prompted.get('type') != 'agent_prompted':
        return None, 'the prompt was refused, or its reply lost'
    started(pane)
    return f'woke {pane}', None


def deliver(run, found, cut, ended):
    """Type the wake into the box of the agent that the run names, once the box
    can take it, and say how the wait ended.

    A refused prompt and a lost reply both come back empty from api.call, and
    both are tried again. A refused one typed nothing. A lost one may have
    typed the wake, which then comes twice: a double wake costs a turn, and a
    lost one leaves Claude waiting.
    """
    if not found['ends'] and not cut:
        return 'the run has no step, and nothing to tell'
    text = wake_text(run, found, cut)
    why = None
    while time.time() < ended + GIVE_UP:
        if os.path.exists(os.path.join(run, QUIET)):
            return f'{QUIET} found, no wake'
        held = lock(run, found['agent'])
        if held is None:
            why = 'another wake of this agent was on its way'
        else:
            try:
                said, why = knock(found['agent'], text)
            finally:
                os.close(held)
            if said:
                return said
        time.sleep(HOLD)
    return f'no wake {GIVE_UP // 3600} hours after the end of the run' + (f': {why}' if why else '')


def main(argv):
    run, pid = argv[1], int(argv[2])
    began = born(pid)
    if began is None:
        print(f'no process {pid} runs {run}', file=sys.stderr)
        return 1
    # opened before the fork, so that the shell shows why it failed. A file
    # that is already there may be a link that an agent planted
    try:
        log = os.open(os.path.join(run, 'wake.log'),
                      os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as why:
        print(f'cannot write {run}/wake.log: {why.strerror}', file=sys.stderr)
        return 1
    if os.fork():
        return 0
    os.setsid()
    # a directory that the wait holds could not be unmounted
    os.chdir('/')
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    os.dup2(log, 1)
    os.dup2(log, 2)
    try:
        found, cut = end(run, pid, began)
        said = deliver(run, found, cut, time.time())
    except OSError as why:
        said = f'no wake: {why}'
    print(time.strftime('%Y-%m-%d %H:%M:%S'), said, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
