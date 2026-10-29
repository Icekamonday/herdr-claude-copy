# Demo

The demo is two short recordings of the picker, on a Herdr of its own. The first one marks two blocks of an answer and copies them with `Enter`, then puts them in Claude's prompt box with `!`. The second one runs two blocks in the shell beside Claude with `*`, and Claude hears of the run when it is over. asciinema records each one, and agg renders the GIFs.

## Prepare

1. Install asciinema and agg.
2. Give the demo a home of its own, and open a plain shell in it. Herdr, Claude Code and the plugin then keep their files there, so the recordings show none of your workspaces, sessions or settings. `env -i` starts from an empty environment and passes on the terminal, the language and the display alone. In a pane of your own Herdr, `HERDR_SOCKET_PATH` would otherwise lead `herdr` to your own server. Herdr starts its panes with `$SHELL`, and bash with no startup file shows a prompt that the `*` key reads.

   ```sh
   mkdir -p ~/herdr-demo && cd ~/herdr-demo && env -i HOME="$PWD" SHELL=/bin/bash PATH="$PATH" TERM="$TERM" COLORTERM="$COLORTERM" LANG="$LANG" DISPLAY="$DISPLAY" WAYLAND_DISPLAY="$WAYLAND_DISPLAY" XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" bash --norc
   ```

3. Size the terminal to 120 columns and 32 rows, so that the footer of the picker shows in full.
4. Start Herdr with `herdr`. In its shell, install the plugin, the `prefix+y` key and the Claude Code integration:

   ```sh
   herdr plugin install Icekamonday/herdr-claude-copy &&
   cat >> ~/.config/herdr/config.toml <<'EOF' &&

   [[keys.command]]
   key = "prefix+y"
   type = "shell"
   command = "herdr plugin action invoke pick --plugin herdr-claude-copy"
   description = "copy a block of Claude's last answers"
   EOF
   herdr server reload-config &&
   herdr integration install claude
   ```

5. Start Claude Code in that pane with `claude`, log in, and trust the folder. Name the session with `/rename demo`.
6. Split the tab with `prefix+v`. The new pane, on the right, is the shell of the runs. Go back to Claude with `prefix+h`.
7. Check that the Claude pane shows nothing that you would not publish.
8. Keep these two prompts ready to paste, so that each take gets the same answer. The first one is for the copy:

   ````
   Reply with this text and nothing else:

   Three commands show where the disk space of this directory goes: the total, the free space, and the five largest entries.

   ```sh
   du -sh .
   ```

   ```sh
   df -h .
   ```

   ```sh
   du -sh * | sort -h | tail -5
   ```
   ````

   The second one is for the run:

   ````
   Reply with this text and nothing else:

   Two steps check the machine: a slow one, then a quick one.

   ```sh
   sleep 3; date
   ```

   ```sh
   uname -sr
   ```
   ````

## Record the copy

Detach from Herdr with `prefix+q`, which brings back the shell of step 2, then start the recording:

```sh
asciinema rec --idle-time-limit 1.5 demo-copy.cast
```

In the shell that asciinema opens, attach Herdr with `herdr`. Then:

1. In the Claude pane, paste the first prompt and press `Enter`. Wait for the answer.
2. Press `prefix+y`. The picker opens on the answer, with the cursor on the first code block.
3. Press `Space` to mark that block, `Tab` twice to reach the third one, and `Space` again.
4. Press `Enter`. The toast reads `copied 2 blocks, 2 lines`.
5. In the shell pane, paste with the paste key of the terminal. The two commands show with no indent, and nothing runs. Clear the line with `Ctrl+C`.
6. In the Claude pane, press `prefix+y`, mark the same two blocks, and press `!`. The two commands land in Claude's prompt box behind one `!`, and nothing runs. Clear the box with `Ctrl+C`, so that the prompt of the second take does not land behind the `!`.
7. Wait two seconds, detach from Herdr with `prefix+q`, and type `exit` to stop the recording.

## Record the run

```sh
asciinema rec --idle-time-limit 1.5 demo-run.cast
```

In the shell that asciinema opens, attach Herdr with `herdr`. Then:

1. In the Claude pane, paste the second prompt and press `Enter`. Wait for the answer.
2. Press `prefix+y`. Press `Space` to mark the first block, `Tab` to reach the second one, `Space` again, then `*`. The picker closes, and the shell pane shows the two blocks behind the script of the run.
3. Go to the shell pane with `prefix+l`, and press `Enter`. The two steps run one after the other.
4. Watch the Claude pane. When the run is over, the waiter types how each step ended into Claude's prompt box and sends it, and Claude answers.
5. Wait two seconds after the answer, detach from Herdr with `prefix+q`, and type `exit` to stop the recording.

## Render

In a shell of your own, from the clone of this repository:

```sh
agg --font-size 16 ~/herdr-demo/demo-copy.cast docs/demo-copy.gif &&
agg --font-size 16 ~/herdr-demo/demo-run.cast docs/demo-run.gif
```

If each GIF is under 5 MB, add the first one under the first paragraph of the README, and the second one under the heading *Run the blocks in a shell of the tab*:

```markdown
![The picker copies two blocks of an answer, then puts them in Claude's prompt box](docs/demo-copy.gif)
```

```markdown
![Two blocks run in the shell beside Claude, and Claude hears of the run](docs/demo-run.gif)
```

`~/herdr-demo` keeps the login of Claude Code for the next takes. To remove it, stop its server with `env -i HOME="$HOME/herdr-demo" PATH="$PATH" herdr server stop`, then delete the directory. In a pane of your own Herdr, `HERDR_SOCKET_PATH` would otherwise stop your own server.
