#!/usr/bin/env python3
"""Drive the copy picker against a stub of the Herdr socket.

The picker reads transcripts and payloads, and asks Herdr through its socket.
A stub server, a fixed world of panes and the transcripts that each test
writes are enough to run it whole.
"""

import contextlib
import importlib
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(HERE), 'bin')

ROOM = None
STOP = None


def setUpModule():
    """Serve the fixed world on a socket, and point each path that the picker
    reads at an empty room: a test that read the sessions of the machine would
    pass or fail with the machine."""
    global ROOM, STOP
    sys.path.insert(0, os.path.join(HERE, 'stub'))
    sys.path.insert(0, BIN)
    import server
    ROOM = tempfile.mkdtemp(prefix='herdr-copy-test-')
    os.environ.update({
        'HERDR_SOCKET_PATH': os.path.join(ROOM, 'herdr.sock'),
        'XDG_CONFIG_HOME': os.path.join(ROOM, 'config'),
        'CLAUDE_CONFIG_DIR': os.path.join(ROOM, 'claude'),
        'CLAUDE_TMUX_STATE': os.path.join(ROOM, 'state'),
        'XDG_STATE_HOME': os.path.join(ROOM, 'xdg-state'),
    })
    os.environ.pop('HERDR_PLUGIN_CONTEXT_JSON', None)
    os.environ.pop('HERDR_PANE_ID', None)
    STOP = server.start(os.environ['HERDR_SOCKET_PATH'])


def tearDownModule():
    STOP.set()
    shutil.rmtree(ROOM, ignore_errors=True)


def run(**extra):
    """bin/copy as Herdr runs it, from a shell of the first tab by default.

    The interpreter of the suite runs it, so that each Python of the CI tests
    itself, and a pipe stands for the terminal: the picker then prints the
    blocks of the last answer instead of opening.
    """
    env = dict(os.environ, **dict({'HERDR_PANE_ID': 'w1:p2'}, **extra))
    return subprocess.run([sys.executable, os.path.join(BIN, 'copy')],
                          check=False, capture_output=True, text=True, timeout=30,
                          env=env)


@contextlib.contextmanager
def stub_log():
    """Collect what was asked of Herdr.

    The socket stub answers inside this process, so the variable has to be
    set here and not only in the environment of the script under test.
    """
    with tempfile.TemporaryDirectory() as room:
        path = os.path.join(room, 'calls')
        os.environ['HERDR_STUB_LOG'] = path
        try:
            yield path
        finally:
            del os.environ['HERDR_STUB_LOG']


def user(content, **extra):
    """A user record, as Claude Code writes it in a transcript."""
    return dict({'type': 'user', 'message': {'role': 'user', 'content': content}},
                **extra)


def claude(message_id, block, **extra):
    """One record of an answer: Claude Code writes one content block per record."""
    return dict({'type': 'assistant', 'message': {
        'id': message_id, 'role': 'assistant', 'content': [block]}}, **extra)


def text(words):
    return {'type': 'text', 'text': words}


def write_transcript(path, records):
    with open(path, 'w') as fp:
        fp.writelines(json.dumps(record) + '\n' for record in records)


ONE = '11111111-1111-4111-8111-111111111111'
TWO = '22222222-2222-4222-8222-222222222222'


def titled(name):
    return {'type': 'custom-title', 'customTitle': name}


# how a transcript records a compaction
COMPACT = ('{"type": "system", "subtype": "compact_boundary", '
           '"content": "Conversation compacted"}')


