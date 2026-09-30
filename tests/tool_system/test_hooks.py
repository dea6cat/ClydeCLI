from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.hooks import load_hooks, normalize_hooks
from src.tool_system.protocol import ToolCall


def _hook(event: str, matcher: str, command: str) -> dict:
    return {event: [{"matcher": matcher, "hooks": [{"type": "command", "command": command}]}]}


class TestToolHooks(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.registry = build_default_registry()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, hooks: dict) -> tuple[object, Path]:
        target = self.root / "out.txt"
        ctx = ToolContext(workspace_root=self.root, hooks=hooks)
        result = self.registry.dispatch(ToolCall(name="Write", input={"file_path": str(target), "content": "hi"}), ctx)
        return result, target

    def test_pre_hook_exit_2_blocks_the_tool(self) -> None:
        result, target = self._write(_hook("PreToolUse", "Write", "echo 'no writes today' >&2; exit 2"))
        self.assertTrue(result.is_error)
        self.assertEqual(result.output["error"], "no writes today")
        self.assertFalse(target.exists())

    def test_pre_hook_gets_event_json_on_stdin(self) -> None:
        seen = self.root / "seen.json"
        result, target = self._write(_hook("PreToolUse", "Bash|Write", f"cat > {seen}"))
        self.assertFalse(result.is_error)
        self.assertTrue(target.exists())
        event = json.loads(seen.read_text())
        self.assertEqual(event["hook_event_name"], "PreToolUse")
        self.assertEqual(event["tool_name"], "Write")
        self.assertEqual(event["tool_input"]["content"], "hi")

    def test_non_matching_hook_does_not_run(self) -> None:
        result, target = self._write(_hook("PreToolUse", "Bash", "exit 2"))
        self.assertFalse(result.is_error)
        self.assertTrue(target.exists())

    def test_other_exit_codes_do_not_block(self) -> None:
        result, target = self._write(_hook("PreToolUse", "*", "exit 1"))
        self.assertFalse(result.is_error)
        self.assertTrue(target.exists())

    def test_post_hook_exit_2_feeds_stderr_back(self) -> None:
        result, target = self._write(_hook("PostToolUse", "", "echo 'run the formatter' >&2; exit 2"))
        self.assertTrue(target.exists())
        self.assertEqual(result.output["hookFeedback"], "run the formatter")

    def test_load_hooks_tolerates_missing_or_bad_files(self) -> None:
        self.assertEqual(load_hooks((self.root / "missing.json",)), {})
        bad = self.root / "bad.json"
        bad.write_text("{not json")
        self.assertEqual(load_hooks((bad,)), {})

    def test_json_and_toml_settings_merge(self) -> None:
        js = self.root / "settings.json"
        js.write_text(json.dumps({"hooks": _hook("PreToolUse", "Bash", "a")}))
        toml = self.root / "settings.toml"
        toml.write_text('[hooks.PreToolUse]\nWrite = "b"\n')
        hooks = load_hooks((js, toml))
        self.assertEqual([(g["matcher"], g["hooks"][0]["command"]) for g in hooks["PreToolUse"]], [("Bash", "a"), ("Write", "b")])

    def test_shorthand_forms(self) -> None:
        hooks = normalize_hooks({"PreToolUse": {"Bash": ["a", "b"]}, "PostToolUse": ["c"]})
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "Bash")
        self.assertEqual([h["command"] for h in hooks["PreToolUse"][0]["hooks"]], ["a", "b"])
        self.assertEqual((hooks["PostToolUse"][0]["matcher"], hooks["PostToolUse"][0]["hooks"][0]["command"]), ("", "c"))

    def test_gemini_events_and_tool_names(self) -> None:
        hooks = normalize_hooks({"BeforeTool": [{"matcher": "write_file|replace", "hooks": [{"type": "command", "command": "x"}]}]})
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "Write|Edit")

    def test_cursor_events_imply_the_tool(self) -> None:
        hooks = normalize_hooks({"beforeShellExecution": [{"command": "x"}], "afterFileEdit": [{"command": "y"}], "stop": [{"command": "z"}]})
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "Bash")
        self.assertEqual(hooks["PostToolUse"][0]["matcher"], "Write|Edit|NotebookEdit")
        self.assertEqual(set(hooks), {"PreToolUse", "PostToolUse"})

    def test_copilot_flat_entries(self) -> None:
        hooks = normalize_hooks({"preToolUse": [{"type": "command", "bash": "x", "timeoutSec": 5}]})
        self.assertEqual(hooks["PreToolUse"][0]["hooks"][0], {"command": "x", "timeout": 5})

    def test_json_deny_reply_blocks(self) -> None:
        for reply in ('{"permission": "deny", "agentMessage": "nope"}',
                      '{"permissionDecision": "deny", "permissionDecisionReason": "nope"}',
                      '{"decision": "block", "reason": "nope"}'):
            result, target = self._write(normalize_hooks({"preToolUse": [f"echo '{reply}'"]}))
            self.assertEqual(result.output.get("error"), "nope", reply)
            self.assertFalse(target.exists())

    def test_json_allow_reply_continues(self) -> None:
        result, target = self._write(normalize_hooks({"beforeTool": ["""echo '{"decision": "allow"}'"""]}))
        self.assertFalse(result.is_error)
        self.assertTrue(target.exists())

if __name__ == "__main__":
    unittest.main()
