from __future__ import annotations

import os
import subprocess
import time
import unittest
from unittest.mock import patch

from src.proc import run_group


def _gone(pid: int) -> bool:
    for _ in range(20):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


class TestRunGroup(unittest.TestCase):
    def test_it_returns_output_like_run(self):
        done = run_group(["sh", "-c", "echo hi; exit 3"], stdout=subprocess.PIPE, text=True)
        self.assertEqual((done.returncode, done.stdout), (3, "hi\n"))

    def test_a_timeout_also_kills_the_childs_children(self):
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            run_group(["sh", "-c", "sleep 60 & echo $!; wait"], stdout=subprocess.PIPE, text=True, timeout=1)
        self.assertTrue(_gone(int(caught.exception.stdout.strip())))

    def test_ctrl_c_kills_the_group_and_propagates(self):
        real = subprocess.Popen.communicate
        calls = []

        def interrupted(self, *a, **k):
            if not calls:
                calls.append(1)
                time.sleep(0.5)   # let the shell print the grandchild's pid
                raise KeyboardInterrupt
            return real(self, *a, **k)

        with patch.object(subprocess.Popen, "communicate", interrupted):
            with patch("src.proc._kill_group", wraps=__import__("src.proc", fromlist=["x"])._kill_group) as kill:
                with self.assertRaises(KeyboardInterrupt):
                    run_group(["sh", "-c", "sleep 60 & wait"], stdout=subprocess.PIPE, text=True)
        kill.assert_called_once()
        proc = kill.call_args.args[0]
        self.assertIsNotNone(proc.poll())


if __name__ == "__main__":
    unittest.main()
