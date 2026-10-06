"""End-to-end flows from replica/test-plan.md: a real `clyde` in a pseudo-terminal, answered by a scripted fake model.

Slow (each test starts a process), so it only runs with CLYDE_E2E=1:

    CLYDE_E2E=1 python -m unittest tests.e2e.test_flows -v

Case IDs (F03-H1 and so on) match replica/test-plan.md.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.e2e.harness import (CTRL_C, CTRL_D, DOWN, ENTER, ESC, SHIFT_TAB, FakeModel, Terminal, call, fail, isolated_env, run_cli, say)

try:
    import prompt_toolkit  # noqa: F401
    HAVE_TERMINAL = True
except ImportError:
    HAVE_TERMINAL = False

ON = os.environ.get("CLYDE_E2E") == "1" and HAVE_TERMINAL
PROMPT = "❯"


def write_call(path: Path, content: str = "hi") -> dict:
    return call("Write", file_path=str(path), content=content)


class Case(unittest.TestCase):
    """A fake model, a project folder, and helpers to start the app in it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="clyde-e2e-proj-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def folder(self, prefix: str) -> Path:
        path = Path(tempfile.mkdtemp(prefix=prefix)).resolve()
        self.addCleanup(shutil.rmtree, path, True)
        return path

    def model(self, *script: dict, **kwargs) -> FakeModel:
        server = FakeModel(list(script), **kwargs)
        self.addCleanup(server.close)
        return server

    def app(self, server, args=None, **kwargs) -> Terminal:
        terminal = Terminal(server, self.tmp, args, **kwargs)
        self.addCleanup(terminal.close)
        terminal.expect(PROMPT, 30)
        return terminal

    def approve(self, terminal: Terminal, answer: str = "y", until: str = "done") -> None:
        """Answer permission prompts with `answer` until `until` shows."""
        for _ in range(20):
            try:
                terminal.expect(until, 2, since_last=True)
                return
            except AssertionError:
                if "Allow?" in terminal.buffer[terminal._seen:]:
                    terminal.send(answer + "\r")
                    terminal._seen = len(terminal.buffer)
        raise AssertionError(f"never reached {until!r}\n{terminal.tail()}")


@unittest.skipUnless(ON, "set CLYDE_E2E=1 (needs prompt_toolkit)")
class TestF01SignIn(Case):
    def login(self, **kwargs) -> Terminal:
        server = self.model()
        terminal = Terminal(server, self.tmp, ["login"], **kwargs)
        self.addCleanup(terminal.close)
        terminal.expect("Connect a provider", 30)
        return terminal

    def test_F01_H1_login_saves_the_default_model(self):
        t = self.login()
        t.send("fake")                       # type to filter the provider list
        t.expect("Filter: fake")
        t.send(ENTER)
        t.expect("API key")
        t.send_line("sk-test-key")
        t.expect("Select fake model", 20)
        t.send(ENTER)
        t.expect("fake connected", 20)
        saved = json.loads((t.home / ".clyde" / "config.json").read_text())
        self.assertEqual(saved["model"], "fake:m")
        self.assertEqual(json.loads((t.home / ".clyde" / "keys.json").read_text())["fake"], "sk-test-key")

    def test_F01_E1_esc_at_the_provider_picker_saves_nothing(self):
        t = self.login()
        t.send(ESC)
        self.assertIsNotNone(t.wait_exit(8), t.tail())
        self.assertFalse((t.home / ".clyde" / "config.json").exists())

    def test_F01_E2_the_picker_works_in_a_narrow_terminal(self):
        t = self.login(cols=40)
        t.expect("Esc to cancel")
        t.send("fake")
        t.send(ENTER)
        t.expect("API key", 15)

    def test_F01_N1_an_empty_key_is_refused_for_a_built_in_provider_and_nothing_is_saved(self):
        t = self.login()
        t.send("openai")
        t.expect("Filter: openai")
        t.send(ENTER)
        t.expect("API key")
        t.send(ENTER)
        t.expect("cannot be empty", 10)
        self.assertFalse((t.home / ".clyde" / "config.json").exists())

    def test_F01_E3_a_custom_provider_may_have_no_key(self):
        # By design: a keyless local server (vLLM and the like) still connects.
        t = self.login()
        t.send("fake")
        t.expect("Filter: fake")
        t.send(ENTER)
        t.expect("empty if it needs none")
        t.send(ENTER)
        t.expect("Select fake model", 20)

    def test_F01_N2_no_provider_at_all_says_what_to_do(self):
        with Terminal(None, self.tmp, []) as t:
            t.expect("No provider available", 30)
            self.assertNotIn("Traceback", t.tail(3000))

    def test_F01_N3_a_rejected_key_opens_the_fix_it_menu(self):
        server = self.model(fail(401, "invalid api key"))
        t = self.app(server)
        t.send_line("hello")
        t.expect("authentication failed", 30)
        t.expect("Fix it now?", 15)
        t.send(ESC)
        t.expect("clyde login", 15)
        t.ready()


