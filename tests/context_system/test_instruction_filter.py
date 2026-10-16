from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.context_system import instruction_filter as f
from src.context_system.claude_md import load_claude_md_context
from src.providers.base import ProviderError

TEXT = "# Mine\nintro\n\n## Dart rules\nuse fvm\n\n## Testing\narrange act assert\n"
LABELS = {"## Dart rules": "dart", "## Testing": "general"}


def _label(section: str) -> str:
    return LABELS[section.splitlines()[0]]


class _Reply:
    def __init__(self, text):
        self.message = type("M", (), {"text": text})()


class SplitTests(unittest.TestCase):
    def test_a_heading_inside_a_code_fence_does_not_split(self):
        pieces = f.split_sections("pre\n## A\n```\n## not a heading\n```\n## B\nx\n")
        self.assertEqual(len(pieces), 3)
        self.assertIn("## not a heading", pieces[1])


class ProjectLanguageTests(unittest.TestCase):
    def test_manifests_in_the_root_and_one_folder_down_name_the_languages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("")
            (root / "app").mkdir()
            (root / "app" / "pubspec.yaml").write_text("")
            self.assertEqual(f.project_languages(root), {"python", "dart", "flutter"})

    def test_a_folder_without_manifests_has_no_languages(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(f.project_languages(Path(tmp)), frozenset())


class KeepRelevantTests(unittest.TestCase):
    def test_a_section_about_another_language_goes_and_a_note_says_so(self):
        out = f.keep_relevant(TEXT, frozenset({"python"}), _label)
        self.assertIn("intro", out)
        self.assertIn("## Testing", out)
        self.assertNotIn("fvm", out)
        self.assertIn("Left out 1 section about other languages", out)

    def test_a_language_the_project_uses_keeps_its_section(self):
        out = f.keep_relevant(TEXT, frozenset({"dart"}), _label)
        self.assertIn("fvm", out)
        self.assertNotIn("Left out", out)


class LabelerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = patch.object(f, "clyde_home", return_value=Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _label(self, reply):
        with patch("src.providers.base.stream_with_retry", side_effect=reply if isinstance(reply, list) else [reply]) as call:
            return f.model_labeler(object(), "m"), call

    def test_the_first_word_of_the_answer_is_the_language_and_it_is_remembered(self):
        label, call = self._label(_Reply("Dart\n"))
        self.assertEqual(label("## A\nx"), "dart")
        self.assertEqual(label("## A\nx"), "dart")
        self.assertEqual(call.call_count, 1)

    def test_a_rambling_or_unknown_answer_keeps_the_section(self):
        label, _ = self._label(_Reply("The text is about dart"))
        self.assertEqual(label("## A\nx"), "general")

    def test_a_failed_call_keeps_the_section_and_is_not_remembered(self):
        label, call = self._label([ProviderError("ollama", "down"), _Reply("dart")])
        self.assertEqual(label("## A\nx"), "general")
        self.assertEqual(label("## A\nx"), "dart")
        self.assertEqual(call.call_count, 2)


class LoaderTests(unittest.TestCase):
    def test_only_the_users_own_file_is_filtered(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as proj:
            (Path(home) / ".claude").mkdir()
            (Path(home) / ".claude" / "CLAUDE.md").write_text("mine")
            (Path(proj) / "CLAUDE.md").write_text("theirs")
            with patch("src.context_system.claude_md.Path.home", return_value=Path(home)):
                ctx = load_claude_md_context(proj, filter_user_file=lambda t: t.upper())
            self.assertEqual([c.content for c in ctx.files], ["MINE", "theirs"])


if __name__ == "__main__":
    unittest.main()
