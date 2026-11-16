"""A flagged outside result in a sub-agent or a worker counts for the whole session, and the other way round."""

from __future__ import annotations

import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from src.agent.orchestration import _worker_context
from src.tool_system.context import ToolContext


class TestShared(unittest.TestCase):
    def test_sub_agent_and_worker_contexts_share_the_flag(self):
        parent = ToolContext(workspace_root=Path(tempfile.mkdtemp()))
        sub = replace(parent, read_file_fingerprints={}, todos=[])   # how the Agent tool copies the context
        worker = _worker_context(parent, Path(tempfile.mkdtemp()), SimpleNamespace(permission_handler=lambda *a: None),
                                 "worker-1", threading.Event(), object(), "m")
        sub.injection_sources.append("WebFetch (x)")
        self.assertEqual(parent.injection_sources, ["WebFetch (x)"])
        self.assertIs(worker.injection_sources, parent.injection_sources)


if __name__ == "__main__":
    unittest.main()