class Picking(unittest.TestCase):
    """What the copy picker reads in a transcript, shows, and copies."""

    def setUp(self):
        loader = importlib.machinery.SourceFileLoader(
            'copy_picker', os.path.join(BIN, 'copy'))
        spec = importlib.util.spec_from_loader('copy_picker', loader)
        self.copy = importlib.util.module_from_spec(spec)
        loader.exec_module(self.copy)

    def book(self, *texts):
        return [{'prompt': 'q', 'text': text, 'blocks': self.copy.blocks(text)}
                for text in texts]

    def press(self, book, *keys):
        state, done = self.copy.opened(book), None
        for key in keys:
            state, done = self.copy.step(state, key, book)
        return state, done

    def test_an_answer_is_cut_into_its_blocks_in_order(self):
        """A list keeps the blank lines between its items, and stays one block."""
        answer = ('## Build\nRun this first:\n\n```sh\nmake -j8\n```\n\nThen:\n\n'
                  '- one\n- two\n\n  more about two\n\n- three\n\n'
                  '| a | b |\n|---|---|\n\n```\nplain\n```')
        found = self.copy.blocks(answer)
        self.assertEqual([(block['kind'], block['lang']) for block in found], [
            ('heading', ''), ('paragraph', ''), ('code', 'sh'), ('paragraph', ''),
            ('list', ''), ('table', ''), ('code', '')])
        self.assertEqual(found[2]['text'], 'make -j8')
        self.assertEqual(found[4]['text'], '- one\n- two\n\n  more about two\n\n- three')

    def test_a_list_under_the_line_that_announces_it_is_a_block_of_its_own(self):
        """Claude writes "two things:" and its list with no blank line between."""
        found = self.copy.blocks('Two things:\n- one\n- two\n\nAnd 2026. was a year.\n\nEnd.')
        self.assertEqual([block['kind'] for block in found],
                         ['paragraph', 'list', 'paragraph', 'paragraph'])
        self.assertEqual(found[1]['text'], '- one\n- two')

    def test_a_block_in_a_list_item_loses_the_indent_of_the_item(self):
        """The two columns belong to the item, and the indent of the code stays."""
        answer = '- Run:\n  ```sh\n  for f in *; do\n    echo "$f"\n  done\n  ```\n- Done.'
        found = self.copy.blocks(answer)
        self.assertEqual([block['kind'] for block in found], ['list', 'code', 'list'])
        self.assertEqual(found[1]['text'], 'for f in *; do\n  echo "$f"\ndone')
        self.assertEqual(found[1]['indent'], 2)

    def test_each_message_of_claude_is_an_answer_under_the_prompt_of_its_turn(self):
        """A tool result and a record that Claude Code adds keep the turn open.
        A local command opens a turn with no text, and a subagent answers no one."""
        with tempfile.TemporaryDirectory() as room:
            path = os.path.join(room, 'session.jsonl')
            write_transcript(path, [
                user('first question'),
                claude('m1', text('Looking.')),
                claude('m1', {'type': 'tool_use', 'id': 't1', 'name': 'Bash',
                              'input': {}}),
                user([{'type': 'tool_result', 'tool_use_id': 't1', 'content': 'ok'}]),
                claude('m2', text('Found it.')),
                user('<system-reminder>a reminder</system-reminder>', isMeta=True),
                user('<command-name>/copy</command-name>'),
                user('<local-command-stdout>Copied</local-command-stdout>'),
                user('second question'),
                claude('m3', text('Here:\n\n```sh\nls\n```')),
                claude('m4', text('a subagent'), isSidechain=True),
            ])
            book = self.copy.pages(path)
        self.assertEqual([(page['prompt'], page['text']) for page in book[:2]],
                         [('first question', 'Looking.'),
                          ('first question', 'Found it.')])
        self.assertEqual(book[-1]['prompt'], 'second question')
        state = self.copy.opened(book)
        self.assertEqual(self.copy.selection(state, book[-1]), ('ls', 'the sh block'))

    def test_an_answer_after_a_compaction_keeps_the_prompt_of_its_turn(self):
        """Claude Code writes the summary as a user record of its own."""
        with tempfile.TemporaryDirectory() as room:
            path = os.path.join(room, 'session.jsonl')
            write_transcript(path, [
                user('fix the bug'),
                claude('m1', text('Looking.')),
                json.loads(COMPACT),
                user('This session is being continued from a previous '
                     'conversation that ran out of context.',
                     isCompactSummary=True, isVisibleInTranscriptOnly=True),
                claude('m2', text('Fixed.')),
            ])
            book = self.copy.pages(path)
        self.assertEqual([(page['prompt'], page['text']) for page in book],
                         [('fix the bug', 'Looking.'), ('fix the bug', 'Fixed.')])

    def test_a_long_transcript_is_read_from_its_tail(self):
        """A turn that the start of the tail cuts is left out with its prompt."""
        kept = [claude('m1', text('Also cut.')), user('second question'),
                claude('m2', text('Kept.'))]
        with tempfile.TemporaryDirectory() as room:
            path = os.path.join(room, 'session.jsonl')
            write_transcript(path, [user('first question'),
                                    claude('m1', text('x' * 400)), *kept])
            self.copy.TAIL = sum(len(json.dumps(record)) + 1 for record in kept) + 200
            book = self.copy.pages(path)
        self.assertEqual([(page['prompt'], page['text']) for page in book],
                         [('second question', 'Kept.')])

    def test_tab_goes_from_code_to_code_and_stops_at_the_last(self):
        book = self.book('a\n\n```sh\none\n```\n\nb\n\n```sh\ntwo\n```\n\nc')
        self.assertEqual(self.press(book)[0]['cursor'], 1)
        self.assertEqual(self.press(book, '\t', '\t')[0]['cursor'], 3)
        self.assertEqual(self.press(book, '\t', 'KEY_BTAB')[0]['cursor'], 1)
        self.assertEqual(self.press(book, 'G', 'j')[0]['cursor'], 4)

    def test_blocks_of_code_alone_are_copied_to_be_run(self):
        book = self.book('a\n\n```sh\none\n```\n\nb\n\n```sh\ntwo\n```')
        state, done = self.press(book, ' ', '\t', ' ', '\n')
        self.assertEqual(done, 'copy')
        self.assertEqual(self.copy.selection(state, book[0]), ('one\ntwo', '2 blocks'))

    def test_prose_in_the_selection_keeps_the_markdown_of_every_block(self):
        book = self.book('Run:\n\n```sh\none\n```\n\nDone.')
        state, _ = self.press(book, ' ', 'k', ' ')
        self.assertEqual(self.copy.selection(state, book[0]),
                         ('Run:\n\n```sh\none\n```', '2 blocks'))

    def test_a_marks_every_block_and_a_mark_can_then_be_taken_off(self):
        book = self.book('Run:\n\n```sh\none\n```\n\nThen check.')
        state, _ = self.press(book, 'a')
        text, what = self.copy.selection(state, book[0])
        self.assertEqual(text, book[0]['text'])
        self.assertEqual(self.copy.said(what, text), 'copied the whole answer, 7 lines')
        state, _ = self.press(book, 'a', ' ')
        self.assertEqual(self.copy.selection(state, book[0]),
                         ('Run:\n\nThen check.', '2 blocks'))
        self.assertEqual(self.press(book, 'a', 'a')[0]['marked'], frozenset())

    def test_shift_a_copies_the_whole_answer_at_once(self):
        book = self.book('Run:\n\n```sh\none\n```')
        state, done = self.press(book, 'A')
        self.assertEqual(done, 'copy')
        self.assertEqual(self.copy.selection(state, book[0]),
                         (book[0]['text'], 'the whole answer'))

    def test_another_answer_starts_with_no_mark_and_the_ends_hold(self):
        book = self.book('one', 'two')
        state, _ = self.press(book, ' ', 'p', 'p')
        self.assertEqual((state['page'], state['marked']), (0, frozenset()))
        state, done = self.press(book, 'n', 'q')
        self.assertEqual((state['page'], done), (1, 'quit'))

    def test_a_list_item_wraps_under_its_text_without_the_marks(self):
        page = self.book('- a `command` and **a word** that make this item wrap twice')[0]
        rows = [''.join(run for run, _ in row['runs'])
                for row in self.copy.layout(page, 20)]
        self.assertEqual(rows[0], '- a command and a')
        self.assertTrue(all(row.startswith('  ') for row in rows[1:]), rows)
        self.assertTrue(all(len(row) <= 20 for row in rows), rows)

    def test_a_code_line_wider_than_the_pane_is_cut_and_kept_whole(self):
        line = 'printf "%s\\n" one two three four five six seven'
        page = self.book(f'```sh\n{line}\n```')[0]
        rows = [''.join(run for run, _ in row['runs'])
                for row in self.copy.layout(page, 24)]
        self.assertEqual(''.join(row[1:-1] for row in rows[1:]).rstrip(), line)
        self.assertTrue(all(len(row) == 24 for row in rows), rows)

    def test_the_view_follows_the_cursor_and_shows_a_tall_block_from_its_top(self):
        rows = [{'block': 0}] * 5 + [{'block': None}] + [{'block': 1}] * 10
        state = {'cursor': 1, 'top': 0, 'follow': True}
        self.assertEqual(self.copy.view(rows, state, 6), 6)
        self.assertEqual(self.copy.view(rows, dict(state, cursor=0, top=6), 6), 0)
        self.assertEqual(self.copy.view(rows, dict(state, top=99, follow=False), 6), 10)

    def test_a_block_in_a_language_unknown_keeps_one_colour(self):
        self.assertEqual(self.copy.highlight('x = 1', 'nosuchlanguage'),
                         [[('x = 1', 'code')]])
        self.assertEqual(self.copy.highlight('x = 1', ''), [[('x = 1', 'code')]])

    @unittest.skipUnless(importlib.util.find_spec('pygments'), 'no Pygments')
    def test_pygments_colours_a_shell_block(self):
        styles = {style for line in self.copy.highlight('# done\necho "$HOME"', 'sh')
                  for _, style in line}
        self.assertTrue({'builtin', 'string', 'comment'} <= styles, styles)

    def test_a_command_shows_as_it_was_typed(self):
        prompt = self.copy._prompt(
            '<command-message>review</command-message>\n'
            '<command-name>/review</command-name>\n'
            '<command-args>the last commit</command-args>')
        self.assertEqual(prompt, '/review the last commit')
        self.assertEqual(self.copy._prompt([text('look'), {'type': 'image'}]),
                         'look\n[image]')

    def test_a_shell_command_is_the_prompt_and_its_output_is_not(self):
        """Claude answers a ! command once its output is recorded after it."""
        with tempfile.TemporaryDirectory() as room:
            path = os.path.join(room, 'session.jsonl')
            write_transcript(path, [
                user('<bash-input>cd /tmp\npwd</bash-input>'),
                user('<bash-stdout>/tmp</bash-stdout><bash-stderr></bash-stderr>'),
                claude('m1', text('It passes.')),
            ])
            book = self.copy.pages(path)
        self.assertEqual([(page['prompt'], page['text']) for page in book],
                         [('! cd /tmp\npwd', 'It passes.')])

    def test_code_in_bold_loses_its_backticks(self):
        self.assertEqual(self.copy.spans('**T1, the `!` mark** and more'),
                         [('T1, the ', 'bold'), ('!', 'inline'), (' mark', 'bold'),
                          (' and more', 'text')])

    def test_a_long_prompt_is_cut_on_its_own_ground(self):
        rows = [''.join(run for run, _ in row)
                for row in self.copy.asked('one\ntwo\nthree\nfour', 20, 3)]
        self.assertEqual([row.rstrip() for row in rows],
                         ['❯ one', '  two', '  … 2 more lines'])
        self.assertTrue(all(len(row) == 20 for row in rows), rows)

    def test_a_key_that_closes_the_help_does_nothing_else(self):
        book = self.book('one')
        state, done = self.press(book, '?')
        self.assertTrue(state['help'])
        state, done = self.press(book, '?', 'q')
        self.assertEqual((state['help'], done), (False, None))

    def test_the_cursor_a_mark_and_both_have_colours_of_their_own(self):
        self.assertEqual(self.copy.tint('head', True, False), 'head-cursor')
        self.assertEqual(self.copy.tint('head', False, True), 'head-mark')
        self.assertEqual(self.copy.tint('head', True, True), 'head-both')
        self.assertEqual(self.copy.tint('text', True, True), 'text-cursor')
        self.assertEqual(self.copy.tint('code', True, True), 'code')

    def ran(self, done, answer, *keys):
        book = self.book(answer)
        state, _ = self.press(book, *keys)
        return self.copy.prepared(done, state, book[0])[0]

    def test_bang_and_dollar_are_the_keys_of_claude_and_of_a_shell(self):
        book = self.book('```sh\nls\n```')
        self.assertEqual(self.press(book, '!')[1], 'claude')
        self.assertEqual(self.press(book, '$')[1], 'shell')

    def test_a_block_with_its_bang_keeps_one_for_claude_and_none_for_a_shell(self):
        answer = '```sh\n!echo T1\n```'
        self.assertEqual(self.ran('claude', answer), '!echo T1')
        self.assertEqual(self.ran('shell', answer), 'echo T1')
        self.assertEqual(self.ran('copy', answer), '!echo T1')

    def test_blocks_for_claude_take_one_bang_in_front_and_no_other(self):
        """Whichever block carries a bang, with or without a language."""
        for first, second in (('echo a', 'echo b'), ('!echo a', '!echo b'),
                              ('echo a', '!echo b'), ('!echo a', 'echo b')):
            answer = f'```sh\n{first}\n```\n\n```\n{second}\n```'
            self.assertEqual(self.ran('claude', answer, ' ', '\t', ' '),
                             '!echo a\necho b', answer)
            self.assertEqual(self.ran('shell', answer, ' ', '\t', ' '),
                             'echo a\necho b', answer)

    def test_each_line_of_a_block_loses_its_bang(self):
        answer = '```sh\n!echo 1\n!echo 2\n```'
        self.assertEqual(self.ran('claude', answer), '!echo 1\necho 2')
        self.assertEqual(self.ran('shell', answer), 'echo 1\necho 2')

    def test_a_bang_and_its_space_are_the_mark_of_claude(self):
        """Claude writes "! git status" far more often than "!git status"."""
        answer = '```sh\n! git status\n```\n\n```sh\n!  ls\n```'
        self.assertEqual(self.ran('claude', answer, ' ', '\t', ' '), '!git status\nls')
        self.assertEqual(self.ran('shell', answer, ' ', '\t', ' '), 'git status\nls')

    def test_a_bang_inside_a_line_stays(self):
        answer = '```sh\n[ 1 != 2 ] && echo d\n```'
        self.assertEqual(self.ran('claude', answer), '![ 1 != 2 ] && echo d')
        self.assertEqual(self.ran('shell', answer), '[ 1 != 2 ] && echo d')

    def test_a_block_in_a_list_item_runs_without_its_indent(self):
        answer = '1. Run:\n   ```sh\n   !echo T9\n   ```'
        self.assertEqual(self.ran('claude', answer), '!echo T9')

    def test_claude_refuses_code_that_is_not_shell(self):
        answer = '```python\nprint("T10")\n```'
        with self.assertRaises(self.copy.Refused):
            self.ran('claude', answer)
        self.assertEqual(self.ran('shell', answer), 'print("T10")')

    def test_claude_leaves_out_a_block_that_is_not_shell_and_says_so(self):
        answer = '```sh\nls\n```\n\n```python\nprint(1)\n```\n\n```bash\npwd\n```'
        book = self.book(answer)
        state, _ = self.press(book, 'a')
        self.assertEqual(self.copy.prepared('claude', state, book[0]),
                         ('!ls\npwd', '2 blocks for Claude, 1 python block left out'))
        self.assertEqual(self.copy.prepared('shell', state, book[0])[0],
                         'ls\nprint(1)\npwd')

    def test_star_runs_each_shell_block_as_a_step_of_its_own(self):
        answer = ('```sh\n!echo a\necho b\n```\n\n```python\nprint(1)\n```\n\n'
                  '```bash\npwd\n```')
        book = self.book(answer)
        state, done = self.press(book, 'a', '*')
        self.assertEqual(done, 'run')
        self.assertEqual(self.copy.prepared('run', state, book[0]),
                         (['echo a\necho b', 'pwd'],
                          '2 blocks in the free shell, 1 python block left out'))

    def test_a_run_refuses_code_that_is_not_shell(self):
        with self.assertRaisesRegex(self.copy.Refused, '^a shell runs shell code, not python'):
            self.ran('run', '```python\nprint(1)\n```')

    def test_the_prose_stays_out_and_prose_alone_copies_nothing_to_run(self):
        answer = 'Run:\n\n```sh\nls\n```\n\nThen:\n\n```sh\npwd\n```'
        self.assertEqual(self.ran('claude', answer, 'a'), '!ls\npwd')
        with self.assertRaises(self.copy.Refused):
            self.ran('shell', answer, 'k')

    def test_a_command_for_claude_goes_in_its_empty_box_without_an_enter(self):
        """The paste markers keep a newline from sending the first command."""
        agent = {'pane_id': 'w2:p1', 'agent_status': 'idle'}
        with stub_log() as log:
            self.assertIsNone(self.copy.place(agent, '!echo a\necho b'))
            asked = pathlib.Path(log).read_text()
        self.assertIn('pane.send_text w2:p1 \033[200~!echo a\necho b\033[201~', asked)
        self.assertIn('pane.focus w2:p1', asked)
        self.assertNotIn('agent.prompt', asked)

    def test_a_command_for_claude_loses_its_control_characters(self):
        """An end marker in the text would close the paste before its last line."""
        agent = {'pane_id': 'w2:p1', 'agent_status': 'idle'}
        with stub_log() as log:
            self.copy.place(agent, '!cat log\n\033[201~\necho sent\r\n\tdone\x07\x9b')
            asked = pathlib.Path(log).read_text()
        self.assertIn('pane.send_text w2:p1 '
                      '\033[200~!cat log\n[201~\necho sent\n\tdone\033[201~', asked)

    def test_a_box_out_of_sight_takes_no_command(self):
        """The working agent of the fixture shows no screen, so no box."""
        with stub_log() as log:
            why = self.copy.place({'pane_id': 'w1:p1'}, '!ls')
            asked = pathlib.Path(log).read_text()
        self.assertEqual(why, 'the prompt box is not on screen')
        self.assertNotIn('send_text', asked)

    def test_a_run_goes_to_the_free_shell_of_the_tab_without_an_enter(self):
        """The shell shows the blocks that the Enter of the user will run, and
        an end marker in a block cannot close the paste early."""
        agent = {'pane_id': 'w2:p1', 'tab_id': 'w2:t1'}
        with stub_log() as log, contextlib.redirect_stdout(io.StringIO()) as said:
            self.assertEqual(self.copy.launch(agent, ['make\033[201~'], 'the sh block'), 0)
            asked = pathlib.Path(log).read_text()
        run = said.getvalue().strip().rpartition(' start the run in ')[2]
        self.assertTrue(os.path.isfile(os.path.join(run, 'run')), said.getvalue())
        self.assertIn(f"pane.send_text w2:p2 \033[200~sh {shlex.quote(run + '/run')} "
                      "<<'END_OF_STEPS'\n# ---- step 1\nmake[201~\nEND_OF_STEPS\033[201~",
                      asked)
        self.assertNotIn('send_input', asked)
        self.assertIn('pane.focus w2:p2', asked)

    def test_a_run_waits_for_a_shell_at_its_prompt(self):
        """The shell of the first tab is running make."""
        agent = {'pane_id': 'w1:p1', 'tab_id': 'w1:t1'}
        with stub_log() as log, contextlib.redirect_stdout(io.StringIO()) as said:
            self.assertEqual(self.copy.launch(agent, ['ls'], 'the sh block'), 1)
            asked = pathlib.Path(log).read_text()
        self.assertEqual(said.getvalue(),
                         'open a shell in this tab, or wait for its command to end\n')
        self.assertNotIn('send_input', asked)

    def test_the_copy_goes_to_the_terminal_as_an_osc_52_sequence(self):
        """Herdr catches the sequence and writes the clipboard."""
        terminal = io.StringIO()
        self.copy.clip('make -j8\n  ls', terminal)
        self.assertEqual(terminal.getvalue(),
                         '\033]52;c;bWFrZSAtajgKICBscw==\a')


