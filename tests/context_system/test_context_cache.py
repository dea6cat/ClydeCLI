"""Reversible cuts in the context prompt: the full text is kept, referenced, and read back by RetrieveContext."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from src.context_system import build_context_prompt, context_cache
from src.context_system.builder import section_report
from src.context_system.claude_md import load_claude_md_context
from src.tool_system.context import ToolContext
from src.tool_system.tools.context_retrieve import RetrieveContextTool


def _ref(text: str) -> str:
    return text.split('reference="', 1)[1].split('"', 1)[0]


class TestCut(unittest.TestCase):
    def test_text_that_fits_is_untouched(self):
        self.assertEqual(context_cache.cut("short", 100), "short")

    def test_a_cut_stays_in_budget_and_the_full_text_comes_back(self):
        full = "rule\n" * 2_000
        cut = context_cache.cut(full, 500)
        self.assertLessEqual(len(cut), 500)
        self.assertEqual(context_cache.fetch(_ref(cut)), full)
        self.assertEqual(context_cache.cut(full, 500), cut)   # same text, same bytes: the prompt cache keeps hitting

    def test_only_a_well_formed_reference_reads_a_file(self):
        for bad in ("ctx:../../etc/passwd", "ctx:ABCDEF0123456789", "/etc/passwd", "ctx:0123"):
            self.assertIsNone(context_cache.fetch(bad))

    def test_writing_a_new_entry_prunes_expired_ones(self):
        old = context_cache.stash("old text")
        path = context_cache._dir() / f"{old[4:]}.txt"
        stale = time.time() - context_cache.TTL_SECONDS - 60
        os.utime(path, (stale, stale))
        context_cache.stash("new text")
        self.assertIsNone(context_cache.fetch(old))


class TestInstructionFiles(unittest.TestCase):
    def test_a_long_instruction_file_is_cut_with_a_reference_the_tool_reads_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "\n".join(f"- Rule {i}: keep it." for i in range(400))
            (root / "CLAUDE.md").write_text(body, encoding="utf-8")
            files = load_claude_md_context(root, max_chars_per_file=1_000).files
            shown = next(f.content for f in files if f.path.name == "CLAUDE.md")
            result = RetrieveContextTool().run({"reference": _ref(shown)}, ToolContext(workspace_root=root))
        self.assertLessEqual(len(shown), 1_000)
        self.assertNotIn("Rule 399", shown)
        self.assertFalse(result.is_error)
        self.assertEqual(result.output["text"], body)

    def test_an_unknown_reference_is_an_error_that_says_what_to_do(self):
        result = RetrieveContextTool().run({"reference": "ctx:0000000000000000"}, ToolContext(workspace_root=Path.cwd()))
        self.assertTrue(result.is_error)
        self.assertIn("Read the file itself", result.output["error"])


class TestSectionReport(unittest.TestCase):
    def test_a_section_that_changed_ends_the_cached_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "CLAUDE.md").write_text("Always add tests.", encoding="utf-8")
            (root / "notes.txt").write_text("draft\n", encoding="utf-8")
            self.assertEqual(section_report(root), [])
            build_context_prompt(root)
            self.assertTrue(all(s["stable"] is None and not s["aligned"] for s in section_report(root)))

            build_context_prompt(root)
            self.assertTrue(all(s["aligned"] for s in section_report(root)))

            subprocess.run(["git", "-C", str(root), "add", "notes.txt"], check=True)   # only git status changes
            build_context_prompt(root)
            rows = {s["name"]: s for s in section_report(root)}
        self.assertTrue(rows["Runtime Context"]["aligned"])
        self.assertFalse(rows["Git Context"]["stable"])
        self.assertTrue(rows["Project Instructions"]["stable"])
        self.assertFalse(rows["Project Instructions"]["aligned"])   # unchanged, but after the change: prefilled again


class TestToolOutput(unittest.TestCase):
    """Tool output over its max_result_size_chars keeps its head and tail; the whole of it is a RetrieveContext away."""

    def test_clip_keeps_both_ends_within_the_limit(self):
        text = "start\n" + "noise\n" * 20_000 + "FAILED tests/test_x.py::test_y - AssertionError"
        clipped = context_cache.clip(text, 2_000)
        self.assertLessEqual(len(clipped), 2_000)
        self.assertTrue(clipped.startswith("start"))
        self.assertTrue(clipped.endswith("AssertionError"))
        self.assertEqual(context_cache.fetch(_ref(clipped)), text)
        self.assertEqual(context_cache.clip("short", 2_000), "short")

    def test_a_long_failing_bash_run_keeps_the_error_at_its_end(self):
        from src.tool_system.defaults import build_default_registry
        from src.tool_system.protocol import ToolCall
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ToolContext(workspace_root=Path(tmp))
            ctx.permission_handler = lambda *_a: (True, None)   # the user says yes to the command
            command = "for i in $(seq 1 20000); do echo line $i; done; echo 'Error: the real reason' >&2; exit 3"
            result = build_default_registry().dispatch(ToolCall(name="Bash", input={"command": command}, tool_use_id="t"), ctx)
        out = result.output
        self.assertTrue(result.is_error)
        self.assertLessEqual(len(out["stdout"]), 30_000)
        self.assertTrue(out["stdout"].rstrip().endswith("line 20000"))   # the old cap kept only the first 20,000 chars
        self.assertIn("Error: the real reason", out["stderr"])
        whole = RetrieveContextTool().run({"reference": _ref(out["stdout"])}, ctx).output
        self.assertGreater(whole["total_chars"], 30_000)                  # the whole stdout, not the clipped view
        self.assertTrue(whole["text"].startswith("line 1\n"))

    def test_retrieve_pages_through_long_text(self):
        text = "".join(f"{i:08d}\n" for i in range(12_000))   # 108,000 characters
        ref = context_cache.stash(text)
        tool, ctx = RetrieveContextTool(), ToolContext(workspace_root=Path.cwd())
        first = tool.run({"reference": ref}, ctx).output
        second = tool.run({"reference": ref, "offset": first["next_offset"]}, ctx).output
        third = tool.run({"reference": ref, "offset": second["next_offset"]}, ctx).output
        self.assertEqual(first["text"] + second["text"] + third["text"], text)
        self.assertNotIn("next_offset", third)

    def test_encoded_files_are_never_cut(self):
        from src.tool_system.protocol import ToolResult
        from src.tool_system.registry import _clip_result
        image = ToolResult(name="Read", output={"type": "image", "file": {"base64": "A" * 90_000}})
        self.assertIs(_clip_result(image, 1_000), image)


if __name__ == "__main__":
    unittest.main()
