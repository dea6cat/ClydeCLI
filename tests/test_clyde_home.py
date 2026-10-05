"""clyde_home: XDG_CONFIG_HOME is honored, but never at the cost of an existing ~/.clyde."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import clyde_home


class TestClydeHome(unittest.TestCase):
    def setUp(self):
        self.home, self.xdg = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        p = patch.object(Path, "home", return_value=self.home)
        p.start()
        self.addCleanup(p.stop)

    def at(self, xdg):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": xdg}):
            return clyde_home()

    def test_choice(self):
        self.assertEqual(self.at(""), self.home / ".clyde")                # unset
        self.assertEqual(self.at(str(self.xdg)), self.xdg / "clyde")       # fresh install
        self.assertEqual(self.at("relative/dir"), self.home / ".clyde")    # relative values are ignored, per the spec
        (self.home / ".clyde").mkdir()
        self.assertEqual(self.at(str(self.xdg)), self.home / ".clyde")     # an existing ~/.clyde wins
        (self.xdg / "clyde").mkdir()
        self.assertEqual(self.at(str(self.xdg)), self.xdg / "clyde")       # unless the XDG folder exists too


if __name__ == "__main__":
    unittest.main()