class PromptBox(unittest.TestCase):
    """What the screen of an agent says about the box one types in, and which
    agent a key typed for."""

    def setUp(self):
        import prompting
        self.prompting = importlib.reload(prompting)

    def screen(self, box):
        """A screen with a message already sent above the box, as Claude draws
        it: both carry the same mark, and only the lowest is the box."""
        rule = '\u2500' * 40
        return f'\u276f a message of yours\n\n{rule}\n{box}\n{rule}\n'

    def test_a_box_out_of_sight_is_told_from_an_empty_one(self):
        """A command is pasted only into a box seen, and an empty one."""
        self.assertIsNone(self.prompting.box('\u25cf a call\n  \u23bf its answer\n'))
        self.assertEqual(self.prompting.box(self.screen('\u276f')), '')
        self.assertEqual(self.prompting.box(self.screen('\u276f half a question')),
                         'half a question')

    def test_a_popup_stands_in_the_pane_under_it(self):
        context = {'HERDR_PANE_ID': 'w1:p9',
                   'HERDR_PLUGIN_CONTEXT_JSON': '{"focused_pane_id": "w2:p1"}'}
        with unittest.mock.patch.dict(os.environ, context):
            self.assertEqual(self.prompting.standing(), 'w2:p1')
        with unittest.mock.patch.dict(os.environ, dict(context,
                                      HERDR_PLUGIN_CONTEXT_JSON='not json')):
            self.assertEqual(self.prompting.standing(), 'w1:p9')

    TAB = ({'pane_id': 'p1', 'tab_id': 't', 'agent': 'claude'},
           {'pane_id': 'p2', 'tab_id': 't', 'agent': 'claude'},
           {'pane_id': 'p3', 'tab_id': 't'})

    def test_a_tab_with_two_agents_names_the_one_you_stand_in(self):
        self.assertEqual(self.prompting.target(self.TAB, 'p2')['pane_id'], 'p2')

    def test_a_tab_with_two_agents_names_none_from_a_shell(self):
        """Either could be meant, and a line typed in the other is lost."""
        self.assertIsNone(self.prompting.target(self.TAB, 'p3'))