@unittest.skipUnless(ON, "set CLYDE_E2E=1 (needs prompt_toolkit)")
class TestF02Ask(Case):
    def test_F02_H1_a_reply_comes_with_a_footer_and_the_model_in_the_corner(self):
        t = self.app(self.model(say("The answer is 42")))
        t.send_line("what is the answer")
        t.expect("The answer is 42", 30)
        t.expect("100 in, 10 out", 10)
        self.assertRegex(t.tail(400), r"♠ hold.*fake:m")

    def test_F02_H2_only_core_tools_and_the_index_are_sent(self):
        server = self.model(say("ok"))
        t = self.app(server)
        t.send_line("hi")
        t.expect("ok", 30)
        names = server.tool_names()
        self.assertLessEqual(len(names), 20)
        self.assertIn("Bash", names)
        self.assertNotIn("Sleep", names)
        self.assertIn("## More tools", server.system_prompt())

    def test_F02_E1_an_empty_enter_sends_nothing(self):
        server = self.model(say("never"))
        t = self.app(server)
        t.send(ENTER)
        t.send(ENTER)
        t.absent("never", 2)
        self.assertEqual(len(server.requests), 0)

    def test_F02_E2_emoji_and_accents_arrive_unchanged(self):
        server = self.model(say("ok"))
        t = self.app(server)
        t.send_line("héllo wörld 🎉 日本語")
        t.expect("ok", 30)
        self.assertIn("héllo wörld 🎉 日本語", server.user_texts()[-1])

    def test_F02_E3_a_very_long_paste_is_sent_whole(self):
        server = self.model(say("ok"))
        t = self.app(server)
        long = "word " * 4000
        t.paste(long)
        t.send(ENTER)
        t.expect("ok", 60)
        self.assertIn(long.strip(), server.user_texts()[-1])

    def test_F02_E7_a_paste_inside_typed_text_is_expanded_before_it_is_sent(self):
        # Typed words, a multi-line paste (shown as a [Pasted text] marker), then a closing quote typed after it.
        server = self.model(say("ok"))
        t = self.app(server)
        poem = "\n".join(f"line {i} of the poem" for i in range(18))
        t.send('make this rhyme "')
        t.paste(poem)
        t.send('"')
        t.expect("[Pasted text #1", 10)                    # the prompt shows a marker, not 18 lines
        t.send(ENTER)
        t.turn_done()
        sent = server.user_texts()[-1]
        self.assertEqual(sent, f'make this rhyme "{poem}"')
        self.assertNotIn("[Pasted", sent)

    def test_F02_E8_two_pastes_in_one_message_are_both_expanded_in_order(self):
        server = self.model(say("ok"))
        t = self.app(server)
        first, second = "\n".join(f"a{i}" for i in range(6)), "\n".join(f"b{i}" for i in range(6))
        t.send("compare ")
        t.paste(first)
        t.send(" with ")
        t.paste(second)
        t.expect("[Pasted text #2", 10)
        t.send(ENTER)
        t.turn_done()
        self.assertEqual(server.user_texts()[-1], f"compare {first} with {second}")

    def test_F02_E4_ctrl_c_at_the_idle_prompt_does_not_quit(self):
        t = self.app(self.model(say("still here")))
        t.send(CTRL_C)
        t.expect("Interrupted", 10)
        t.send_line("hello")
        t.expect("still here", 30)

    def test_F02_E5_ctrl_d_quits_cleanly(self):
        t = self.app(self.model())
        t.send(CTRL_D)
        self.assertEqual(t.wait_exit(10), 0, t.tail())

    def test_F02_E6_two_messages_back_to_back_are_answered_in_order(self):
        server = self.model(say("first answer"), say("second answer"))
        t = self.app(server)
        t.send("one\r")
        t.send("two\r")
        t.expect("second answer", 40)
        self.assertEqual(len(server.requests), 2)
        self.assertIn("one", server.user_texts(0)[-1])
        self.assertIn("two", server.user_texts(1)[-1])

    def test_F02_N1_a_server_error_shows_a_line_and_the_app_keeps_working(self):
        server = self.model(fail(500, "boom"), fail(500, "boom"), fail(500, "boom"), fail(500, "boom"), say("recovered"))
        t = self.app(server)
        t.send_line("hello")
        t.expect("❌", 60)
        t.ready()
        t.send_line("again")
        t.expect("recovered", 30)

    def test_F02_N2_a_provider_that_is_down_shows_a_line_and_the_app_keeps_working(self):
        server = self.model()
        t = self.app(server)
        server.close()
        t.send_line("hello")
        t.expect("❌", 60)
        t.ready()

    def test_F02_N3_rate_limits_are_named(self):
        server = self.model(*[fail(429, "slow down")] * 4)
        t = self.app(server)
        t.send_line("hello")
        t.expect("rate limited", 90)


