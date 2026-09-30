"""Tests for saved permission rules (permissions.allow / permissions.deny in ~/.clyde/settings.json)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tool_system.context import ToolContext
from src.tool_system.permission_rules import check_rules, load_rules, save_allow_rule, suggest_rule
from src.tool_system.protocol import ToolCall
from src.tool_system.registry import ToolRegistry
from src.tool_system.tools.bash import BashTool
from src.tool_system.tools.web_fetch import WebFetchTool
from src.tool_system.tools.write import FileWriteTool


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.ctx = ToolContext(workspace_root=self.root)
        self.asked: list[tuple[str, str, str | None]] = []
        self.ctx.permission_handler = lambda *args: (self.asked.append(args), (True, False))[1]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def rules(self, allow=(), deny=()) -> None:
        self.ctx.permission_rules = {"allow": list(allow), "deny": list(deny)}

    def bash(self, command: str) -> str | None:
        return check_rules("Bash", {"command": command}, self.ctx)


class TestBashRules(_Case):
    def test_exact_rule_matches_only_that_command(self) -> None:
        self.rules(allow=["Bash(npm test)"])
        self.assertEqual(self.bash("npm test"), "allow")
        self.assertIsNone(self.bash("npm test --watch"))

    def test_prefix_rule_matches_on_word_boundary(self) -> None:
        self.rules(allow=["Bash(git commit:*)"])
        self.assertEqual(self.bash('git commit -m "a b"'), "allow")
        self.assertEqual(self.bash("git commit"), "allow")
        self.assertIsNone(self.bash("git commitx"))
        self.assertIsNone(self.bash("git push"))

    def test_compound_needs_every_part_allowed(self) -> None:
        self.rules(allow=["Bash(npm test:*)"])
        self.assertEqual(self.bash("cd sub && npm test"), "allow")  # cd is read-only
        self.assertIsNone(self.bash("npm test && rm -r build"))
        self.assertIsNone(self.bash("npm test $(rm x)"))

    def test_bare_tool_name_matches_everything(self) -> None:
        self.rules(allow=["Bash"])
        self.assertEqual(self.bash("rm -r build && make"), "allow")

    def test_deny_wins_over_allow_and_catches_any_part(self) -> None:
        self.rules(allow=["Bash"], deny=["Bash(rm:*)"])
        self.assertEqual(self.bash("rm -r build"), "deny")
        self.assertEqual(self.bash("make; rm -r build"), "deny")
        self.assertEqual(self.bash("make"), "allow")

    def test_suggestion_is_command_prefix(self) -> None:
        self.rules()
        self.assertEqual(suggest_rule("Bash", {"command": "npm run test -- --watch"}, self.ctx), "Bash(npm run test:*)")
        self.assertEqual(suggest_rule("Bash", {"command": "git commit -m 'x'"}, self.ctx), "Bash(git commit:*)")
        self.assertEqual(suggest_rule("Bash", {"command": "ls && make build"}, self.ctx), "Bash(make build:*)")
        self.assertIsNone(suggest_rule("Bash", {"command": "make && rm x"}, self.ctx))  # no single rule covers it


class TestPathAndDomainRules(_Case):
    def test_path_glob_relative_to_workspace(self) -> None:
        self.rules(allow=["Edit(docs/**)"])
        self.assertEqual(check_rules("Edit", {"file_path": str(self.root / "docs/a/b.md")}, self.ctx), "allow")
        self.assertIsNone(check_rules("Edit", {"file_path": str(self.root / "README.md")}, self.ctx))
        self.assertIsNone(check_rules("Write", {"file_path": str(self.root / "docs/a.md")}, self.ctx))

    def test_path_suggestion_is_relative_file(self) -> None:
        self.assertEqual(suggest_rule("Write", {"file_path": str(self.root / "docs/a.md")}, self.ctx), "Write(docs/a.md)")

    def test_webfetch_domain(self) -> None:
        self.rules(allow=["WebFetch(domain:example.com)"])
        self.assertEqual(check_rules("WebFetch", {"url": "https://example.com/x"}, self.ctx), "allow")
        self.assertIsNone(check_rules("WebFetch", {"url": "https://evil.com/?example.com"}, self.ctx))
        self.assertEqual(suggest_rule("WebFetch", {"url": "https://docs.python.org/3/"}, self.ctx), "WebFetch(domain:docs.python.org)")


class TestDispatchWithRules(_Case):
    def setUp(self) -> None:
        super().setUp()
        self.registry = ToolRegistry([BashTool(), FileWriteTool(), WebFetchTool()])

    def test_allow_rule_skips_prompt(self) -> None:
        self.rules(allow=["Bash(touch:*)"])
        result = self.registry.dispatch(ToolCall(name="Bash", input={"command": "touch made"}), self.ctx)
        self.assertFalse(result.is_error)
        self.assertEqual(self.asked, [])
        self.assertTrue((self.root / "made").exists())

    def test_deny_rule_blocks_without_asking_even_read_only(self) -> None:
        self.rules(deny=["Bash(ls:*)"])
        result = self.registry.dispatch(ToolCall(name="Bash", input={"command": "ls"}), self.ctx)
        self.assertTrue(result.is_error)
        self.assertIn("deny rule", result.output["error"])
        self.assertEqual(self.asked, [])

    def test_prompt_receives_suggested_rule(self) -> None:
        self.rules()
        self.registry.dispatch(ToolCall(name="Bash", input={"command": "touch made"}), self.ctx)
        self.assertEqual(self.asked[0][2], "Bash(touch made:*)")

    def test_docs_write_allowed_by_rule(self) -> None:
        self.rules(allow=["Write(notes/*.md)"])
        result = self.registry.dispatch(
            ToolCall(name="Write", input={"file_path": str(self.root / "notes/a.md"), "content": "x"}), self.ctx
        )
        self.assertFalse(result.is_error)
        self.assertEqual(self.asked, [])

    def test_webfetch_asks_per_domain(self) -> None:
        self.ctx.permission_handler = lambda *args: (self.asked.append(args), (False, False))[1]
        result = self.registry.dispatch(ToolCall(name="WebFetch", input={"url": "https://example.com/"}), self.ctx)
        self.assertTrue(result.is_error)
        self.assertEqual(self.asked[0][2], "WebFetch(domain:example.com)")


class TestSettingsFile(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        patcher = patch("pathlib.Path.home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.path = self.home / ".clyde" / "settings.json"

    def test_save_keeps_other_keys_and_mode(self) -> None:
        self.path.parent.mkdir()
        self.path.write_text(json.dumps({"hooks": {"PreToolUse": []}, "mcpServers": {"x": {"command": "y"}}}))
        save_allow_rule("Bash(npm test:*)")
        save_allow_rule("Bash(npm test:*)")  # no duplicate
        data = json.loads(self.path.read_text())
        self.assertEqual(data["permissions"]["allow"], ["Bash(npm test:*)"])
        self.assertIn("hooks", data)
        self.assertIn("mcpServers", data)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(load_rules(), {"allow": ["Bash(npm test:*)"], "deny": []})

    def test_load_missing_or_malformed_is_empty(self) -> None:
        self.assertEqual(load_rules(), {"allow": [], "deny": []})
        self.path.parent.mkdir()
        self.path.write_text("{not json")
        self.assertEqual(load_rules(), {"allow": [], "deny": []})
        with self.assertRaises(ValueError):
            save_allow_rule("Bash")


if __name__ == "__main__":
    unittest.main()
