"""The shell sandbox: writes stay in the project, temp and caches; leaving it always asks."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from src.tool_system import sandbox
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.protocol import ToolCall
from src.tool_system.tools.bash import BashTool

REPO = Path(__file__).resolve().parents[2]


class TestProfiles(unittest.TestCase):
    def test_macos_profile_denies_writes_except_the_listed_folders(self):
        profile = sandbox.macos_profile([Path("/w/proj"), Path('/odd "name"')], network=True)
        self.assertIn("(deny file-write*)", profile)
        self.assertIn('(subpath "/w/proj")', profile)
        self.assertIn('(subpath "/odd \\"name\\"")', profile)       # quotes escaped
        self.assertNotIn("network", profile)
        self.assertIn("(deny network*)", sandbox.macos_profile([Path("/w")], network=False))

    def test_bwrap_mounts_root_read_only_and_binds_the_writable_folders(self):
        args = sandbox.bwrap_args([Path("/w/proj")], network=False)
        self.assertEqual(args[:3], ["bwrap", "--ro-bind", "/"])
        self.assertIn("--bind", args)
        self.assertIn("--unshare-net", args)
        self.assertEqual(args[-1], "--")

    def test_settings_can_turn_it_off(self):
        home = Path(tempfile.mkdtemp())
        (home / ".clyde").mkdir()
        (home / ".clyde" / "settings.json").write_text(json.dumps({"sandbox": {"enabled": False}}))
        with patch.object(Path, "home", return_value=home):
            self.assertIsNone(sandbox.engine())
            self.assertEqual(sandbox.wrap(["bash", "-lc", "true"], ToolContext(workspace_root=home)), (["bash", "-lc", "true"], False))


class TestPermissions(unittest.TestCase):
    def test_leaving_the_sandbox_always_asks_even_all_in(self):
        ctx = ToolContext(workspace_root=Path(tempfile.mkdtemp()))
        result = BashTool().check_permissions({"command": "ls", "unsandboxed": True}, ctx)
        self.assertEqual(result.behavior.value, "ask")                 # even a read-only command
        from src.tool_system.registry import _is_major
        spec = BashTool().spec()
        self.assertTrue(_is_major(spec, {"command": "ls", "unsandboxed": True}, ctx))
        self.assertFalse(_is_major(spec, {"command": "ls"}, ctx))


@unittest.skipUnless(sys.platform == "darwin" and sandbox.engine() == "sandbox-exec", "needs macOS sandbox-exec")
class TestRealSandbox(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp()).resolve()
        self.ctx = ToolContext(workspace_root=self.ws)
        self.registry = build_default_registry(include_user_tools=False)
        self.ctx.permission_handler = lambda *a: (True, False)

    def bash(self, command: str, **extra):
        return self.registry.dispatch(ToolCall(name="Bash", input={"command": command, **extra}, tool_use_id="t"), self.ctx)

    def test_writes_inside_the_project_work(self):
        result = self.bash("echo hi > made.txt && cat made.txt")
        self.assertFalse(result.is_error)
        self.assertTrue(result.output["sandboxed"])
        self.assertEqual((self.ws / "made.txt").read_text(), "hi\n")

    def test_writes_outside_the_project_are_blocked_with_a_hint(self):
        target = REPO / f".sandbox-probe-{uuid.uuid4().hex}"    # outside the test's workspace, not temp
        try:
            result = self.bash(f"echo escaped > '{target}'")
            self.assertTrue(result.is_error)
            self.assertFalse(target.exists())
            self.assertIn("unsandboxed: true", result.output["hint"])
        finally:
            target.unlink(missing_ok=True)

    def test_an_approved_unsandboxed_command_can_write_there(self):
        target = REPO / f".sandbox-probe-{uuid.uuid4().hex}"
        try:
            result = self.bash(f"echo allowed > '{target}'", unsandboxed=True)
            self.assertFalse(result.is_error)
            self.assertFalse(result.output["sandboxed"])
            self.assertTrue(target.exists())
        finally:
            target.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