def enter(text, room):
    """The Enter of the user, in a session with no terminal, so that no step
    takes the terminal of the suite as its input.

    $SHELL names a program that runs nothing, as a pane may inherit the $SHELL
    of another shell: a step runs in the shell of the pane.
    """
    return subprocess.run(text + '\n', shell=True, check=False, cwd=room,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=30, env=dict(os.environ, SHELL='/bin/false'),
                          start_new_session=True)


class Running(unittest.TestCase):
    """Which shell a run goes to, what it types there, and what it records.

    The waiter of a run is a program that does nothing, and the class Waking
    runs the real one.
    """

    def setUp(self):
        self.room = tempfile.mkdtemp(prefix='herdr-run-')
        self.addCleanup(shutil.rmtree, self.room)
        patch = unittest.mock.patch.dict(os.environ, {'XDG_STATE_HOME': self.room})
        patch.start()
        self.addCleanup(patch.stop)
        import running
        self.running = running
        waiter = unittest.mock.patch.object(running, 'WAITER', ('true',))
        waiter.start()
        self.addCleanup(waiter.stop)

    def free(self, *shells, standing=None, tab='w3:t1'):
        """The free shell among these panes, in a tab beside the agent w3:p1.

        In the world, bash in w3:p2 and zsh in w3:p7 are at their prompt.
        w3:p5 is at its prompt too, with a line that the user is typing, and
        w3:p8 runs fish. w3:p3 runs cargo, w3:p4 a shell in a container, and
        w3:p6 a panel.
        """
        agent = {'pane_id': 'w3:p1', 'tab_id': 'w3:t1', 'agent': 'claude'}
        panes = [agent, *({'pane_id': shell, 'tab_id': tab} for shell in shells)]
        return self.running.free_shell(panes, agent, standing)[0]['pane_id']

    def test_a_shell_is_free_when_it_has_the_terminal_back(self):
        """A server that reports no process gives no free shell."""
        at = self.running.at_prompt
        self.assertTrue(at({'shell_pid': 7, 'foreground_process_group_id': 7}))
        self.assertFalse(at({'shell_pid': 7, 'foreground_process_group_id': 9}))
        self.assertFalse(at({}))

    def test_the_run_goes_to_the_shell_at_its_prompt(self):
        self.assertEqual(self.free('w3:p2', 'w3:p3', 'w3:p4', 'w3:p6'), 'w3:p2')

    def test_a_busy_shell_a_container_and_a_panel_take_no_run(self):
        with self.assertRaisesRegex(self.running.NoRun, '^open a shell in this tab'):
            self.free('w3:p3', 'w3:p4', 'w3:p6')

    def test_a_free_shell_of_another_tab_takes_no_run(self):
        with self.assertRaisesRegex(self.running.NoRun, '^open a shell in this tab'):
            self.free('w3:p2', tab='w3:t2')

    def test_of_two_free_shells_the_run_takes_the_one_you_stand_in_else_the_first(self):
        self.assertEqual(self.free('w3:p2', 'w3:p7'), 'w3:p2')
        self.assertEqual(self.free('w3:p2', 'w3:p7', standing='w3:p7'), 'w3:p7')

    def test_a_shell_with_a_line_typed_takes_no_run(self):
        with self.assertRaisesRegex(self.running.NoRun,
                                    '^clear the line of the free shell first'):
            self.free('w3:p5')

    def test_a_shell_that_reads_no_heredoc_takes_no_run(self):
        with self.assertRaisesRegex(self.running.NoRun,
                                    '^open bash or zsh in this tab: .* which fish '):
            self.free('w3:p8')

    def test_a_line_is_empty_when_it_ends_on_a_prompt(self):
        for screen in ('out\nuser@host:~/w$ \n\n', 'host% ', '❯ ', 'root@host:/# '):
            self.assertTrue(self.running.empty_line(screen), screen)
        for screen in ('user@host:~/w$ ls -la', ''):
            self.assertFalse(self.running.empty_line(screen), screen)

    def test_a_block_with_a_line_that_would_cut_the_run_is_refused(self):
        for block in ('make\nEND_OF_STEPS', '# ---- step 9\nls'):
            with self.subTest(block), self.assertRaisesRegex(self.running.NoRun,
                                                             r'^copy this block with \$'):
                self.running.check([block])
        self.running.check(['echo END_OF_STEPS', '  # ---- step'])

    def test_the_shell_gets_the_script_and_the_blocks_with_no_enter(self):
        with unittest.mock.patch.dict(os.environ, {'HOME': '/home/u'}):
            text = self.running.typed('/home/u/.local/state/herdr-claude-copy/runs/d-3',
                                      ['echo a', 'ls\npwd'])
        self.assertEqual(text, "sh ~/.local/state/herdr-claude-copy/runs/d-3/run "
                               "<<'END_OF_STEPS'\n# ---- step 1\necho a\n"
                               "# ---- step 2\nls\npwd\nEND_OF_STEPS")

    def test_a_run_starts_as_a_script_in_a_directory_of_its_own(self):
        """The directory of the runs and of the locks may come from a umask
        that lets the group in."""
        mine = os.path.join(self.room, 'herdr-claude-copy')
        os.mkdir(mine)
        os.chmod(mine, 0o775)
        run = self.running.prepare({'pane_id': 'w3:p1'}, {'pane_id': 'w3:p2'}, 'sh',
                                   day='2026-10-27')
        self.assertEqual(run, os.path.join(self.room, 'herdr-claude-copy', 'runs',
                                           '2026-10-27-1'))
        self.assertEqual(os.listdir(run), ['run'])
        for mine in (run, os.path.dirname(os.path.dirname(run))):
            self.assertEqual(os.stat(mine).st_mode & 0o777, 0o700, mine)

    def test_a_run_never_writes_through_a_link_planted_at_its_path(self):
        root = os.path.join(self.room, 'herdr-claude-copy', 'runs')
        os.makedirs(root)
        elsewhere = os.path.join(self.room, 'elsewhere')
        os.mkdir(elsewhere)
        os.symlink(elsewhere, os.path.join(root, '2026-10-27-1'))
        run = self.running.prepare({'pane_id': 'w3:p1'}, {'pane_id': 'w3:p2'}, 'sh',
                                   day='2026-10-27')
        self.assertEqual(os.path.basename(run), '2026-10-27-2')
        self.assertEqual(os.listdir(elsewhere), [])

    def enter(self, text):
        return enter(text, self.room)

    def test_a_shell_missing_from_the_path_starts_no_run(self):
        run = self.running.prepare({'pane_id': 'w3:p1'}, {'pane_id': 'w3:p2'}, 'nosuchsh')
        out = self.enter(self.running.typed(run, ['ls']))
        self.assertEqual(out.returncode, 1)
        self.assertIn('add nosuchsh to the PATH', out.stderr)
        self.assertEqual(os.listdir(run), ['run'])

    def start(self, *blocks, edit=lambda text: text):
        """A run of these blocks, typed, edited by the user and started: its
        directory, the text typed, and its job file."""
        run = self.running.prepare({'pane_id': 'w3:p1'}, {'pane_id': 'w3:p2'}, 'sh')
        text = self.running.typed(run, list(blocks))
        out = self.enter(edit(text))
        self.assertEqual(out.returncode, 0, out.stderr)
        return run, text, pathlib.Path(run, 'job').read_text().splitlines()

    @unittest.skipUnless(shutil.which('script'), 'no script')
    def test_each_step_keeps_its_terminal_and_a_failure_stops_nothing(self):
        """A status other than 0 is often the answer that the step was for."""
        run, _, job = self.start('echo "in $STEP_DIR"; exit 3', 'echo two')
        self.assertEqual(job, ['agent w3:p1', 'shell w3:p2', 'step 1', 'step 2',
                               '=== START 1', '=== END 1 rc=3', '=== START 2',
                               '=== END 2 rc=0', '=== DONE'])
        self.assertIn(f'in {run}/1', pathlib.Path(run, '1', 'tty.log').read_text())
        self.assertIn('two', pathlib.Path(run, '2', 'tty.log').read_text())
        self.assertEqual(sorted(os.listdir(run)), ['1', '1.sh', '2', '2.sh', 'job', 'run'])
        self.assertEqual(os.listdir(os.path.join(run, '1')), ['tty.log'])

    @unittest.skipUnless(shutil.which('script'), 'no script')
    def test_ctrl_c_stops_the_whole_run(self):
        """The shell of a step that Ctrl+C stops dies of SIGINT."""
        run, _, job = self.start('kill -INT $$', 'echo never')
        self.assertEqual(job[4:], ['=== START 1', '=== END 1 rc=130', '=== DONE'])
        self.assertFalse(os.path.exists(os.path.join(run, '2', 'tty.log')))

    @unittest.skipUnless(shutil.which('script'), 'no script')
    def test_the_same_run_typed_again_runs_nothing(self):
        """The history of the shell keeps the text of a run."""
        run, text, job = self.start('echo once')
        again = self.enter(text)
        self.assertEqual(again.returncode, 1)
        self.assertIn('press * in the picker for a new one', again.stderr)
        self.assertEqual(pathlib.Path(run, 'job').read_text().splitlines(), job)

    @unittest.skipUnless(shutil.which('script'), 'no script')
    def test_the_run_takes_the_blocks_as_the_user_left_them(self):
        """A mark of a step that the user took out joins two blocks into one step."""
        run, _, _ = self.start('echo one', 'echo two',
                               edit=lambda text: text.replace('# ---- step 2\n', ''))
        self.assertEqual(pathlib.Path(run, '1.sh').read_text(), 'echo one\necho two\n')
        self.assertFalse(os.path.exists(os.path.join(run, '2.sh')))

    @unittest.skipUnless(shutil.which('script'), 'no script')
    def test_the_waiter_starts_once_the_head_is_written_and_before_the_first_step(self):
        """The waiter reads the agent and the steps in the head, and must be
        there when a step closes the shell."""
        record = ('import shutil, sys; '
                  'shutil.copy(sys.argv[1] + "/job", sys.argv[1] + "/job-at-wait"); '
                  'open(sys.argv[1] + "/pid", "w").write(sys.argv[2])')
        with unittest.mock.patch.object(self.running, 'WAITER',
                                        (sys.executable, '-c', record)):
            run, _, job = self.start('echo one', 'echo two')
        self.assertEqual(pathlib.Path(run, 'job-at-wait').read_text().splitlines(), job[:4])
        self.assertTrue(pathlib.Path(run, 'pid').read_text().isdigit())

    @unittest.skipUnless(shutil.which('script'), 'no script')
    def test_the_end_of_a_run_says_how_to_cancel_its_wake(self):
        run = self.running.prepare({'pane_id': 'w3:p1'}, {'pane_id': 'w3:p2'}, 'sh')
        out = self.enter(self.running.typed(run, ['echo one']))
        self.assertEqual(out.stdout.splitlines()[-1],
                         f'Claude hears of this run once its prompt box is free. '
                         f'To cancel, run: touch {run}/no-wake')

    @unittest.skipUnless(shutil.which('script'), 'no script')
    def test_a_waiter_that_cannot_start_stops_no_step(self):
        with unittest.mock.patch.object(self.running, 'WAITER', ('false',)):
            run = self.running.prepare({'pane_id': 'w3:p1'}, {'pane_id': 'w3:p2'}, 'sh')
        out = self.enter(self.running.typed(run, ['echo one']))
        self.assertIn('Claude will not hear of this run when it ends', out.stderr)
        self.assertNotIn('no-wake', out.stdout)
        self.assertEqual(pathlib.Path(run, 'job').read_text().splitlines()[-1], '=== DONE')


