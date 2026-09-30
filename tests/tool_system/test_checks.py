"""Python checks: detection, new-problems-only diffing, feedback in the agent loop, and /check,
against fake `ruff` / `mypy` / `pytest` / `uv` scripts on PATH."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent.agent_loop import run_agent_loop
from src.agent.conversation import Conversation
from src.command_system import create_command_context, execute_command_sync
from src.tool_system.checks import Problem, detect, new_problems, parse_mypy, parse_ruff
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from tests.fakes import FakeProvider, reply

# Flags `import os` lines like ruff's F401; a bare "." (whole project) is clean.
FAKE_RUFF = """#!/bin/sh
echo "ruff $*" >> "$CHECKS_LOG"
for a in "$@"; do
  case "$a" in *.py) awk -v f="$a" '/^import os/ {print f":"NR":8: F401 [*] `os` imported but unused"}' "$a";; esac
done
"""
# Flags `: int = "` lines; for "." reports one project-wide error.
FAKE_MYPY = """#!/bin/sh
echo "mypy $*" >> "$CHECKS_LOG"
for a in "$@"; do
  case "$a" in
    *.py) awk -v f="$a" '/: int = "/ {print f":"NR": error: Incompatible types in assignment  [assignment]"}' "$a";;
    .) echo 'pkg/m.py:3: error: Name "y" is not defined  [name-defined]'; exit 1;;
  esac