@unittest.skipUnless(ON, "set CLYDE_E2E=1 (needs prompt_toolkit)")
class TestF03Approvals(Case):
    """In hold mode Clyde asks before every file change (and before shell commands and settings changes)."""

    def test_F03_H1_a_doc_write_asks_and_y_writes_the_file(self):
        target = self.tmp / "a.md"
        t = self.app(self.model(write_call(target), say("done")))
        t.send_line("make a doc")
        t.expect("Allow?", 30)
        self.assertFalse(target.exists())                 # nothing happens before the answer
        t.send("y\r")
        t.expect("done", 30)
        self.assertEqual(target.read_text(), "hi")

    def test_F03_N1_n_leaves_no_file_and_tells_the_model(self):
        target = self.tmp / "a.md"
        server = self.model(write_call(target), say("done"))
        t = self.app(server)
        t.send_line("make a doc")
        t.expect("Allow?", 30)
        t.send("n\r")
        t.expect("done", 30)
        self.assertFalse(target.exists())
        results = [m for m in server.requests[1]["messages"] if m["role"] == "tool"]
        self.assertTrue(results and "denied" in results[0]["content"].lower(), results)

    def test_F03_E1_always_saves_a_rule_for_that_file_so_it_is_not_asked_again(self):
        a, b = self.tmp / "a.md", self.tmp / "b.md"
        t = self.app(self.model(write_call(a), write_call(a, "again"), write_call(b), say("done")))
        t.send_line("make docs")
        t.expect("Allow?", 30)
        t.send("a\r")
        t.expect("Saved allow rule Write(a.md)", 15)       # the rule is for that file
        self.approve(t, "y")                                # a different file (b.md) asks again
        self.assertTrue(a.exists() and b.exists())
        self.assertEqual(t.buffer.count("Allow?"), 2, t.buffer[-2500:])    # a.md twice without a second ask, then b.md

    def test_F03_E2_edit_on_a_file_that_was_never_read_is_refused(self):
        target = self.tmp / "keep.txt"
        target.write_text("original")
        t = self.app(self.model(call("Edit", file_path=str(target), old_string="original", new_string="changed"), say("done")))
        t.send_line("edit it")
        self.approve(t, "y")
        self.assertEqual(target.read_text(), "original")

    def test_F03_E3_a_write_outside_the_project_is_never_performed(self):
        target = self.folder("clyde-e2e-other-") / "x.txt"
        t = self.app(self.model(write_call(target), say("done")))
        t.send_line("write elsewhere")
        self.approve(t, "n")
        self.assertFalse(target.exists())

    def test_F03_E4_reading_a_dotenv_file_asks(self):
        secret = self.tmp / ".env"
        secret.write_text("TOKEN=abc")
        t = self.app(self.model(call("Read", file_path=str(secret)), say("done")))
        t.send_line("read the env file")
        t.expect("Allow?", 30)
        t.send("n\r")
        t.expect("done", 30)

    def test_F03_E5_ctrl_c_at_the_permission_prompt_writes_nothing_and_the_app_survives(self):
        # Ctrl+C there has two valid outcomes, depending on timing: the turn is aborted, or it counts as a denial and
        # the turn goes on. Either way nothing is written, the follow-up reaches the model, and no tool call is left
        # without a result (a real provider rejects a conversation that has one).
        target = self.tmp / "a.md"
        server = self.model(write_call(target), say("done"), say("alive"), say("alive"))
        t = self.app(server)
        t.send_line("make a doc")
        t.expect("Allow?", 30)
        t.send(CTRL_C)
        # Aborted ("Interrupted") or denied and carried on (the turn footer): wait for whichever happens, so the
        # follow-up is typed at an idle prompt and not into a turn that is still running.
        t.expect(r"Interrupted|\d+ in, \d+ out", 30, regex=True, since_last=True)
        t.ready(30)
        self.assertFalse(target.exists())
        t.send_line("still there?")
        for _ in range(150):
            if any(server.user_texts(i)[-1] == "still there?" for i in range(len(server.requests))):
                break
            t._pump(0.2)
        followed = [i for i in range(len(server.requests)) if server.user_texts(i)[-1] == "still there?"]
        self.assertTrue(followed, [server.user_texts(i)[-1] for i in range(len(server.requests))])
        messages = server.requests[followed[0]]["messages"]
        for at, message in enumerate(messages):
            if message["role"] == "assistant" and message.get("tool_calls"):
                self.assertEqual(messages[at + 1]["role"], "tool", messages)    # every tool call has its result
        self.assertFalse(target.exists())

    def test_F03_E6_a_code_file_asks_too_and_reading_does_not(self):
        target = self.tmp / "a.py"
        (self.tmp / "notes.txt").write_text("plain")
        t = self.app(self.model(call("Read", file_path=str(self.tmp / "notes.txt")), write_call(target, "x = 1"), say("done")))
        t.send_line("read then write a script")
        t.expect("Allow?", 30)                      # the first (and only) question is for the write, not the read
        self.assertFalse(target.exists())
        t.send("y\r")
        t.expect("done", 30)
        self.assertEqual(t.buffer.count("Allow?"), 1)
        self.assertEqual(target.read_text(), "x = 1")


