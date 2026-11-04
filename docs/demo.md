# Demo

The demo is two short recordings of the picker, on a Herdr of its own. The first one marks the code blocks of an answer with `c` and copies them with `Enter`. Then it puts them in Claude's prompt box with `!`. The second one runs the code blocks of another answer in the shell beside Claude with `*`. Claude hears of the run when it is over. asciinema records each one, and agg renders the GIFs.

## Prepare

1. Install asciinema and agg in a directory of your `PATH`, such as `~/.local/bin`. asciinema runs under the HOME of the demo. There, the shims of a version manager such as asdf fail, so give asciinema the Python of the system:

   ```sh
   uv tool install --python /usr/bin/python3 asciinema
   ```

   For agg, take the binary of your platform from the releases of `asciinema/agg` on GitHub.

2. Open a terminal window of its own, 128 columns by 32 rows, so that the footer of the picker shows in full. The folded sidebar of Herdr and the frame of the picker take 8 columns, and the footer takes 117 when three blocks are marked. Open it at that size, as `gnome-terminal --geometry=128x32` does, since some terminals ignore a resize sequence. A pane of your own Herdr doesn't do: if both use the same prefix, your Herdr catches the keys of the demo.
3. Give the demo a home of its own. Herdr, Claude Code and the plugin then keep their files there, so the recordings show none of your workspaces, sessions or settings. Create the home, with a shell for the panes of Herdr:

   ```sh
   mkdir -m 700 -p /var/tmp/herdr-demo && mkdir -p /var/tmp/herdr-demo/bin && printf '#!/bin/sh\nexec /bin/bash --noprofile --norc "$@"\n' > /var/tmp/herdr-demo/bin/bash && chmod +x /var/tmp/herdr-demo/bin/bash
   ```

   The home is outside `/home`, so that its path names no user. Only you can read it, since it keeps the login of Claude Code. Some systems delete the files in `/var/tmp` that nobody used for 30 days, as systemd does by default. A later take may then ask for the login again.

   Herdr starts its panes with `$SHELL`. A bash that reads the startup files of the system may put your user and host names in its prompt, as `/etc/bash.bashrc` does on Debian and Ubuntu. The shell of the panes starts bash with no startup file, so its prompt ends with a `$` that the `*` key reads. `exec` keeps `bash` as the name of the process, which the `*` key checks.

   Then open a plain shell in the home. `env -i` starts from an empty environment and passes on the terminal, the language and the display alone. In a pane of your own Herdr, `HERDR_SOCKET_PATH` would otherwise lead `herdr` to your own server.

   ```sh
   cd /var/tmp/herdr-demo && env -i HOME="$PWD" SHELL="$PWD/bin/bash" PATH="$PATH" TERM="$TERM" COLORTERM="$COLORTERM" LANG="$LANG" DISPLAY="$DISPLAY" WAYLAND_DISPLAY="$WAYLAND_DISPLAY" XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" bash --norc
   ```

   `stty size` must answer `32 128`.

4. Start Herdr with `herdr`. In its shell, install the plugin and the `prefix+y` key:

   ```sh
   herdr plugin install Icekamonday/herdr-claude-copy &&
   cat >> ~/.config/herdr/config.toml <<'EOF' &&

   [[keys.command]]
   key = "prefix+y"
   type = "shell"
   command = "herdr plugin action invoke pick --plugin herdr-claude-copy"
   description = "copy a block of Claude's last answers"
   EOF
   herdr server reload-config
   ```

   The demo leaves out the Claude Code integration of Herdr, which the plugin doesn't need. With the integration, Herdr also resumes Claude Code after a restart, which the demo doesn't show.

5. Fold the sidebar with `prefix+b`, so that the tab gets almost all of the columns.
6. Start Claude Code in that pane with `claude`, log in, and trust the folder. Name the session with `/rename demo`.
7. Split the tab with `prefix+v`. The new pane, on the right, is the shell of the runs. Go back to Claude with `prefix+h`.
8. Check that the Claude pane shows nothing that you would not publish. The account of an organization can show a message of that organization in the welcome box. If it does, log in with a personal account.
9. Keep these two prompts ready to paste, so that each take gets the same answer. The first one is for the copy:

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

Each take starts on an answer that is already on the screen. In the Claude pane, paste the first prompt, press `Enter`, and wait for the answer. Then detach from Herdr with `prefix+q`, which brings back the shell of step 3. Check that `stty size` still answers `32 128`, then start the recording:

```sh
stty size
```

```sh
asciinema rec --idle-time-limit 1.5 demo-copy.cast
```

To record a take again, add `--overwrite`: asciinema refuses to replace a recording.

In the shell that asciinema opens, attach Herdr with `herdr`. Press no prefix before step 1: the cut of the Render section starts the take at the first press. Then:

1. Press `prefix+y`. The picker opens on the answer, with the cursor on the first code block.
2. Press `c` to mark the three code blocks. The footer starts with `3 marked`.
3. Press `Enter`. The picker closes, and Herdr shows the toast `copied to clipboard`.
4. Go to the shell pane with `prefix+l`, and paste with the paste key of the terminal. The three commands show with no indent, and nothing runs. Clear the line with `Ctrl+C`.
5. Go back to Claude with `prefix+h`, then press `prefix+y`, `c` and `!`. The three commands land in Claude's prompt box behind one `!`, and nothing runs.
6. Wait two seconds, detach from Herdr with `prefix+q`, and type `exit` to stop the recording.

## Record the run

First clear the panes, outside a recording. Attach Herdr with `herdr`. In the Claude pane, empty the prompt box with `Ctrl+C`, then press `Backspace` until the `❯` of the prompt comes back. Clear the conversation with `/clear`, and name the session again with `/rename demo`. In the shell pane, type `clear`.

Then, in the Claude pane, paste the second prompt, press `Enter`, and wait for the answer. Detach with `prefix+q`, check that `stty size` still answers `32 128`, and start the recording:

```sh
stty size
```

```sh
asciinema rec --idle-time-limit 1.5 demo-run.cast
```

In the shell that asciinema opens, attach Herdr with `herdr`. Press no prefix before step 1. Then:

1. Press `prefix+y`, then `c` to mark the two code blocks, then `*`. The picker closes, and the shell pane shows the two blocks behind the script of the run.
2. Go to the shell pane with `prefix+l`, and press `Enter`. The two steps run one after the other.
3. Watch the Claude pane. When the run is over, the waiter types how each step ended into Claude's prompt box and sends it, and Claude answers.
4. Wait two seconds after the answer, detach from Herdr with `prefix+q`, and type `exit` to stop the recording.

## Render

A cut keeps the part of each take between the first press of the prefix and the last one. Herdr shows `PREFIX` at the bottom of the screen after each press, and the cut finds the presses there. The take starts one second before the first press, which opens the picker. The output before that point plays at once, so the first frame shows the answer. The take ends at the last press, which detaches.

The cut also turns each no-break space into a plain space. Claude Code writes one after some marks, such as its prompt `❯`, and agg 1.9.0 draws a `€` for it.

Write the cut next to the recordings:

```sh
cat > /var/tmp/herdr-demo/cut.py <<'EOF'
import json
import sys

source, target = sys.argv[1], sys.argv[2]
skip = [float(second) for second in sys.argv[3:5]]
lines = open(source, encoding='utf-8').read().splitlines()
events = [json.loads(line) for line in lines[1:]]
presses = [t for t, kind, data in events if kind == 'o' and 'PREFIX' in data]
start, end = presses[0] - 1, presses[-1]


def shown(t):
    if skip and t >= skip[1]:
        t -= skip[1] - skip[0]
    elif skip and t > skip[0]:
        t = skip[0]
    return max(t - start, 0)


with open(target, 'w', encoding='utf-8') as out:
    out.write(lines[0] + '\n')
    for t, kind, data in events:
        if t >= end:
            break
        out.write(json.dumps([shown(t), kind, data.replace(' ', ' ')]) + '\n')
EOF
```

Then cut and render both takes, in a shell of your own, from the clone of this repository:

```sh
for take in copy run; do python3 /var/tmp/herdr-demo/cut.py /var/tmp/herdr-demo/demo-$take.cast /var/tmp/herdr-demo/agg-$take.cast && agg --font-size 16 /var/tmp/herdr-demo/agg-$take.cast docs/demo-$take.gif || break; done
```

Claude can work for some seconds on the wake of the run, and its spinner moves all the time, so `--idle-time-limit` can't shorten that span. To skip it, give the cut its first and its last second, after the two paths. Each line of a recording starts with its second, so a search for a word on the screen finds them, such as `Running` for the first tool call of Claude and the first word of its answer. Keep a second of the work, so that the GIF shows that Claude acts on the wake:

```sh
python3 /var/tmp/herdr-demo/cut.py /var/tmp/herdr-demo/demo-run.cast /var/tmp/herdr-demo/agg-run.cast 57.0 65.6 && agg --font-size 16 /var/tmp/herdr-demo/agg-run.cast docs/demo-run.gif
```

The two seconds in this block are those of the recording in this repository: a new take has its own.

Keep each GIF under 1.5 MB: if one is larger, render it again with `--fps-cap 10` added. Add the first one, with its caption, under the first paragraph of the README, and the second one under the heading *Run the blocks in a shell of the tab*:

```markdown
![The picker copies the code blocks of an answer, then puts them in Claude's prompt box](docs/demo-copy.gif)

In this demo, `c` marks the three code blocks of the answer. `Enter` copies them, and a paste into the shell beside Claude shows them with no indent. Then `!` puts them in Claude's prompt box, behind one `!`.
```

```markdown
![Two blocks run in the shell beside Claude, and Claude hears of the run](docs/demo-run.gif)
```

`/var/tmp/herdr-demo` keeps the login of Claude Code for the next takes. To remove it, stop its server with `env -i HOME=/var/tmp/herdr-demo PATH="$PATH" herdr server stop`, then delete the directory. In a pane of your own Herdr, `HERDR_SOCKET_PATH` would otherwise stop your own server.
