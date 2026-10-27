# herdr-claude-copy

A Herdr plugin that copies the blocks of Claude Code's answers as Claude wrote them, or puts their commands in Claude's prompt box.

A mouse copy takes the screen grid. Claude Code draws a code block two columns in and wraps it at the width of the pane, so the copy keeps that indent and a break in each long line. The picker reads the answers from the session's transcript instead.

## Requirements

- Herdr 0.9.0 or later, on Linux.
- Python 3.10 or later at `/usr/bin/python3`, with no other package. If Pygments is installed for that Python, the picker colours the code.

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
| `p` `n` | previous or next answer |
| `?`, `q` | every key, quit |

The copy goes out as an OSC 52 sequence, which Herdr turns into a clipboard write. The picker finds the session by the title of its pane, which Claude Code sets to the session name, then by the session id that Herdr holds. If neither works, name the session with `/rename`.

## A session in a container

The picker reads the transcripts under `~/.claude/projects`, or `$CLAUDE_CONFIG_DIR/projects`. A Claude Code that runs in a container writes them in another directory. Add that directory to `~/.config/herdr-claude-copy/sources`, one per line:

```
# projects directory                 payload directory (optional)
~/containers/app/.claude/projects
```

Each line adds to the host directory, and never replaces it. The optional second word names a directory where a status line hook saves the payload of each session, as `<session id>.raw.json`.

## Security

- The `!` key puts the code in Claude's prompt box and sends no Enter. When you press Enter, Claude Code runs the text in a shell with your rights, so read it first. The picker removes control characters from the text, so an answer can't end the paste early and send a line.
- Herdr doesn't review or sandbox plugins. This one reads your Claude Code transcripts and drives panes through the Herdr socket: read `bin/` before you install it.

## Development

`python3 tests/test_copy.py` runs the tests, with no Herdr server. `docs/drift.md` names the code that this plugin shares with a private Herdr setup, and `docs/demo.md` is the script of the demo.

## License

MIT, see `LICENSE`.
