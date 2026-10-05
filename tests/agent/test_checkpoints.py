"""Edit checkpoints and /rewind: files back as they were before a message, and the conversation cut there."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent import checkpoints
from src.agent.checkpoints import Checkpoints
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.protocol import ToolCall


class _Home(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.ws = Path(tempfile.mkdtemp()).resolve()
        patcher = patch.object(Path, "home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestCheckpoints(_Home):
    def test_rewind_restores_edits_and_removes_created_files(self):
        app, new = self.ws / "app.py", self.ws / "new.py"
        app.write_text("v1\n")
        cps = Checkpoints("s1")
        cps.begin("make it v2", 0)
        cps.snapshot(app)
        app.write_text("v2\n")
        cps.snapshot(new)                     # about to be created
        new.write_text("brand new\n")
        cps.snapshot(app)                     # a second edit in the same turn keeps the first snapshot
        app.write_text("v2.1\n")
        restored, problems = cps.restore(1)
        self.assertEqual(app.read_text(), "v1\n")
        self.assertFalse(new.exists())
        self.assertEqual(problems, [])
        self.assertEqual(len(restored), 2)
        self.assertEqual(cps.list(), [])      # the rewound checkpoints are gone

    def test_rewinding_further_back_takes_the_earliest_state(self):
        app = self.ws / "app.py"
        app.write_text("v1\n")
        cps = Checkpoints("s1")
        for n, text in ((0, "v2\n"), (2, "v3\n")):
            cps.begin(f"to {text.strip()}", n)
            cps.snapshot(app)
            app.write_text(text)
        cps.restore(2)
        self.assertEqual(app.read_text(), "v2\n")
        self.assertEqual([c.number for c in cps.list()], [1])
        cps.restore(1)
        self.assertEqual(app.read_text(), "v1\n")

    def test_checkpoints_survive_a_reload_and_big_files_are_reported(self):
        big = self.ws / "big.bin"
        big.write_bytes(b"x" * 20)
        cps = Checkpoints("s1")
        cps.begin("touch the big file", 0)
        with patch.object(checkpoints, "MAX_FILE_BYTES", 10):
            cps.snapshot(big)
        reloaded = Checkpoints("s1").list()
        self.assertEqual(reloaded[0].prompt, "touch the big file")
        _, problems = Checkpoints("s1").restore(1)
        self.assertIn("not saved", problems[0])

    def test_old_sessions_are_pruned(self):
        with patch.object(checkpoints, "KEEP_SESSIONS", 2):
            for sid in ("a", "b", "c"):
                Checkpoints(sid).begin("hi", 0)
        self.assertEqual(len(list(checkpoints.root().iterdir())), 2)


class TestRegistryHook(_Home):
    def test_edits_are_snapshotted_right_before_they_run(self):
        seen: list[Path] = []
        ctx = ToolContext(workspace_root=self.ws)
        ctx.before_edit = seen.append
        target = self.ws / "notes.txt"
        registry = build_default_registry(include_user_tools=False)
        registry.dispatch(ToolCall(name="Write", input={"file_path": "notes.txt", "content": "hi\n"}, tool_use_id="t1"), ctx)
        registry.dispatch(ToolCall(name="Glob", input={"pattern": "*.txt"}, tool_use_id="t2"), ctx)
        self.assertEqual(seen, [target])     # Write, not Glob
        self.assertEqual(target.read_text(), "hi\n")


class TestRewindCommand(_Home):
    def test_rewind_puts_files_conversation_and_prompt_back(self):
        from src.agent import Conversation
        from src.repl import ClydeREPL
        from tests.fakes import reply
        from tests.repl.test_repl import _fake_provider_env

        (self.ws / "app.py").write_text("v1\n")
        conversation = Conversation()
        session = type("S", (), {"conversation": conversation, "session_id": "sess", "provider": "glm",
                                 "model": "glm-4.5", "save": lambda self: None})()
        with patch("src.repl.core.Path.cwd", return_value=self.ws), \
                patch("src.repl.core.Session.create", return_value=session), \
                _fake_provider_env(reply(tool_calls=[("Read", {"file_path": str(self.ws / "app.py")})]),
                                   reply(tool_calls=[("Write", {"file_path": str(self.ws / "app.py"), "content": "v2\n"})]),
                                   reply("done"),
                                   reply(tool_calls=[("Write", {"file_path": str(self.ws / "extra.py"), "content": "x\n"})]),
                                   reply("added")):
            repl = ClydeREPL(model="glm:glm-4.5", headless=True)
            repl.tool_context.permission_handler = lambda *a: (True, False)
            repl.chat("make app v2")
            repl.chat("add extra.py")
            self.assertEqual((self.ws / "app.py").read_text(), "v2\n")
            with patch("src.repl.core.pick", side_effect=["1", "c"]):
                repl._rewind()
        self.assertEqual((self.ws / "app.py").read_text(), "v1\n")
        self.assertFalse((self.ws / "extra.py").exists())
        self.assertEqual(conversation.messages, [])
        self.assertEqual(repl._prefill, "make app v2")


if __name__ == "__main__":
    unittest.main()