class Waking(unittest.TestCase):
    """The end of a run wakes the agent that the run names.

    The world gives w2:p1, an idle agent with an empty box on screen, and
    w2:p2, the shell of its tab.
    """

    FULL = ('=== START 1', '=== END 1 rc=2', '=== START 2', '=== END 2 rc=0', '=== DONE')

    def setUp(self):
        self.room = tempfile.mkdtemp(prefix='herdr-wake-')
        self.addCleanup(shutil.rmtree, self.room)
        self.runs = os.path.join(self.room, 'herdr-claude-copy', 'runs')
        os.makedirs(self.runs)
        import waking
        self.waking = waking
        world = sys.modules['server'].WORLD
        self.agent = next(p for p in world['panes'] if p['pane_id'] == 'w2:p1')
        self.screens = world['screens']
        # a prompt sets the agent to work in the world that every test reads
        for patch in (unittest.mock.patch.dict(os.environ, {'XDG_STATE_HOME': self.room}),
                      unittest.mock.patch.multiple(waking, TICK=0.01, HOLD=0.01, STARTED=0.05,
                                                   GIVE_UP=0.05),
                      unittest.mock.patch.dict(self.agent)):
            patch.start()
            self.addCleanup(patch.stop)

    def job(self, *marks, agent='w2:p1', n=1, steps=2):
        """A run of the agent and its job file, as running.py states it."""
        run = os.path.join(self.runs, f'2026-10-28-{n}')
        os.makedirs(run, exist_ok=True)
        head = f'agent {agent}\nshell w2:p2\n' + ''.join(f'step {step}\n'
                                                         for step in range(1, steps + 1))
        pathlib.Path(run, 'job').write_text(head + ''.join(f'{mark}\n' for mark in marks))
        return run

    @staticmethod
    def prompts(log):
        asked = pathlib.Path(log).read_text() if os.path.exists(log) else ''
        return [line for line in asked.splitlines() if line.startswith('agent.prompt')]

    def deliver(self, run, cut=False, ended=None, screen=None, **pane):
        """One wait for the box, with the agent w2:p1 changed by pane and its
        screen: how the wait ended, and the prompts sent."""
        screens = {} if screen is None else {'w2:p1': screen}
        with unittest.mock.patch.dict(self.agent, pane), \
                unittest.mock.patch.dict(self.screens, screens), stub_log() as log:
            said = self.waking.deliver(run, self.waking.job(run), cut,
                                       time.time() if ended is None else ended)
            return said, self.prompts(log)

    def test_the_wake_tells_how_each_step_ended_and_where_its_files_are(self):
        run = self.job(*self.FULL)
        said, prompts = self.deliver(run)
        self.assertEqual(said, 'woke w2:p1')
        self.assertEqual(prompts, [(
            f'agent.prompt w2:p1 The user ran blocks of your answer in a shell of this '
            f'tab, as run 2026-10-28-1, and the run is over. Step 1 ended with rc=2, '
            f'step 2 with rc=0. The files of step N are in {run}/N: the log of its tool '
            f'if there is one, then tty.log, its terminal output with the header of '
            f'script and color codes. Read them, then go on with the task.')])

    def test_a_run_is_over_after_its_last_step_or_a_ctrl_c(self):
        """The run writes DONE right after a Ctrl+C, and a read may fall
        between the two lines."""
        def over(*marks):
            return self.waking.over(self.waking.job(self.job(*marks)))
        self.assertTrue(over(*self.FULL))
        self.assertTrue(over('=== START 1', '=== END 1 rc=0', '=== START 2', '=== END 2 rc=1'))
        self.assertTrue(over('=== START 1', '=== END 1 rc=130'))
        self.assertFalse(over('=== START 1', '=== END 1 rc=2', '=== START 2'))

    def test_a_mark_half_written_is_read_once_whole(self):
        run = self.job('=== START 1')
        with open(os.path.join(run, 'job'), 'a') as fp:
            fp.write('=== END 1 rc=')
        self.assertEqual(self.waking.job(run)['ends'], [])

    def test_a_ctrl_c_is_told_as_the_end_of_the_run(self):
        _, prompts = self.deliver(self.job('=== START 1', '=== END 1 rc=130', '=== DONE'))
        self.assertIn('and the run is over. Step 1 ended with rc=130, a Ctrl+C, and the run '
                      'stopped there. The files', prompts[0])

    def test_a_run_whose_process_ended_before_its_end_was_cut(self):
        """The shell closed, and took the run with it."""
        run = self.job('=== START 1', '=== END 1 rc=0', '=== START 2')
        gone = subprocess.Popen(['true'])
        gone.wait()
        self.assertTrue(self.waking.end(run, gone.pid, '1')[1])
        _, prompts = self.deliver(run, cut=True)
        self.assertIn('Step 1 ended with rc=0, and the shell closed during step 2. The files',
                      prompts[0])

    def test_a_pid_that_another_process_took_is_a_run_that_ended(self):
        """A process that began at another tick is not the run."""
        run = self.job('=== START 1')
        self.assertIsNotNone(self.waking.born(os.getpid()))
        self.assertTrue(self.waking.end(run, os.getpid(), 'another tick')[1])
        self.assertFalse(self.waking.end(self.job(*self.FULL), os.getpid(), 'another tick')[1])

    def test_an_agent_at_work_or_on_a_dialog_gets_the_wake_after(self):
        """A line typed during a turn waits behind it, and one typed under a
        dialog answers it."""
        run = self.job(*self.FULL)
        for status in ('working', 'blocked'):
            with self.subTest(status=status):
                said, prompts = self.deliver(run, agent_status=status)
                self.assertEqual(prompts, [])
                self.assertTrue(said.endswith(f': the agent is {status}'), said)
        self.assertEqual(len(self.deliver(run)[1]), 1)

    def test_a_box_out_of_sight_or_holding_a_line_waits(self):
        run = self.job(*self.FULL)
        for screen, why in (('  scrolled up, far from the box\n', 'is not on screen'),
                            ('❯ half a sentence\n', 'holds a line')):
            with self.subTest(screen=screen):
                said, prompts = self.deliver(run, screen=screen)
                self.assertEqual(prompts, [])
                self.assertTrue(said.endswith(why), said)

    def test_a_run_whose_agent_is_gone_wakes_nobody(self):
        """The idle agent of the same tab is not the one the run names."""
        for agent in ('w2:p9', 'w2:p2'):
            with self.subTest(agent=agent):
                said, prompts = self.deliver(self.job(*self.FULL, agent=agent))
                self.assertEqual((said, prompts), (f'{agent} holds no agent, no wake', []))

    def test_a_server_that_does_not_answer_is_waited_for(self):
        """An empty pane list would read as every agent gone."""
        with unittest.mock.patch.object(self.waking.api, 'panes', return_value=[]):
            said, prompts = self.deliver(self.job(*self.FULL))
        self.assertEqual(prompts, [])
        self.assertTrue(said.endswith(': the server did not answer'), said)

    def test_a_no_wake_file_cancels_the_wake(self):
        run = self.job(*self.FULL)
        pathlib.Path(run, 'no-wake').touch()
        self.assertEqual(self.deliver(run), ('no-wake found, no wake', []))

    def test_the_wait_ends_a_day_after_the_end_of_the_run(self):
        with unittest.mock.patch.object(self.waking, 'GIVE_UP', 24 * 3600):
            said, prompts = self.deliver(self.job(*self.FULL), ended=time.time() - 24 * 3600)
        self.assertEqual((said, prompts), ('no wake 24 hours after the end of the run', []))

    def test_a_run_of_no_step_wakes_nobody(self):
        said, prompts = self.deliver(self.job('=== DONE', steps=0))
        self.assertEqual((said, prompts), ('the run has no step, and nothing to tell', []))

    def test_a_refused_prompt_is_tried_again(self):
        """A dialog may open between the look at the box and the prompt, and
        api.call answers agent_blocked as it answers a lost reply."""
        errors = sys.modules['server'].ERRORS
        with unittest.mock.patch.dict(errors, {'agent.prompt': 'agent_blocked'}):
            said, prompts = self.deliver(self.job(*self.FULL))
        self.assertGreater(len(prompts), 1)
        self.assertTrue(said.endswith(': the prompt was refused, or its reply lost'), said)

    def test_two_runs_of_one_agent_wake_it_in_two_turns(self):
        """The first wake starts a turn, and a second one typed then would
        wait behind it."""
        first, second = self.job(*self.FULL), self.job(*self.FULL, n=2)
        with unittest.mock.patch.dict(self.agent), stub_log() as log:
            self.assertEqual(self.waking.deliver(first, self.waking.job(first), False,
                                                 time.time()), 'woke w2:p1')
            said = self.waking.deliver(second, self.waking.job(second), False, time.time())
            self.assertTrue(said.endswith(': the agent is working'), said)
            prompts = self.prompts(log)
        self.assertEqual(len(prompts), 1)
        _, prompts = self.deliver(second)
        self.assertIn('as run 2026-10-28-2,', prompts[0])

    def test_a_wake_waits_while_another_one_holds_the_agent(self):
        """The lock is held from the look at the box until the turn shows."""
        run = self.job(*self.FULL)
        held = self.waking.lock(run, 'w2:p1')
        try:
            said, prompts = self.deliver(run)
        finally:
            os.close(held)
        self.assertEqual(prompts, [])
        self.assertTrue(said.endswith(': another wake of this agent was on its way'), said)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.runs))),
                         ['runs', 'wake-w2:p1.lock'])

    def wait_for(self, run):
        """What the waiter of the run wrote, once it ended."""
        log = pathlib.Path(run, 'wake.log')
        deadline = time.time() + 20
        while time.time() < deadline:
            said = log.read_text() if log.exists() else ''
            if said.endswith('\n'):
                return said
            time.sleep(0.1)
        self.fail(f'the waiter of {run} wrote nothing')

    @unittest.skipUnless(shutil.which('script'), 'no script')
    def test_a_run_wakes_its_agent_once_over(self):
        """The run starts the real waiter, which outlives it."""
        import running
        with stub_log() as log:
            run = running.prepare(self.agent, {'pane_id': 'w2:p2'}, 'sh')
            out = enter(running.typed(run, ['exit 3', 'echo two']), self.room)
            said = self.wait_for(run)
            prompts = self.prompts(log)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(said.endswith(' woke w2:p1\n'), said)
        self.assertEqual(len(prompts), 1)
        self.assertIn('Step 1 ended with rc=3, step 2 with rc=0. The files', prompts[0])

    def test_the_waiter_outlives_a_shell_that_closes(self):
        """A pane that closes kills what its shell runs: the run, and not the
        waiter, which tells the agent."""
        run = self.job('=== START 1')
        with stub_log() as log:
            shell = subprocess.Popen(
                ['sh', '-c', '"$0" "$1" "$2" "$$" && exec sleep 60',
                 sys.executable, os.path.join(BIN, 'waking.py'), run],
                start_new_session=True)
            # the waiter has left once the shell has become the sleep
            deadline = time.time() + 10
            while not pathlib.Path(f'/proc/{shell.pid}/cmdline').read_bytes() \
                    .startswith(b'sleep') and time.time() < deadline:
                time.sleep(0.05)
            os.killpg(shell.pid, signal.SIGKILL)
            shell.wait()
            said = self.wait_for(run)
            prompts = self.prompts(log)
        self.assertTrue(said.endswith(' woke w2:p1\n'), said)
        self.assertIn('and the run is over. The shell closed during step 1. The files',
                      prompts[0])


