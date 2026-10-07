"""Artifacts: which files count, how they are described, and what may be read back."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent.conversation import ToolResultContentBlock, ToolUseContentBlock
from src.agent.session import Session
from src.bonny import artifacts


def session(session_id: str, cwd: Path, calls: list, updated: str = "2026-10-07T10:00:00") -> Session:
    """A session whose assistant turn made `calls`: (tool use id, tool name, input, failed?)."""
    s = Session(session_id=session_id, provider="p", model="m", cwd=str(cwd), updated_at=updated)
    s.conversation.add_user_message("make me something")
    s.conversation.add_message("assistant", [ToolUseContentBlock(id=i, name=name, input=inp) for i, name, inp, _ in calls])
    s.conversation.add_message("user", [ToolResultContentBlock(tool_use_id=i, content="boom" if failed else "ok", is_error=failed) for i, _, _, failed in calls])
    return s


def temp_dir(case: unittest.TestCase) -> Path:
    path = Path(tempfile.mkdtemp()).resolve()
    case.addCleanup(shutil.rmtree, path, ignore_errors=True)
    return path


class TestClassify(unittest.TestCase):
    def test_files_are_grouped_by_what_they_are(self):
        self.assertEqual(artifacts.classify("a/index.html"), ("html", "page"))
        self.assertEqual(artifacts.classify("NOTES.MD"), ("markdown", "document"))
        self.assertEqual(artifacts.classify("p.svg"), ("image", "image"))
        self.assertEqual(artifacts.classify("r.csv"), ("text", "document"))
        self.assertEqual(artifacts.classify("tool.py"), ("text", "code"))
        self.assertEqual(artifacts.classify("archive.zip"), ("other", "other"))
        self.assertEqual(artifacts.classify("Makefile"), ("other", "other"))


class TestCollect(unittest.TestCase):
    def setUp(self):
        self.root = temp_dir(self)
        (self.root / "site").mkdir()
        (self.root / "site" / "index.html").write_text("<h1>hi</h1>")
        (self.root / "notes.md").write_text("# notes")

    def rows(self, sessions):
        return {r["name"]: r for r in artifacts.collect(sessions, lambda s: "title of " + s.session_id)}

    def test_successful_writes_and_edits_are_listed_and_the_rest_is_not(self):
        s = session("s1", self.root, [
            ("a", "Write", {"file_path": str(self.root / "site" / "index.html")}, False),
            ("b", "Write", {"file_path": "notes.md"}, False),            # relative: resolved against the session's folder
            ("c", "Edit", {"file_path": "notes.md"}, False),
            ("d", "Write", {"file_path": str(self.root / "broken.txt")}, True),   # failed
            ("e", "Bash", {"command": "echo hi > shell.txt"}, False),            # shell changes aren't visible
            ("f", "Read", {"file_path": str(self.root / "notes.md")}, False),
        ])
        rows = self.rows([s])
        self.assertEqual(sorted(rows), ["index.html", "notes.md"])
        self.assertEqual((rows["notes.md"]["tool"], rows["notes.md"]["changes"]), ("Edit", 2))   # the later call in the same session wins
        self.assertEqual((rows["index.html"]["kind"], rows["index.html"]["group"], rows["index.html"]["folder"]), ("html", "page", "site"))
        self.assertEqual((rows["notes.md"]["folder"], rows["notes.md"]["exists"], rows["notes.md"]["size"]), ("", True, 7))
        self.assertEqual(rows["index.html"]["session"], {"id": "s1", "title": "title of s1"})

    def test_a_file_keeps_the_newest_session_that_touched_it_and_counts_every_change(self):
        newer = session("new", self.root, [("a", "Edit", {"file_path": "notes.md"}, False)], updated="2026-10-07T12:00:00")
        older = session("old", self.root, [("a", "Write", {"file_path": "notes.md"}, False)], updated="2026-10-06T12:00:00")
        row = self.rows([newer, older])["notes.md"]                      # list_recent gives newest first
        self.assertEqual((row["session"]["id"], row["tool"], row["changes"]), ("new", "Edit", 2))

    def test_a_deleted_file_is_still_listed_but_marked_missing(self):
        (self.root / "notes.md").unlink()
        row = self.rows([session("s1", self.root, [("a", "Write", {"file_path": "notes.md"}, False)])])["notes.md"]
        self.assertEqual((row["exists"], row["size"]), (False, 0))

    def test_the_public_row_hides_the_project_folder(self):
        row = artifacts.collect([session("s1", self.root, [("a", "Write", {"file_path": "notes.md"}, False)])], lambda s: "t")[0]
        self.assertIn("cwd", row)
        self.assertNotIn("cwd", artifacts.public(row))


class TestFind(unittest.TestCase):
    def setUp(self):
        self.root = temp_dir(self)
        (self.root / "ok.md").write_text("fine")
        self.outside = temp_dir(self)
        (self.outside / "secret.txt").write_text("secret")

    def rows(self, *names):
        s = session("s1", self.root, [(str(i), "Write", {"file_path": n}, False) for i, n in enumerate(names)])
        return artifacts.collect([s], lambda x: "t")

    def test_only_listed_files_inside_the_project_are_found(self):
        rows = self.rows("ok.md")
        self.assertEqual(artifacts.find(str(self.root / "ok.md"), rows)["name"], "ok.md")
        self.assertIsNone(artifacts.find(str(self.root / "not-listed.md"), rows))
        self.assertIsNone(artifacts.find("/etc/passwd", rows))

    def test_a_listed_path_that_points_outside_the_project_is_refused(self):
        rows = self.rows(str(self.outside / "secret.txt"))                    # a write that named a file elsewhere
        self.assertIsNone(artifacts.find(str(self.outside / "secret.txt"), rows))

    def test_a_link_swapped_in_after_the_write_cannot_reach_another_file(self):
        rows = self.rows("ok.md")
        (self.root / "ok.md").unlink()
        (self.root / "ok.md").symlink_to(self.outside / "secret.txt")
        self.assertIsNone(artifacts.find(str(self.root / "ok.md"), rows))


class TestReadAndReveal(unittest.TestCase):
    def setUp(self):
        self.root = temp_dir(self)

    def test_text_is_read_and_cut_at_the_preview_limit(self):
        (self.root / "t.txt").write_text("x" * 50)
        with patch.object(artifacts, "MAX_TEXT", 10):
            self.assertEqual(artifacts.read_text(self.root / "t.txt"), {"text": "x" * 10, "truncated": True})
        self.assertEqual(artifacts.read_text(self.root / "t.txt"), {"text": "x" * 50, "truncated": False})

    def test_a_binary_file_is_not_shown_as_text(self):
        (self.root / "b.bin").write_bytes(b"\x89PNG\x00\x00data")
        self.assertEqual(artifacts.read_text(self.root / "b.bin"), {"kind": "other"})

    def test_reveal_reports_whether_the_file_manager_ran(self):
        with patch("src.bonny.artifacts.subprocess.run") as run:
            run.return_value.returncode = 0
            self.assertTrue(artifacts.reveal(self.root / "a.txt"))
            run.side_effect = OSError("no such program")
            self.assertFalse(artifacts.reveal(self.root / "a.txt"))


if __name__ == "__main__":
    unittest.main()
