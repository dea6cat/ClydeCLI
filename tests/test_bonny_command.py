"""`bonny luv clyde` hands over to the terminal Clyde; anything else is a usage error."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src import cli


class TestBonnyCommand(unittest.TestCase):
    def run_with(self, *argv):
        with patch("sys.argv", ["bonny", *argv]), patch("src.cli.main", return_value=0) as main:
            code = cli.bonny_main()
            return code, main.call_count, __import__("sys").argv[1:]

    def test_luv_clyde_runs_main_with_the_rest_of_the_options(self):
        self.assertEqual(self.run_with("luv", "clyde", "--model", "glm:glm-4.5", "-c"), (0, 1, ["--model", "glm:glm-4.5", "-c"]))
        self.assertEqual(self.run_with("luv", "clyde")[:2], (0, 1))

    def test_anything_else_is_a_usage_error_and_runs_nothing(self):
        for argv in ((), ("luv",), ("luv", "bonny"), ("clyde",), ("--version",)):
            self.assertEqual(self.run_with(*argv)[:2], (2, 0), argv)


if __name__ == "__main__":
    unittest.main()