@unittest.skipUnless(ON, "set CLYDE_E2E=1 (needs prompt_toolkit)")
class TestF04Plan(Case):
    def test_F04_H1_plan_mode_refuses_edits(self):
        target = self.tmp / "a.py"
        t = self.app(self.model(write_call(target), say("done")))
        t.send(SHIFT_TAB)
        t.expect("reading the table", 10)
        t.send_line("make a file")
        self.approve(t, "y")
        self.assertFalse(target.exists())

    def test_F04_H2_exit_plan_mode_returns_to_normal(self):
        t = self.app(self.model(call("ExitPlanMode", plan="1. do the thing"), say("done")))
        t.send(SHIFT_TAB)
        t.expect("reading the table", 10)
        t.send_line("plan it")
        self.approve(t, "y")
        t.ready()

    def test_F04_E1_shift_tab_cycles_through_all_three_modes_and_back_to_hold(self):
        # The status line is redrawn cell by cell, so the modes are checked by what they do to a doc write:
        # hold asks, plan refuses without asking, all in writes without asking.
        target = self.tmp / "d.md"
        t = self.app(self.model(write_call(target), say("one"), write_call(target, "two"), say("two"),
                                write_call(self.tmp / "e.md"), say("three")))
        t.send(SHIFT_TAB)
        t.expect("reading the table", 10)
        t.send_line("go")
        t.turn_done()
        self.assertFalse(target.exists())
        self.assertNotIn("Allow?", t.buffer)               # plan mode refuses; it does not ask
        t.send(SHIFT_TAB)
        t.expect("all in", 10)
        t.send_line("go")
        t.turn_done()
        self.assertEqual(target.read_text(), "two")
        self.assertNotIn("Allow?", t.buffer)               # all in writes without asking
        t.send(SHIFT_TAB)                                  # back to hold
        t.ready()
        t.send_line("go")
        t.expect("Allow?", 30, since_last=True)            # hold asks again
        t.send("n\r")


