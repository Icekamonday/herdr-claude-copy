# Code shared with a private setup

This plugin comes from a private set of Herdr scripts. That setup will install this plugin and remove its own copy of the picker. After that, two pieces still live on both sides, and a change to one side must reach the other.

## The title rule

`bin/sessions.py` decides which Claude session a pane runs: `_title` with its `TRANSIENT` titles, `_names`, `_named`, and the title and identity keys of `resolve_all`. The private setup keeps the same rule for its status panel and its sidebar. It also keeps a third key, the working directory, which the picker refuses.

If Claude Code changes how it titles a pane, for example with a new transient title, change both copies.

## The wake after a run

A planned key of the picker will run the marked blocks in a shell of the tab. Each block will log into a directory of its own, passed in `STEP_DIR`, which the agent can't write. When a block ends, `bin/busy`, a watcher of the private setup, will wake Claude with `agent.prompt`.

The watcher stays private. So the log directory, the name of each step and the mark of its end become a contract: this plugin writes them, and `bin/busy` reads them.
