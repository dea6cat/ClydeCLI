"""clyde acp install zed: Clyde is added to Zed's settings.json as text, so comments and other settings survive."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from src.install import zed

CMD = "/home/me/.local/bin/clyde"

# Zed's real file is JSON with comments and trailing commas.
ZED = """// Zed settings
{
  "theme": "One Dark", // keep me
  /* an agent_servers { in a comment */
  "agent_servers": {
    "your_agent": {
      "type": "custom",
      "command": "path_to_executable",
    },
    "opencode": {
      "type": "registry"
    }
  },
}
"""


class TestZedInstall(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "zed" / "settings.json"
        self.console = Console(record=True, width=200)

    def _install(self, text=None, **kw):
        if text is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(text, encoding="utf-8")
        return zed.install(self.console, command=CMD, path=self.path, assume_yes=True, **kw)

    def _settings(self):
        return zed._parse(self.path.read_text(encoding="utf-8"))

    def test_the_agent_is_added_next_to_the_others_and_the_comments_survive(self):
        self.assertEqual(self._install(ZED), 0)
        agents = self._settings()["agent_servers"]
        self.assertEqual(agents["Clyde"], {"type": "custom", "command": CMD, "args": ["--acp"]})
        self.assertEqual(set(agents), {"Clyde", "your_agent", "opencode"})
        text = self.path.read_text(encoding="utf-8")
        for kept in ("// Zed settings", "// keep me", "/* an agent_servers { in a comment */", '"theme": "One Dark"'):
            self.assertIn(kept, text)

    def test_a_file_without_agent_servers_gets_the_section(self):
        self.assertEqual(self._install('{\n  "theme": "One Dark"\n}\n'), 0)
        self.assertEqual(self._settings()["agent_servers"], {"Clyde": {"type": "custom", "command": CMD, "args": ["--acp"]}})
        self.assertEqual(self._settings()["theme"], "One Dark")

    def test_an_empty_object_an_empty_agent_servers_and_a_missing_file_all_work(self):
        for text in ("{}", '{"agent_servers": {}}', None):
            self.path.unlink(missing_ok=True)
            self.assertEqual(self._install(text), 0, text)
            self.assertEqual(list(self._settings()["agent_servers"]), ["Clyde"], text)

    def test_a_second_run_changes_nothing(self):
        self._install(ZED)
        once = self.path.read_text(encoding="utf-8")
        self.assertEqual(self._install(), 0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), once)
        self.assertIn("already has", self.console.export_text())

    def test_an_entry_with_another_command_is_left_alone_and_pointed_out(self):
        self._install('{"agent_servers": {"Clyde": {"type": "custom", "command": "/old/clyde"}}}')
        before = self.path.read_text(encoding="utf-8")
        self.assertEqual(self._install(), 0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self.assertIn("/old/clyde", self.console.export_text())

    def test_a_file_that_is_not_json_is_refused_untouched(self):
        broken = '{"theme": '
        self.assertEqual(self._install(broken), 1)
        self.assertEqual(self.path.read_text(encoding="utf-8"), broken)
        self.assertFalse(self.path.with_name("settings.json.clyde-bak").exists())

    def test_an_existing_file_is_backed_up_before_it_is_changed(self):
        self._install(ZED)
        self.assertEqual(self.path.with_name("settings.json.clyde-bak").read_text(encoding="utf-8"), ZED)

    def test_declining_the_question_writes_nothing(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(ZED, encoding="utf-8")
        with patch("rich.prompt.Confirm.ask", return_value=False):
            self.assertEqual(zed.install(self.console, command=CMD, path=self.path), 0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), ZED)

    def test_without_the_clyde_command_nothing_is_written(self):
        with patch("src.install.zed.shutil.which", return_value=None):
            self.assertEqual(zed.install(self.console, path=self.path, assume_yes=True), 1)
        self.assertFalse(self.path.exists())

    def test_a_command_path_with_quotes_and_backslashes_stays_valid_json(self):
        odd = 'C:\\Users\\me\\clyde "x".exe'
        zed.install(self.console, command=odd, path=self.path, assume_yes=True)
        self.assertEqual(self._settings()["agent_servers"]["Clyde"]["command"], odd)


if __name__ == "__main__":
    unittest.main()
