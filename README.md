# herdr-claude-copy

A Herdr plugin that copies the blocks of Claude Code's answers as Claude wrote them, or puts their commands in Claude's prompt box or in a shell of the tab.

A mouse copy takes the screen grid. Claude Code draws a code block two columns in and wraps it at the width of the pane, so the copy keeps that indent and a break in each long line. The picker reads the answers from the session's transcript instead.

## Requirements

- Herdr 0.9.0 or later, on Linux. The `*` key asks Herdr which process runs in each shell, and was checked on Herdr 0.9.3 only.
- Python 3.10 or later at `/usr/bin/python3`, with no other package. If Pygments is installed for that Python, the picker colours the code.
- `script` of util-linux, for the `*` key.

## Install

```sh
herdr plugin install Icekamonday/herdr-claude-copy
```

A plugin manifest can't declare a key, so add the binding to `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "prefix+y"
type = "shell"
command = "herdr plugin action invoke pick --plugin herdr-claude-copy"
description = "copy a block of Claude's last answers"
```

Then reload the configuration with `herdr server reload-config`.

## Use

Press `prefix+y` in a tab that runs Claude Code. The picker opens on the last answer, with the cursor on its first code block.

| Key | Action |
|---|---|
| `j` `k`, `Tab` `Shift+Tab` | next or previous block, or block of code |
| `Space`, `a` | mark the block at the cursor, or every block |
| `Enter` | copy the marked blocks, else the block at the cursor |
| `!` | copy their shell code behind one `!`, and put it in Claude's prompt box |
| `$` | copy their code for a shell, with no `!` |
| `*` | put their shell code in a free shell of the tab, as a run of one step per block |
| `p` `n` | previous or next answer |
| `?`, `q` | every key, quit |

The copy goes out as an OSC 52 sequence, which Herdr turns into a clipboard write. The picker finds the session by the title of its pane, which Claude Code sets to the session name, then by the session id that Herdr holds. If the title names no session, the session id decides alone: with `CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1`, for example, the pane keeps the title that the shell set. If neither works, name the session with `/rename`.

## Run the blocks in a shell of the tab

The `*` key puts the shell blocks of the selection in a free shell of the tab, as a run of one step per block, and sends no Enter. A free shell is a pane of the tab with no agent, whose shell is at its prompt: the one you stand in, else the first.

The shell shows the blocks as they will run, behind the script of the run:

```sh
sh ~/.local/state/herdr-claude-copy/runs/2026-10-28-3/run <<'END_OF_STEPS'
# ---- step 1
make test
# ---- step 2
git status
END_OF_STEPS
```

Read the blocks, edit them if you want, and press Enter to start the run. Each block runs under `script`, in the shell of the pane and not in `$SHELL`, with the directory of its step in `STEP_DIR`:

```
runs/2026-10-28-3/
  run          the script of the run
  job          the agent, the shell, the steps, and when each step starts and ends
  1.sh         the first block
  1/tty.log    what the first block wrote to the terminal
  wake.log     how the wake of Claude went
```

A tool that writes its own log can write it into `$STEP_DIR`. A step that fails doesn't stop the run, since its status is often the answer. `Ctrl+C` stops the step and the rest of the run. A run starts once: if you type the same text again from the history, press `*` again instead. `bin/running.py` states the format of `job`.

The run is a heredoc, so the key refuses a shell other than bash, zsh or another POSIX shell. The text goes out as a bracketed paste, as for the `!` key: bash 5.1 and zsh turn it on by default. If your shell has it off, nothing runs before your Enter either, but you can't edit the lines, and a tab in a block triggers completion.

Herdr doesn't report where the cursor is, so the picker reads the last line on the screen of the shell. If that line doesn't end with `$`, `#`, `%`, `>` or `❯`, you may be typing a command there, and the key does nothing but say so. If your prompt ends with another character, or shows text on its right, the key refuses every time.

When the run is over, Claude hears of it: a waiter types into Claude's prompt box how each step ended and where its files are, and sends it. The run is over after its last step, after a `Ctrl+C`, or when its shell closes. The run starts the waiter before its first step, in a session of its own, so the waiter outlives both a `Ctrl+C` and the shell.

The waiter types only into a box that can take a line. Claude must not be working or waiting on a dialog, and the box must be on screen and empty. The waiter reads the pane of Claude even when its tab isn't displayed, so you can switch to another space during the run. If the box can't take the line, the waiter looks again every 2 seconds. It gives up 24 hours after the end of the run, or when the pane of Claude closes or no longer runs Claude. To cancel a wake, create the file `no-wake` in the directory of the run: the run shows the command when it ends. `wake.log` says how the wake went.

If two runs of one Claude end together, the second wake waits for the turn that the first one starts. For that, each waiter takes a lock on the pane of Claude: an empty file `wake-<pane id>.lock` in `~/.local/state/herdr-claude-copy/`, next to `runs/`. These files are harmless, and you can delete them when no run is waiting.

## A session in a container

The picker reads the transcripts under `~/.claude/projects`, or `$CLAUDE_CONFIG_DIR/projects`. A Claude Code that runs in a container writes them in another directory. Add that directory to `~/.config/herdr-claude-copy/sources`, one per line:

```
# projects directory                 payload directory (optional)
~/containers/app/.claude/projects
```

Each line adds to the host directory, and never replaces it. The optional second word names a directory where a status line hook saves the payload of each session, as `<session id>.raw.json`.

## Security

- The `!` key puts the code in Claude's prompt box and sends no Enter. When you press Enter, Claude Code runs the text in a shell with your rights, so read it first. The picker removes control characters from the text, so an answer can't end the paste early and send a line.
- The `*` key puts the code in a shell and sends no Enter. When you press Enter, the shell runs the blocks with your rights, so read them first. The picker removes control characters from the blocks, as for the `!` key.
- The wake that the waiter types into Claude's prompt box holds the name of the run, the status of each step and the directory of the run. It never holds what a step wrote.
- `script` follows a link planted at the path of its log. If your agent can write the runs directory, it can plant one and make the shell write over another of your files. If it can write the directory above, it can also hold the lock of a wake and keep Claude from hearing of its runs. Check that the sandbox of your agent can't write `~/.local/state/herdr-claude-copy`.
- Herdr doesn't review or sandbox plugins. This one reads your Claude Code transcripts and drives panes through the Herdr socket: read `bin/` before you install it.

## Development

`python3 tests/test_copy.py` runs the tests, with no Herdr server. `docs/drift.md` names the code that this plugin shares with a private Herdr setup, and `docs/demo.md` is the script of the demo.

## License

MIT, see `LICENSE`.