@unittest.skipUnless(ON, "set CLYDE_E2E=1 (needs prompt_toolkit)")
class TestF05Sessions(Case):
    def first_session(self, home: Path) -> None:
        server = self.model(say("noted: blue"))
        with Terminal(server, self.tmp, home=home) as t:
            t.expect(PROMPT, 30)
            t.send_line("remember the colour blue")
            t.expect("noted: blue", 30)
            t.expect("♠", 10, since_last=True)
            t.send_line("/exit")
            t.wait_exit(10)

    def test_F05_H1_continue_resumes_the_latest_session_with_a_recap(self):
        home = self.folder("clyde-e2e-home-")
        self.first_session(home)
        server = self.model(say("it was blue"))
        with Terminal(server, self.tmp, ["--model", "fake:m", "-c"], home=home) as t:
            t.expect("Resumed session", 30)
            t.expect("remember the colour blue", 10)
            t.send_line("what colour?")
            t.expect("it was blue", 30)
            self.assertIn("remember the colour blue", " ".join(json.dumps(m) for m in server.requests[0]["messages"]))

    def test_F05_H2_resume_lists_sessions_and_loads_one(self):
        home = self.folder("clyde-e2e-home-")
        self.first_session(home)
        with Terminal(self.model(), self.tmp, home=home) as t:
            t.expect(PROMPT, 30)
            t.send_line("/resume")
            t.expect("Resume a session", 15)
            t.expect("remember the colour blue", 5)
            t.send(ENTER)
            t.expect("Resumed session", 15)

    def test_F05_N1_continue_with_no_sessions_is_a_message_not_a_crash(self):
        with Terminal(self.model(), self.tmp, ["--model", "fake:m", "-c"]) as t:
            t.expect(PROMPT, 30)
            self.assertNotIn("Traceback", t.tail(3000))

    def test_F05_N2_resuming_a_made_up_id_is_a_clear_error(self):
        with Terminal(self.model(), self.tmp, ["--model", "fake:m", "--resume", "nonsense"]) as t:
            t.expect("nonsense", 30)
            self.assertNotIn("Traceback", t.tail(3000))

    def test_F05_E1_a_session_from_another_folder_is_not_offered(self):
        home = self.folder("clyde-e2e-home-")
        self.first_session(home)
        with Terminal(self.model(), self.folder("clyde-e2e-elsewhere-"), home=home) as t:
            t.expect(PROMPT, 30)
            t.send_line("/resume")
            t.expect("No saved sessions", 15)


@unittest.skipUnless(ON, "set CLYDE_E2E=1 (needs prompt_toolkit)")
class TestF06Rewind(Case):
    def test_F06_H1_rewinding_files_removes_what_a_write_created(self):
        target = self.tmp / "a.txt"
        t = self.app(self.model(write_call(target), say("done")))
        t.send_line("make a file")
        self.approve(t, "y")
        t.turn_done()
        self.assertTrue(target.exists())
        t.send_line("/rewind")
        t.expect("Rewind to before which message?", 15)
        t.send(ENTER)
        t.expect("Rewind what?", 15)
        t.send(DOWN)                                   # "Code and conversation" first, then "Files only"
        t.send(ENTER)
        for _ in range(30):
            if not target.exists():
                break
            t._pump(0.2)
        self.assertFalse(target.exists(), t.tail())
    def test_F06_E1_nothing_to_rewind_says_so(self):
        t = self.app(self.model())
        t.send_line("/rewind")
        t.expect("Nothing to rewind", 15)

    def test_F06_E2_esc_in_the_rewind_picker_changes_nothing(self):
        target = self.tmp / "a.txt"
        t = self.app(self.model(write_call(target), say("done")))
        t.send_line("make a file")
        self.approve(t, "y")
        t.turn_done()
        t.send_line("/rewind")
        t.expect("Rewind to before which message?", 15)
        t.send(ESC)
        t.expect("Nothing rewound", 15)
        self.assertTrue(target.exists())