class Resolution(unittest.TestCase):
    """Which payload a pane takes, when the identity Herdr holds has drifted."""

    def setUp(self):
        self.room = tempfile.mkdtemp(prefix='herdr-resolve-')
        self.addCleanup(shutil.rmtree, self.room)
        import sessions
        self.store = importlib.reload(sessions)
        self.published = []

    def publish(self, sid, name, *records, age=60, written=None):
        """A payload of that age, and the transcript that it names.

        Freshness is what the rule turns on. The transcript stays older than
        its payload, unless written gives its own age.
        """
        transcript = os.path.join(self.room, f'{sid}.jsonl')
        write_transcript(transcript, [*records, {'type': 'user'}])
        now = time.time()
        when = now - (age + 10 if written is None else written)
        os.utime(transcript, (when, when))
        self.published.append((now - age, {'session_id': sid, 'session_name': name,
                                           'transcript_path': transcript}))
        self.published.sort(key=lambda pair: pair[0], reverse=True)

    def resolve(self, *panes):
        return self.store.resolve_all(list(panes), self.published)

    def test_the_payload_is_read_where_the_hook_writes_it(self):
        """A hook that honours XDG_STATE_HOME writes its payloads there."""
        self.addCleanup(importlib.reload, self.store)
        with unittest.mock.patch.dict(os.environ, {'XDG_STATE_HOME': '/xdg/state'}):
            os.environ.pop('CLAUDE_TMUX_STATE', None)
            self.assertEqual(importlib.reload(self.store).STATE,
                             '/xdg/state/claude-tmux')

    def test_two_panes_in_one_directory_take_two_sessions(self):
        self.publish('one', 'A named session')
        self.publish('two', 'Its neighbour in the same folder', age=120)
        got = self.resolve(
            {'pane_id': 'a', 'cwd': '/w', 'terminal_title_stripped': 'A named session'},
            {'pane_id': 'b', 'cwd': '/w',
             'terminal_title_stripped': 'Its neighbour in the same folder'})
        self.assertEqual(got['a']['session_id'], 'one')
        self.assertEqual(got['b']['session_id'], 'two')

    def test_a_resumed_session_takes_the_newest_of_its_name(self):
        """Herdr keeps the identity from before the resume; the title does not."""
        self.publish('before', 'A named session', age=3600)
        self.publish('after', 'A named session')
        got = self.resolve({'pane_id': 'a', 'terminal_title_stripped': 'A named session',
                            'agent_session': {'value': 'before'}})
        self.assertEqual(got['a']['session_id'], 'after')

    def test_a_renamed_session_is_found_by_its_new_name(self):
        """The payload keeps the old name until Claude redraws its status line,
        and another session may still carry that old name."""
        self.publish('renamed', 'deploy', titled('deploy the fix'), written=0)
        self.publish('other', 'deploy', titled('deploy'), age=120, written=130)
        got = self.resolve(
            {'pane_id': 'work', 'terminal_title_stripped': 'deploy'},
            {'pane_id': 'home', 'terminal_title_stripped': 'deploy the fix',
             'agent_session': {'value': 'stale'}})
        self.assertEqual(got['home']['session_id'], 'renamed')
        self.assertEqual(got['work']['session_id'], 'other')

    def test_without_a_title_the_identity_decides(self):
        self.publish('one', 'A named session')
        got = self.resolve({'pane_id': 'a', 'terminal_title_stripped': 'claude',
                            'agent_session': {'value': 'one'}})
        self.assertEqual(got['a']['session_id'], 'one')

    def test_a_session_nobody_named_answers_to_the_name_claude_code_gave(self):
        """A name that the user gave wins over the one that Claude Code gave."""
        self.publish('unnamed', '', {'type': 'ai-title', 'aiTitle': 'Fix the build'},
                     written=0)
        self.publish('named', 'release notes', titled('release notes'),
                     {'type': 'ai-title', 'aiTitle': 'Write the notes'}, written=0)
        got = self.resolve(
            {'pane_id': 'a', 'terminal_title_stripped': 'Fix the build'},
            {'pane_id': 'b', 'terminal_title_stripped': 'Write the notes'})
        self.assertEqual(got['a']['session_id'], 'unnamed')
        self.assertNotIn('b', got)


