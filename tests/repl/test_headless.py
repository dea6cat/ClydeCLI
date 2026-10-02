"""`clyde -p`: one headless turn, answer on stdout, nothing interactive, honest exit status."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.providers.base import ProviderError
from src.repl import headless
from tests.fakes import reply
from tests.repl.test_repl import _fake_provider_env


class _Pipe(io.StringIO):
    def isatty(self) -> bool:
        return False


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


class TestBuildPrompt(unittest.TestCase):
    def test_a_pipe_that_never_closes_does_not_hang_a_prompted_run(self):
        import os
        import time
        read_end, write_end = os.pipe()                     # stays open and silent, like cron's or ssh's stdin
        self.addCleanup(os.close, write_end)
        with os.fdopen(read_end) as silent:
            start = time.monotonic()
            self.assertEqual(headless.build_prompt("hello", silent), "hello")
            self.assertLess(time.monotonic() - start, 3)

    def test_piped_data_on_a_real_pipe_is_still_read(self):
        import os
        read_end, write_end = os.pipe()
        os.write(write_end, b"from the pipe\n")
        os.close(write_end)
        with os.fdopen(read_end) as piped:
            self.assertEqual(headless.build_prompt("summarize", piped), "summarize\n\n<stdin>\nfrom the pipe\n</stdin>")

    def test_piped_input_is_added_to_the_prompt(self):
        self.assertEqual(headless.build_prompt("review this", _Pipe("diff --git a b\n")),
                         "review this\n\n<stdin>\ndiff --git a b\n</stdin>")
        self.assertEqual(headless.build_prompt("-", _Pipe("just the input\n")), "just the input")
        self.assertEqual(headless.build_prompt("hello", _Tty("")), "hello")


class TestRun(unittest.TestCase):
    def setUp(self):
        self.cwd = tempfile.mkdtemp()
        patcher = patch("src.repl.core.Path.cwd", return_value=Path(self.cwd))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, *responses, prompt="what is 2+2?", **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with _fake_provider_env(*responses) as provider, patch("sys.stderr", err):
            code = headless.run(prompt, model="glm:glm-4.5", stdin=_Tty(""), stdout=out, **kwargs)
        return code, out.getvalue(), err.getvalue(), provider

    def test_only_the_answer_goes_to_stdout(self):
        code, out, err, _ = self._run(reply("4", usage={"input_tokens": 10, "output_tokens": 1}))
        self.assertEqual((code, out), (0, "4\n"))

    def test_json_output_for_scripts(self):
        code, out, _, _ = self._run(reply("4", usage={"input_tokens": 10, "output_tokens": 1}), output_format="json")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual({k: data[k] for k in ("result", "is_error", "model", "num_turns", "denied")},
                         {"result": "4", "is_error": False, "model": "glm:glm-4.5", "num_turns": 1, "denied": []})
        self.assertEqual(data["usage"]["output_tokens"], 1)
        self.assertTrue(data["session_id"])

    def test_anything_that_would_ask_is_denied_not_prompted(self):
        with patch("rich.prompt.Prompt.ask", side_effect=AssertionError("prompted in -p mode")), \
                patch("rich.prompt.Confirm.ask", side_effect=AssertionError("prompted in -p mode")):
            code, out, err, provider = self._run(
                reply(tool_calls=[("Bash", {"command": "touch made-by-the-model.txt"})]),
                reply("I couldn't create the file: permission was denied."), output_format="json")
        data = json.loads(out)
        self.assertEqual(data["denied"], ["Bash"])
        self.assertIn("Denied Bash", err)
        self.assertFalse((Path(self.cwd) / "made-by-the-model.txt").exists())
        self.assertEqual(code, 0)

    def test_a_provider_failure_exits_1_without_a_re_login_prompt(self):
        with patch("rich.prompt.Prompt.ask", side_effect=AssertionError("prompted in -p mode")):
            code, out, err, _ = self._run(ProviderError("glm", "HTTP 401 — authentication failed", status=401),
                                          output_format="json")
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertTrue(data["is_error"])
        self.assertIn("401", data["error"])
        self.assertIn("clyde login", err)

    def test_running_out_of_rounds_is_a_failure(self):
        loop = [reply(tool_calls=[("Glob", {"pattern": "*.py"})]) for _ in range(2)]
        code, out, _, _ = self._run(*loop, max_turns=2)
        self.assertEqual(code, 1)
        self.assertIn("Max tool turns", out)

    def test_nothing_to_do(self):
        out = io.StringIO()
        with patch("sys.stderr", io.StringIO()):
            self.assertEqual(headless.run("", stdin=_Tty(""), stdout=out), 2)
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