done
"""
FAKE_PYTEST = """#!/bin/sh
echo "pytest $*" >> "$CHECKS_LOG"
echo "FAILED tests/test_a.py::test_x - assert 1 == 2"
echo "1 failed, 3 passed in 0.10s"
exit 1
"""
FAKE_UV = """#!/bin/sh
echo "uv $*" >> "$CHECKS_LOG"
shift 2; exec "$@"
"""


class ChecksTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.bin = base / "bin"
        self.bin.mkdir()
        for name, script in {"ruff": FAKE_RUFF, "mypy": FAKE_MYPY, "pytest": FAKE_PYTEST}.items():
            self._tool(self.bin / name, script)
        self.root = base / "proj"
        self.root.mkdir()
        (self.root / "pyproject.toml").write_text("[project]\nname = 'p'\n\n[tool.mypy]\nstrict = true\n")
        (self.root / "tests").mkdir()
        self.home = base / "home"
        self.home.mkdir()
        self.log = base / "calls.log"
        self.env = patch.dict(os.environ, {"PATH": f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin",
                                           "CHECKS_LOG": str(self.log), "CLYDE_CHECKS": ""})
        self.env.start()
        self.home_patch = patch.object(Path, "home", return_value=self.home)
        self.home_patch.start()

    def tearDown(self) -> None:
        self.home_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    @staticmethod
    def _tool(path: Path, script: str) -> None:
        path.write_text(script)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)


class TestDetection(ChecksTestCase):
    def test_detects_configured_tools_on_path(self) -> None:
        tooling = detect(self.root)
        self.assertEqual(tooling.tools, {"ruff": [str(self.bin / "ruff")], "mypy": [str(self.bin / "mypy")],
                                         "pytest": [str(self.bin / "pytest")]})
        self.assertEqual(tooling.via, "PATH")

    def test_mypy_and_pytest_need_config_but_ruff_does_not(self) -> None:
        (self.root / "pyproject.toml").write_text("[project]\nname = 'p'\n")
        (self.root / "tests").rmdir()
        self.assertEqual(set(detect(self.root).tools), {"ruff"})
        (self.root / "mypy.ini").write_text("[mypy]\n")
        self.assertEqual(set(detect(self.root).tools), {"ruff", "mypy"})

    def test_not_a_python_project(self) -> None:
        (self.root / "pyproject.toml").unlink()
        self.assertIsNone(detect(self.root))

    def test_prefers_uv_then_project_venv(self) -> None:
        venv_ruff = self.root / ".venv" / "bin" / "ruff"
        venv_ruff.parent.mkdir(parents=True)
        self._tool(venv_ruff, FAKE_RUFF)
        self.assertEqual(detect(self.root).tools["ruff"], [str(venv_ruff)])
        self.assertEqual(detect(self.root).via, ".venv")
        (self.root / "uv.lock").write_text("")
        self._tool(self.bin / "uv", FAKE_UV)
        tooling = detect(self.root)
        self.assertEqual(tooling.tools["ruff"], ["uv", "run", "--no-sync", "ruff"])
        self.assertEqual(tooling.via, "uv run")


class TestProblems(unittest.TestCase):
    def test_parsers(self) -> None:
        ruff = parse_ruff("a.py:1:8: F401 [*] `os` imported but unused\nb.py:2:5: SyntaxError: Expected ':'\nFound 2 errors.")
        self.assertEqual(ruff, [Problem("a.py", 1, "F401", "`os` imported but unused"),
                                Problem("b.py", 2, "SyntaxError", "Expected ':'")])
        mypy = parse_mypy('a.py:3: error: Incompatible types  [assignment]\na.py:4: note: see docs\n')
        self.assertEqual(mypy, [Problem("a.py", 3, "assignment", "Incompatible types")])
        self.assertEqual(str(mypy[0]), "a.py:3: assignment Incompatible types")

    def test_only_new_problems_survive_line_shifts(self) -> None:
        before = [Problem("a.py", 1, "F401", "`os` unused"), Problem("a.py", 9, "E501", "long")]
        after = [Problem("a.py", 3, "F401", "`os` unused"), Problem("a.py", 5, "F401", "`os` unused"),
                 Problem("a.py", 7, "assignment", "bad")]
        self.assertEqual(new_problems(before, after), after[1:])


class TestAgentLoopFeedback(ChecksTestCase):
    def _write(self, content: str):
        target = self.root / "mod.py"
        target.write_text("import os\n")
        context = ToolContext(workspace_root=self.root)
        context.mark_file_read(target)
        provider = FakeProvider(
            reply(tool_calls=[("Write", {"file_path": str(target), "content": content}, "toolu_1")]),
            reply("done"),
        )
        conversation = Conversation()
        conversation.add_user_message("edit mod.py")
        run_agent_loop(conversation=conversation, provider=provider, model="fake-model",
                       tool_registry=build_default_registry(), tool_context=context)
        return json.loads(provider.requests[1]["conversation"].messages[-1].tool_results[0].content)

    def test_new_problems_reach_the_model_in_the_same_loop(self) -> None:
        result = self._write('import os\nx: int = "s"\n')
        self.assertEqual(result["newProblems"],
                         "1 new problem(s) after this edit; fix them:\nmod.py:2: assignment Incompatible types in assignment")
        self.assertIn("ruff check --no-fix --output-format=concise mod.py", self.log.read_text())

    def test_clean_edit_adds_nothing(self) -> None:
        self.assertNotIn("newProblems", self._write("import os\nx: int = 1\n"))

    def test_switched_off_by_env_or_settings(self) -> None:
        with patch.dict(os.environ, {"CLYDE_CHECKS": "off"}):
            self.assertNotIn("newProblems", self._write('x: int = "s"\n'))
        (self.home / ".clyde").mkdir()
        (self.home / ".clyde" / "settings.json").write_text('{"checks": {"enabled": false}}')
        self.assertNotIn("newProblems", self._write('x: int = "s"\n'))
        self.assertFalse(self.log.exists())


class TestCheckCommand(ChecksTestCase):
    def test_summarizes_ruff_mypy_and_pytest(self) -> None:
        ok, text, error = execute_command_sync("check", "", create_command_context(workspace_root=self.root))
        self.assertTrue(ok, error)
        self.assertEqual(text, "\n".join([
            "Checks (via PATH):",
            "✓ ruff: clean",
            "✗ mypy: 1 problem(s)",
            "    pkg/m.py:3: name-defined Name \"y\" is not defined",
            "✗ pytest: FAILED tests/test_a.py::test_x - assert 1 == 2",
            "    1 failed, 3 passed in 0.10s",
        ]))


if __name__ == "__main__":
    unittest.main()
