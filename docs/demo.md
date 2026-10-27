# Demo

The demo shows the picker on one answer of Claude: a paragraph and three code blocks. Two blocks are marked and copied with `Enter`, then put in Claude's prompt box with `!`. asciinema records it, and agg renders the GIF.

## Prepare

1. Install the plugin and the `prefix+y` binding, as the README says.
2. Size the terminal to 100 columns and 30 rows, with a dark theme.
3. In an empty directory, start Herdr with a tab that holds Claude Code and a shell beside it. Name the session with `/rename demo`.
4. Keep this prompt ready to paste, so that each take gets the same answer:

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

## Record

```sh
asciinema rec --idle-time-limit 1.5 demo.cast
```

In the shell that asciinema opens, attach Herdr with `herdr`. Then:

1. In the Claude pane, paste the prompt and press `Enter`. Wait for the answer.
2. Press `prefix+y`. The picker opens on the answer, with the cursor on the first code block.
3. Press `Space` to mark that block, `Tab` twice to reach the third one, and `Space` again.
4. Press `Enter`. The toast reads `copied 2 blocks, 2 lines`.
5. In the shell pane, paste with the paste key of the terminal. The two commands show with no indent, and nothing runs. Clear the line with `Ctrl+C`.
6. In the Claude pane, press `prefix+y`, mark the same two blocks, and press `!`. The two commands land in Claude's prompt box behind one `!`, and nothing runs.
7. Wait two seconds, detach from Herdr, and type `exit` to stop the recording.

## Render

```sh
agg --font-size 16 demo.cast docs/demo.gif
```

If the GIF is under 5 MB, add it under the first paragraph of the README:

```markdown
![The picker on an answer of Claude](docs/demo.gif)
```
