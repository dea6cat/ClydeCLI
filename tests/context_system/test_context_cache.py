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

    def test_the_marker_names_the_headings_the_cut_hides_but_not_code_or_shown_ones(self):
        full = "# Rules\nkeep\n\n## Testing\n" + "t\n" * 300 + "```bash\n# not a heading\n```\n## Documentation\ndoc\n# graphify\nrun it\n"
        cut = context_cache.cut(full, 200)
        self.assertLessEqual(len(cut), 200)
        hidden = cut.split("not shown: ", 1)[1].split(";", 1)[0]
        self.assertEqual(hidden, "Documentation, graphify")
        self.assertEqual(context_cache.cut(full, 200), cut)   # still byte-identical turn to turn

    def test_a_long_list_of_hidden_headings_is_capped(self):
        full = "x" * 50 + "".join(f"\n## Part {i}\nbody" for i in range(40))
        self.assertIn("Part 14 (+25 more)", context_cache.marker(full, full[:50]))

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


if __name__ == "__main__":
    unittest.main()