@unittest.skipUnless(ON, "set CLYDE_E2E=1 (needs prompt_toolkit)")
class TestF07Context(Case):
    def test_F07_H1_context_prints_a_usage_report(self):
        t = self.app(self.model(say("hello")))
        t.send_line("hi")
        t.expect("hello", 30)
        t.send_line("/context")
        t.expect("Context Usage", 20)
        t.expect("Tokens:", 5)
        self.assertNotIn("Traceback", t.tail(3000))

    def test_F07_H2_compact_after_a_short_chat_does_not_crash(self):
        t = self.app(self.model(say("hello"), say("summary of the chat")))
        t.send_line("hi")
        t.expect("hello", 30)
        t.send_line("/compact")
        t.ready()
        self.assertNotIn("Traceback", t.tail(3000))

    def test_F07_E1_compact_on_an_empty_session_says_so(self):
        t = self.app(self.model())
        t.send_line("/compact")
        t.ready()
        self.assertNotIn("Traceback", t.tail(3000))


@unittest.skipUnless(ON, "set CLYDE_E2E=1 (needs prompt_toolkit)")
class TestF08Mcp(Case):
    def test_F08_N1_a_server_that_cannot_start_does_not_stop_the_app(self):
        settings = {"mcpServers": {"broken": {"command": "/nonexistent/mcp-server", "args": []}}}
        t = self.app(self.model(say("fine")), settings=settings)
        t.send_line("hi")
        t.expect("fine", 30)
        self.assertNotIn("Traceback", t.buffer)