class Finding(unittest.TestCase):
    """Which transcript the copy picker reads, when it may not guess."""

    def setUp(self):
        self.room = tempfile.mkdtemp(prefix='herdr-find-')
        self.addCleanup(shutil.rmtree, self.room)
        self.root = os.path.join(self.room, 'claude', 'projects')
        self.state = os.path.join(self.room, 'state')
        os.makedirs(self.state)
        import sessions
        self.addCleanup(importlib.reload, sessions)
        patch = unittest.mock.patch.dict(os.environ, {
            'CLAUDE_CONFIG_DIR': os.path.join(self.room, 'claude'),
            'CLAUDE_TMUX_STATE': self.state,
            'XDG_CONFIG_HOME': os.path.join(self.room, 'config')})
        patch.start()
        self.addCleanup(patch.stop)
        self.store = importlib.reload(sessions)

    def transcript(self, sid, *names, root=None, folder='-w-app', age=0):
        path = os.path.join(root or self.root, folder, f'{sid}.jsonl')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_transcript(path, [*names, user('q'), claude('m1', text(f'from {sid}'))])
        when = time.time() - age
        os.utime(path, (when, when))
        return os.path.realpath(path)

    def payload(self, sid, name, transcript_path):
        with open(os.path.join(self.state, f'{sid}.raw.json'), 'w') as fp:
            json.dump({'session_id': sid, 'session_name': name, 'cwd': '/w/app',
                       'transcript_path': transcript_path}, fp)

    def find(self, title, sid=None, cwd='/w/app'):
        pane = {'pane_id': 'p', 'cwd': cwd, 'terminal_title_stripped': title,
                'agent_session': {'value': sid} if sid else None}
        return self.store.find(pane, [pane])

    def test_with_no_payload_the_identity_finds_the_transcript(self):
        """/cd moves a session to the project of its new cwd."""
        found = self.transcript(ONE, titled('build'), folder='-w-lib')
        self.assertEqual(self.find('claude', ONE), found)

    def test_with_no_payload_the_title_finds_the_transcript(self):
        """devcontainer exec starts Claude at the top of the workspace."""
        self.transcript(ONE, titled('build'))
        found = self.transcript(TWO, titled('release'), age=60)
        self.assertEqual(self.find('release', cwd='/w/app/src'), found)

    def test_a_stale_identity_gives_way_to_the_title(self):
        self.transcript(ONE, titled('old work'))
        found = self.transcript(TWO, titled('new work'), age=60)
        self.assertEqual(self.find('new work', ONE), found)

    def test_a_title_that_names_no_session_gives_way_to_the_identity(self):
        """With CLAUDE_CODE_DISABLE_TERMINAL_TITLE, the shell sets the title."""
        found = self.transcript(ONE, titled('build'))
        self.transcript(TWO, titled('release'), age=60)
        self.assertEqual(self.find('user@host: ~/w/app', ONE), found)

    def test_a_session_never_renamed_is_found_by_its_ai_title(self):
        found = self.transcript(ONE, {'type': 'ai-title', 'aiTitle': 'Fix the build'}, age=60)
        self.transcript(TWO, titled('other'), {'type': 'ai-title', 'aiTitle': 'Fix the build'})
        self.assertEqual(self.find('Fix the build'), found)

    def test_a_transient_title_with_no_identity_is_refused(self):
        self.transcript(ONE, titled('build'))
        with self.assertRaisesRegex(self.store.NoTranscript, '^name this session with /rename'):
            self.find('claude')

    def test_a_forged_transcript_path_is_not_followed(self):
        """The finder keeps the project and the file, and joins them to its root."""
        forged = self.transcript(ONE, titled('build'), root=os.path.join(self.room, 'forged'))
        self.payload(ONE, 'build', forged)
        found = self.transcript(ONE, titled('build'), age=3 * 86400)
        self.assertEqual(self.find('build'), found)

    def test_a_link_out_of_the_root_is_refused(self):
        secret = os.path.join(self.room, 'secret')
        write_transcript(secret, [titled('build'), user('q'), claude('m1', text('secret'))])
        link = os.path.join(self.root, '-w-app', f'{ONE}.jsonl')
        os.makedirs(os.path.dirname(link))
        os.symlink(secret, link)
        self.payload(ONE, 'build', link)
        with self.assertRaisesRegex(self.store.NoTranscript,
                                    f'^check {re.escape(link)}: it resolves outside'):
            self.find('build')

    def test_a_stem_that_is_not_the_session_id_is_refused(self):
        self.transcript('build-1', titled('build'))
        self.payload('build-1', 'build', os.path.join(self.root, '-w-app', 'build-1.jsonl'))
        self.transcript(TWO, titled('other'))
        self.payload(ONE, 'deploy', os.path.join(self.root, '-w-app', f'{TWO}.jsonl'))
        for title in ('build', 'deploy'):
            with self.subTest(title), \
                    self.assertRaisesRegex(self.store.NoTranscript, '^add the projects directory'):
                self.find(title)

    def test_an_old_transcript_of_the_project_is_not_taken(self):
        """A host session that once ran in the workspace of a container pane."""
        self.transcript(ONE, titled('build'), age=2 * 86400)
        self.transcript(TWO, titled('other'))
        with self.assertRaisesRegex(self.store.NoTranscript, 'no transcript carries its name'):
            self.find('build')

    def test_of_two_roots_the_newest_write_wins(self):
        container = os.path.join(self.room, 'dc', 'projects')
        os.makedirs(os.path.join(self.room, 'config', 'herdr-claude-copy'))
        with open(self.store.sources_file(), 'w') as fp:
            fp.write(f'{container}\n')
        self.transcript(ONE, titled('build'), age=300)
        found = self.transcript(TWO, titled('build'), root=container, age=10)
        self.assertEqual(self.find('build'), found)

    def test_the_sources_file_adds_to_the_host_paths(self):
        host = (self.root, self.state)
        self.assertEqual(self.store.sources(), [host])
        os.makedirs(os.path.join(self.room, 'config', 'herdr-claude-copy'))
        with open(self.store.sources_file(), 'w') as fp:
            fp.write('# a devcontainer\n\n'
                     '~/dc/projects   ~/dc/drop  # the bind and the drop\n/x/projects\n')
        self.assertEqual(self.store.sources(), [
            host, (os.path.expanduser('~/dc/projects'), os.path.expanduser('~/dc/drop')),
            ('/x/projects', None)])


