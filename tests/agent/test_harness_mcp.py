"""The harness list shows the MCP servers Clyde really connects to (settings.json's mcpServers)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent.harness import discover_mcp_servers


class TestHarnessMcp(unittest.TestCase):
    def test_servers_come_from_the_settings_file(self):
        with tempfile.TemporaryDirectory() as home, patch("src.settings.clyde_home", return_value=Path(home)):
            (Path(home) / "settings.json").write_text(json.dumps({"mcpServers": {"github": {"command": "gh-mcp"}}}))
            self.assertEqual([(h.name, h.binary) for h in discover_mcp_servers()], [("mcp:github", "gh-mcp")])


if __name__ == "__main__":
    unittest.main()