@unittest.skipUnless(ON, "set CLYDE_E2E=1 (needs prompt_toolkit)")
class TestF09Extend(Case):
    def skill(self, name: str, text: str) -> None:
        folder = self.tmp / ".clyde" / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(text)

    def test_F09_H1_skills_shows_block_descriptions_in_full_and_enter_runs_one(self):
        self.skill("hello", "---\nname: hello\ndescription: >\n  Greets the user warmly and asks what they\n  need help with today.\n---\nUNIQUE-SKILL-BODY say hello\n")
        server = self.model(say("greeted"))
        t = self.app(server)
        t.send_line("/skills")
        t.expect("Run a skill", 15)
        t.expect("Greets the user warmly and asks what they need help with today.", 5)
        t._pump(0.5)
        t.send(ENTER)
        t.turn_done()
        self.assertIn("UNIQUE-SKILL-BODY", json.dumps(server.requests[0]["messages"]))

    def test_F09_E2_a_skill_typed_by_name_alone_runs_it(self):
        self.skill("hello", "---\nname: hello\ndescription: Greets.\n---\nUNIQUE-SKILL-BODY say hello\n")
        server = self.model(say("greeted"))
        t = self.app(server)
        t.send_line("/hello")
        t.turn_done()
        self.assertIn("UNIQUE-SKILL-BODY", json.dumps(server.requests[0]["messages"]))

    def test_F09_E3_cost_typed_alone_runs_and_does_not_list_matches(self):
        t = self.app(self.model())
        t.send_line("/cost")
        t.ready()
        self.assertNotIn("Available commands and skills", t.buffer)
    def test_F09_H2_a_pretooluse_hook_that_exits_2_blocks_the_write(self):
        target = self.tmp / "a.txt"
        hook = {"hooks": {"PreToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "echo blocked-by-hook >&2; exit 2"}]}]}}
        server = self.model(write_call(target), say("done"))
        t = self.app(server, settings=hook)
        t.send_line("make a file")
        self.approve(t, "y")
        self.assertFalse(target.exists())
        self.assertIn("blocked-by-hook", json.dumps(server.requests[1]["messages"]))

    def test_F09_E1_a_skill_with_broken_frontmatter_does_not_break_the_list(self):
        self.skill("broken", "---\nname: [unclosed\ndescription: >\n---\nbody\n")
        self.skill("fine", "---\nname: fine\ndescription: A fine skill.\n---\nbody\n")
        t = self.app(self.model())
        t.send_line("/skills")
        t.expect("Run a skill", 15)
        t.expect("fine", 5)
        self.assertNotIn("Traceback", t.tail(3000))


@unittest.skipUnless(ON, "set CLYDE_E2E=1 (needs prompt_toolkit)")
class TestF10Delegate(Case):
    def test_F10_H1_a_sub_agent_runs_and_its_answer_returns(self):
        server = self.model(call("Agent", description="look it up", prompt="find the answer"), say("sub-agent says 7"), say("the sub-agent said 7"))
        t = self.app(server)
        t.send_line("delegate this")
        self.approve(t, "y", until="the sub-agent said 7")
        self.assertEqual(len(server.requests), 3)
        self.assertIn("find the answer", json.dumps(server.requests[1]["messages"]))
        self.assertIn("sub-agent says 7", json.dumps(server.requests[2]["messages"]))


@unittest.skipUnless(ON, "set CLYDE_E2E=1 (needs prompt_toolkit)")
class TestF11Headless(Case):
    def test_F11_H1_print_mode_prints_the_answer(self):
        code, out, _ = run_cli(self.model(say("plain answer")), self.tmp, ["--model", "fake:m", "-p", "hi"])
        self.assertEqual(code, 0)
        self.assertIn("plain answer", out)

    def test_F11_H2_json_output_has_the_documented_fields(self):
        code, out, _ = run_cli(self.model(say("json answer")), self.tmp, ["--model", "fake:m", "-p", "hi", "--output-format", "json"])
        data = json.loads(out[out.index("{"):])
        self.assertEqual((code, data["result"], data["model"], data["is_error"]), (0, "json answer", "fake:m", False))
        self.assertTrue({"usage", "num_turns", "session_id"} <= set(data))

    def test_F11_H3_piped_input_is_added_to_the_prompt(self):
        server = self.model(say("seen"))
        run_cli(server, self.tmp, ["--model", "fake:m", "-p", "summarise"], stdin="THE PIPED TEXT")
        self.assertIn("THE PIPED TEXT", server.user_texts()[-1])
        self.assertIn("summarise", server.user_texts()[-1])

    def test_F11_N1_hold_mode_denies_a_write_and_reports_it(self):
        target = self.tmp / "a.py"
        code, out, _ = run_cli(self.model(write_call(target), say("could not")), self.tmp,
                               ["--model", "fake:m", "-p", "write it", "--output-format", "json"])
        data = json.loads(out[out.index("{"):])
        self.assertFalse(target.exists())
        self.assertTrue(data["denied"], data)
    def test_F11_N2_max_turns_ends_a_tool_loop(self):
        target = self.tmp / "r.txt"
        target.write_text("x")
        read = call("Read", file_path=str(target))
        code, out, _ = run_cli(self.model(read, read, read), self.tmp, ["--model", "fake:m", "-p", "loop", "--max-turns", "1", "--output-format", "json"])
        data = json.loads(out[out.index("{"):])
        self.assertIn("Max tool turns", data["result"] + str(data.get("error")))

    def test_F11_N3_a_provider_that_is_down_is_a_nonzero_exit(self):
        server = self.model()
        server.close()
        code, out, err = run_cli(server, self.tmp, ["--model", "fake:m", "-p", "hi", "--output-format", "json"])
        data = json.loads(out[out.index("{"):])
        self.assertTrue(data["is_error"])
        self.assertNotEqual(code, 0)

    def test_F11_E1_all_in_writes_inside_the_project_without_asking(self):
        target = self.tmp / "a.txt"
        run_cli(self.model(write_call(target), say("written")), self.tmp, ["--model", "fake:m", "-p", "write it", "--mode", "all_in"])
        self.assertEqual(target.read_text(), "hi")


@unittest.skipUnless(ON, "set CLYDE_E2E=1 (needs prompt_toolkit)")
class TestF12Model(Case):
    def shuffled(self, server, *, cols: int = 120) -> Terminal:
        """The app on cardShuffle:house, with the fake model recorded as having passed /eval so it can be dealt."""
        home = Path(tempfile.mkdtemp(prefix="clyde-e2e-home-"))
        self.addCleanup(shutil.rmtree, home, True)
        env = isolated_env(server, home)
        (home / ".clyde" / "model_evals.json").write_text(json.dumps({
            "fake:m": {"passed": True, "kind": "ok", "strength": 4, "hand": 4, "note": "", "at": "2026-10-06T00:00:00+00:00",
                       "tokens_per_s": 50.0}}))
        terminal = Terminal(server, self.tmp, ["--model", "cardShuffle:house"], home=home, env=env, cols=cols)
        self.addCleanup(terminal.close)
        terminal.expect(PROMPT, 40)
        return terminal

    def test_F12_E4_cardshuffle_deals_a_model_and_the_corner_follows_it(self):
        server = self.model(say("from the dealt model"))
        t = self.shuffled(server)
        t.send_line("hi")
        t.expect("dealt fake:m", 30)                        # the deal line
        t.turn_done()
        self.assertEqual(server.requests[0]["model"], "m")
        self.assertIn("cardShuffle:house → fake:m", t.tail(600))

    def test_F12_E5_a_narrow_terminal_keeps_the_dealt_model_readable(self):
        server = self.model(say("ok"))
        t = self.shuffled(server, cols=60)
        t.send_line("hi")
        t.turn_done()
        corner = re.sub(r"\[\?\d+[hl]|zq\d+qz", "", t.tail(600).splitlines()[-1])    # stray mode codes, the ready() probe
        self.assertTrue(corner.rstrip().endswith("fake:m"), corner)      # the end of the line, which names the model
        self.assertLessEqual(len(corner.rstrip()), 60)
    def test_F12_H1_the_model_picker_switches_and_the_next_request_uses_it(self):
        server = self.model(say("on m2"))
        t = self.app(server)
        t.send_line("/model")
        t.expect("Select model", 15)
        t.expect("fake:m2", 5)
        t._pump(0.5)
        t.send(DOWN)
        t._pump(0.5)
        t.send(ENTER)
        t.expect("Model: fake:m2", 15)
        t.ready()
        t.send_line("hi")
        t.turn_done()
        self.assertEqual(server.requests[0]["model"], "m2")             # the status-line corner is checked in F02-H1
    def test_F12_H2_typing_filters_the_picker(self):
        t = self.app(self.model())
        t.send_line("/model")
        t.expect("Select model", 15)
        t.send("m2")
        t.send(ENTER)
        t.expect("Model: fake:m2", 15)

    def test_F12_H3_terse_changes_the_system_prompt_and_off_restores_it(self):
        server = self.model(say("a"), say("b"))
        t = self.app(server)
        t.send_line("/terse on")
        t.expect("Terse replies: on", 10)
        t.ready()
        t.send_line("hi")
        t.turn_done()
        t.send_line("/terse off")
        t.expect("Terse replies: off", 10)
        t.ready()
        t.send_line("hi again")
        t.turn_done()
        self.assertIn("as few words as accuracy allows", server.system_prompt(0))
        self.assertNotIn("as few words as accuracy allows", server.system_prompt(1))
    def test_F12_E1_esc_in_the_picker_keeps_the_model(self):
        server = self.model(say("still m"))
        t = self.app(server)
        t.send_line("/model")
        t.expect("Select model", 15)
        t.send(ESC)
        t.ready()
        t.send_line("hi")
        t.expect("still m", 30)
        self.assertEqual(server.requests[0]["model"], "m")

    def test_F12_E2_a_model_the_provider_does_not_list_is_called_out(self):
        t = self.app(self.model())
        t.send_line("/model fake:nope")
        t.expect("isn't in fake's model list", 15)
    def test_F12_E3_models_all_and_refresh_do_not_crash(self):
        t = self.app(self.model())
        for command in ("/models all", "/models refresh"):
            t.send_line(command)
            t.expect("Select model", 15, since_last=True)
            t.send(ESC)
            t.ready()
        self.assertNotIn("Traceback", t.tail(3000))


if __name__ == "__main__":
    unittest.main()
