# Code shared with a private setup

This plugin comes from a private set of Herdr scripts. That setup will install this plugin and remove its own copy of the picker. After that, three pieces still live on both sides, and a change to one side must reach the other.

## The title rule

`bin/sessions.py` decides which Claude session a pane runs: `_title` with its `TRANSIENT` titles, `_names`, `_named`, and the title and identity keys of `resolve_all`. The private setup keeps the same rule for its status panel and its sidebar. It also keeps a third key, the working directory, which the picker refuses.

If Claude Code changes how it titles a pane, for example with a new transient title, change both copies.

## The job file

The `*` key types the marked blocks into a free shell of the tab, as a run of steps that the Enter of the user starts. `bin/busy`, a watcher of the private setup, reads what a run records, and wakes Claude with `agent.prompt` when a step ends. The watcher stays private, so the layout of a run and its job file are a contract: this plugin writes them, and the watcher reads them as written.

A run is the directory `${XDG_STATE_HOME:-~/.local/state}/herdr-claude-copy/runs/<YYYY-MM-DD>-<n>/`, where `n` is the first number from 1 that no entry holds. The picker writes only `run`, the script of the run, there. The run writes the rest when the user starts it:

- `job`, the job file. A run with no job file was never started.
- `<step>.sh`, the text of each block. Steps are named `1`, `2`, and so on, in the order of the blocks.
- `<step>/`, the directory of each step, which the block gets in `STEP_DIR`. `script` writes the terminal output of the block to `<step>/tty.log`, and the block may write other files there.

The run reads every block before the first step runs, so the head of the job file is complete before any `START`:

```
agent <pane id of the agent>
shell <pane id of the shell>
step <step>
```

There is one `step` line per step, in order. The run then appends these lines:

```
=== START <step>
=== END <step> rc=<status>
=== DONE
```

After `END`, the files of the step are complete. `DONE` is the last line of a run: after every step, or after a step that `Ctrl+C` stopped, with status 130. If the shell closes during a run, the job file gets no `DONE`.

## The free shell

`running.at_prompt` decides that a shell is at its prompt: Herdr reports the foreground process group of the pane as the shell itself. The watcher uses the same rule to mark a pane as busy. If Herdr changes `pane.process_info`, change both.
