"""Choosing the project: browsing, making a folder, and switching Bonny to it."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

from src.bonny import projects
from tests.bonny import test_server as ts
from tests.bonny.test_artifacts import temp_dir


class TestProjects(ts.BonnyCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(os.chdir, os.getcwd())
        self.base = temp_dir(self)
        (self.base / "alpha").mkdir()
        (self.base / ".hidden").mkdir()
        (self.base / "file.txt").write_text("x")

    def test_browsing_lists_visible_folders_only_and_knows_the_parent(self):
        status, info = self.call("GET", f"/api/dirs?path={self.base}")
        self.assertEqual((status, info["dirs"], info["parent"]), (200, ["alpha"], str(self.base.parent)))
        self.assertEqual(self.call("GET", f"/api/dirs?path={self.base}/nope")[0], 400)
        self.assertEqual(self.call("GET", "/api/dirs?path=relative/dir")[0], 400)
        self.assertEqual(self.call("GET", "/api/dirs")[1]["path"], str(Path(self.repl.tool_context.workspace_root).resolve()))   # starts at the open project

    def test_a_new_folder_is_made_inside_the_parent_and_bad_names_are_refused(self):
        status, made = self.call("POST", "/api/dirs/create", {"parent": str(self.base), "name": "fresh"})
        self.assertEqual((status, Path(made["path"])), (200, self.base / "fresh"))
        self.assertTrue((self.base / "fresh").is_dir())
        for name in ("", "  ", "..", ".", "a/b", "..\\x", "fresh", "x" * 101, 5):
            self.assertEqual(self.call("POST", "/api/dirs/create", {"parent": str(self.base), "name": name})[0], 400, name)
        self.assertFalse((self.base.parent / "x").exists())

    def test_choosing_a_project_moves_tools_permissions_and_sessions_there(self):
        target = self.base / "alpha"
        before = self.call("GET", "/api/state")[1]["cwd"]
        status, state = self.call("POST", "/api/project", {"path": str(target)})
        self.assertEqual((status, state["cwd"], state["messages"]), (200, str(target.resolve()), []))
        context = self.repl.tool_context
        self.assertEqual((context.workspace_root, context.cwd, context.permission_context.workspace_root), (target.resolve(),) * 3)
        self.assertEqual(self.repl.session.cwd, str(target.resolve()))
        self.assertNotEqual(before, state["cwd"])
        self.assertEqual(projects.recent()[0], str(target.resolve()))

    def test_choosing_is_refused_for_missing_folders_and_while_busy(self):
        self.assertEqual(self.call("POST", "/api/project", {"path": str(self.base / "nope")})[0], 400)
        self.assertEqual(self.call("POST", "/api/project", {"path": str(self.base / "file.txt")})[0], 400)
        self.assertEqual(self.call("POST", "/api/project", {})[0], 400)
        self.bonny.control.busy = True
        self.assertEqual(self.call("POST", "/api/project", {"path": str(self.base)})[0], 409)
        self.bonny.control.busy = False


if __name__ == "__main__":
    unittest.main()