class Runs(unittest.TestCase):
    """bin/copy run whole, from a pane of the stub world."""

    def assert_clean(self, out):
        self.assertEqual(out.returncode, 0, f'copy failed: {out.stderr}')
        self.assertNotIn('Traceback', out.stderr, 'copy raised an exception')

    def converse(self, room, *records, title='the build'):
        """The transcript of the agent of w2, under the projects root of the
        room, and the title of its pane."""
        server = sys.modules['server']
        server.TITLES['w2:p1'] = title
        self.addCleanup(server.TITLES.pop, 'w2:p1', None)
        path = os.path.join(room, 'projects', '-home-user-dev-app', f'{ONE}.jsonl')
        os.makedirs(os.path.dirname(path))
        write_transcript(path, [titled(title), *records])
        return path

    def test_the_copy_reads_the_agent_of_the_tab_you_stand_in(self):
        """The key fires from where you stand, and nothing is typed into Claude.
        No hook wrote a payload, so the title finds the transcript."""
        with tempfile.TemporaryDirectory() as room:
            self.converse(room, user('how do I build it?'),
                          claude('m1', text('Run this:\n\n```sh\nmake -j8\n```')))
            with stub_log() as log:
                out = run(HERDR_PANE_ID='w2:p2', CLAUDE_CONFIG_DIR=room)
                asked = pathlib.Path(log).read_text()
        self.assert_clean(out)
        self.assertEqual([row.split()[0] for row in out.stdout.splitlines()],
                         ['paragraph', 'sh'])
        self.assertIn('make -j8', out.stdout)
        self.assertNotIn('send_text', asked)

    def test_the_popup_copies_from_the_pane_under_it(self):
        """A popup has no pane of its own, and the context names the one under it."""
        with tempfile.TemporaryDirectory() as room:
            path = self.converse(room, user('which?'), claude('m1', text('This one.')))
            with open(os.path.join(room, f'{ONE}.raw.json'), 'w') as fp:
                json.dump({'session_id': ONE, 'session_name': 'the build',
                           'cwd': '/home/user/dev/app', 'transcript_path': path}, fp)
            out = run(HERDR_PANE_ID='w1:p2', CLAUDE_CONFIG_DIR=room,
                      CLAUDE_TMUX_STATE=room,
                      HERDR_PLUGIN_CONTEXT_JSON='{"focused_pane_id": "w2:p2"}')
        self.assert_clean(out)
        self.assertIn('This one.', out.stdout)

    def test_a_session_with_no_answer_says_so_in_a_toast(self):
        """The pane closes when the script exits, and takes a printed line with it."""
        with tempfile.TemporaryDirectory() as room:
            self.converse(room, user('anyone?'))
            with stub_log() as log:
                out = run(HERDR_PANE_ID='w2:p2', CLAUDE_CONFIG_DIR=room)
                asked = pathlib.Path(log).read_text()
        self.assertEqual(out.returncode, 1)
        self.assertIn('no answer of Claude', out.stdout)
        self.assertIn('notification.show copy no answer of Claude', asked)

    def test_a_session_with_no_transcript_names_the_sources_file(self):
        with stub_log() as log:
            out = run()
            asked = pathlib.Path(log).read_text()
        self.assertEqual(out.returncode, 1)
        sources = os.path.join(os.environ['XDG_CONFIG_HOME'], 'herdr-claude-copy', 'sources')
        self.assertIn(f'add the projects directory of this session to {sources}', out.stdout)
        self.assertIn('notification.show copy add the projects directory', asked)


if __name__ == '__main__':
    unittest.main(verbosity=2)
