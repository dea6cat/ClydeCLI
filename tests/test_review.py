"""/review: the diff text for each target, the size cap, and bad input."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from src.review import ReviewError, build_review_prompt, cap_diff, parse_target


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


class TestParseTarget(unittest.TestCase):
    def test_targets(self):
        self.assertEqual(parse_target(""), ("uncommitted", ""))
        self.assertEqual(parse_target("commit abc123"), ("commit", "abc123"))
        self.assertEqual(parse_target("base main"), ("base", "main"))

    def test_bad_input_is_refused(self):
        for bad in ("commit", "base a b", "nonsense x", "commit --output=/tmp/x", "base -h"):
            with self.assertRaises(ReviewError, msg=bad):
                parse_target(bad)


class TestCapDiff(unittest.TestCase):
    def test_a_small_diff_is_unchanged(self):
        diff = "diff --git a/x b/x\n+hi\n"
        self.assertEqual(cap_diff(diff, 1000), diff)

    def test_big_files_are_left_out_and_named(self):
        small = "diff --git a/small.py b/small.py\n+1\n"
        big = "diff --git a/big.py b/big.py\n" + "+x\n" * 500
        capped = cap_diff(small + big, 200)
        self.assertIn("small.py", capped)
        self.assertNotIn("+x", capped)
        self.assertIn("1 file(s) left out", capped)
        self.assertIn("a/big.py b/big.py", capped)


class TestBuildReviewPrompt(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        _git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "a.py").write_text("x = 1\n")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-qm", "first")

    def test_uncommitted_changes_and_untracked_files(self):
        (self.repo / "a.py").write_text("x = 2\n")
        (self.repo / "new.py").write_text("y = 1\n")
        prompt = build_review_prompt("", self.repo)
        self.assertIn("-x = 1", prompt)
        self.assertIn("+x = 2", prompt)
        self.assertIn("new.py", prompt)
        self.assertIn("read-only", prompt)

    def test_nothing_to_review_says_so(self):
        with self.assertRaisesRegex(ReviewError, "no uncommitted changes"):
            build_review_prompt("", self.repo)

    def test_a_commit(self):
        (self.repo / "a.py").write_text("x = 3\n")
        _git(self.repo, "commit", "-qam", "second")
        prompt = build_review_prompt("commit HEAD", self.repo)
        self.assertIn("+x = 3", prompt)
        self.assertIn("second", prompt)

    def test_a_branch_against_its_base(self):
        _git(self.repo, "checkout", "-qb", "feature")
        (self.repo / "b.py").write_text("z = 9\n")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-qm", "feature work")
        prompt = build_review_prompt("base main", self.repo)
        self.assertIn("+z = 9", prompt)
        self.assertNotIn("x = 1", prompt)

    def test_an_unknown_ref_or_a_non_repo_is_an_error(self):
        with self.assertRaisesRegex(ReviewError, "no such commit or branch"):
            build_review_prompt("base nope", self.repo)
        with tempfile.TemporaryDirectory() as plain:
            with self.assertRaises(ReviewError):
                build_review_prompt("", plain)


if __name__ == "__main__":
    unittest.main()


class TestReviewCommand(unittest.IsolatedAsyncioTestCase):
    async def test_the_command_builds_its_prompt_from_the_diff(self):
        from types import SimpleNamespace
        from src.command_system.builtins import REVIEW_COMMAND
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git(repo, "init", "-q", "-b", "main")
            (repo / "a.py").write_text("x = 1\n")
            _git(repo, "add", ".")
            _git(repo, "commit", "-qm", "first")
            (repo / "a.py").write_text("x = 2\n")
            blocks = await REVIEW_COMMAND.get_prompt_for_command("", SimpleNamespace(workspace_root=repo))
        self.assertIn("+x = 2", blocks[0]["text"])


class TestReviewCli(unittest.TestCase):
    def test_outside_a_repository_it_exits_2_with_a_message(self):
        import sys
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as plain:
            done = subprocess.run([sys.executable, "-m", "src.cli", "review"], cwd=plain, capture_output=True, text=True,
                                  env={"PYTHONPATH": str(root), "HOME": plain, "PATH": "/usr/bin:/bin:/usr/local/bin"}, timeout=60)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("review:", done.stderr)
