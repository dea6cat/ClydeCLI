"""Tests for saved permission rules (permissions.allow / permissions.deny in ~/.clyde/settings.json)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path, PurePath
from unittest.mock import patch

from src.tool_system.context import ToolContext
from src.tool_system.permission_rules import check_rules, load_rules, save_allow_rule, suggest_rule
from src.tool_system.protocol import ToolCall
from src.tool_system.registry import ToolRegistry
from src.tool_system.tools.bash import BashTool
from src.tool_system.tools.web_fetch import WebFetchTool
from src.tool_system.tools.web_search import WebSearchTool
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
        self.registry = ToolRegistry([BashTool(), FileWriteTool(), WebFetchTool(), WebSearchTool()])

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

    def _search(self, query: str = "why does my build fail with ERR_SECRET_TOKEN=abc123"):
        from src.tool_system.protocol import ToolResult
        ran = {"n": 0}

        def fake_run(_self, tool_input, context):
            ran["n"] += 1
            return ToolResult(name="WebSearch", output={"results": []})
        with patch.object(WebSearchTool, "run", fake_run):
            result = self.registry.dispatch(ToolCall(name="WebSearch", input={"query": query}), self.ctx)
        return result, ran["n"]

    def test_websearch_asks_with_the_whole_query_and_a_no_sends_nothing(self) -> None:
        self.ctx.permission_handler = lambda *args: (self.asked.append(args), (False, False))[1]
        result, ran = self._search()
        self.assertTrue(result.is_error)
        self.assertEqual(ran, 0)                                   # a no means no search, so nothing reaches DuckDuckGo
        tool, message, rule = self.asked[0]
        self.assertEqual(tool, "WebSearch")
        self.assertIn("DuckDuckGo", message)
        self.assertIn("ERR_SECRET_TOKEN=abc123", message)          # the user sees exactly what would be sent
        self.assertEqual(rule, "WebSearch")                        # what "don't ask again" would save

    def test_websearch_runs_after_a_yes(self) -> None:
        result, ran = self._search()
        self.assertFalse(result.is_error)
        self.assertEqual((len(self.asked), ran), (1, 1))

    def test_a_websearch_allow_rule_skips_the_question_and_a_deny_rule_blocks_it(self) -> None:
        self.rules(allow=["WebSearch"])
        result, ran = self._search()
        self.assertEqual((result.is_error, self.asked, ran), (False, [], 1))
        self.rules(deny=["WebSearch"])
        result, ran = self._search()
        self.assertTrue(result.is_error)
        self.assertIn("deny rule", result.output["error"])
        self.assertEqual((self.asked, ran), ([], 0))

    def test_a_very_long_search_query_is_shown_shortened(self) -> None:
        message = WebSearchTool().check_permissions({"query": "x" * 500}, self.ctx).message
        self.assertIn("200 more characters", message)
        self.assertNotIn("x" * 400, message)
        self.assertEqual(WebSearchTool().check_permissions({"query": "  "}, self.ctx).behavior.value, "allow")   # run() rejects it


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


class TestPathGlobOnEveryPython(unittest.TestCase):
    """PurePath.full_match exists only from Python 3.13; the fallback must give the same answers on 3.12."""

    # (path, pattern, expected), measured with PurePath.full_match on Python 3.13
    KNOWN = [
        ("/w/docs/a.md", "/w/docs/**", True), ("/w/docs", "/w/docs/**", False), ("/w/a/b/c.md", "/w/**/c.md", True),
        ("/w/c.md", "/w/**/c.md", True), ("/w/docs/a.md", "/w/docs/*.md", True), ("/w/docs/x/a.md", "/w/docs/*.md", False),
        ("/w/.env", "/w/*", True), ("/w/a.md", "/w/?.md", True), ("/w/ab.md", "/w/?.md", False), ("/w/a.md", "/w/[ab].md", True),
        ("/w/c.md", "/w/[!ab].md", True), ("/w/a.md", "/w/[!ab].md", False), ("/w/a/b", "/w/a", False), ("/w/a", "/w/a/**", False),
        ("/w/a/b", "/w/**", True), ("/w", "/w/**", False), ("/z", "/**/z", True), ("/w/x/y/z", "/**/z", True), ("A/b", "a/*", False),
        ("/w/a/b/c", "/w/**/b/**", True), ("/w/a/b", "/w/**/b/**", False), ("/w/ab", "/w/a**", True), ("/w/a/b", "/w/a**", False),
        ("/w/a]", "/w/a[]]", True), ("/w/-", "/w/[a-]", True), ("/w/a", "/w/[a-c]", True),
    ]

    def test_the_fallback_gives_the_measured_answers(self):
        from src.tool_system.permission_rules import _glob_regex
        for path, pattern, expected in self.KNOWN:
            self.assertEqual(_glob_regex(pattern).fullmatch(path) is not None, expected, f"{path} ~ {pattern}")

    @unittest.skipUnless(hasattr(PurePath, "full_match"), "needs Python 3.13+ to compare against")
    def test_the_fallback_agrees_with_full_match_on_generated_cases(self):
        import itertools
        from src.tool_system.permission_rules import _glob_regex
        names = ["a", "b", "ab", ".env", "a.md"]
        patterns_pieces = ["a", "b", "*", "**", "?", "[ab]", "[!a]", "*.md", "a**", ".env", "a*", "[a-b]*"]
        paths = ["/" + "/".join(c) for n in (1, 2, 3) for c in itertools.product(names, repeat=n)]
        patterns = ["/" + "/".join(c) for n in (1, 2, 3) for c in itertools.product(patterns_pieces, repeat=n)]
        for pattern in patterns:
            regex = _glob_regex(pattern)
            for path in paths:
                self.assertEqual(regex.fullmatch(path) is not None, PurePath(path).full_match(pattern), f"{path} ~ {pattern}")


if __name__ == "__main__":
    unittest.main()
