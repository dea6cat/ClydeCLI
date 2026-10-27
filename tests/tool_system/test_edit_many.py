"""Several edits in one Edit call: matched against the file as it is, all or nothing, none touching the same text."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.providers.toolcall_repair import coerce_tool_args
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.errors import ToolInputError
from src.tool_system.protocol import ToolCall
from src.tool_system.tools import FileEditTool, FileReadTool

SOURCE = "alpha = 1\nbeta = 2\ngamma = 3\nbeta_again = 2\n"


class ManyEdits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.ctx = ToolContext(workspace_root=self.root)
        self.path = self.root / "f.py"
        self.path.write_text(SOURCE, encoding="utf-8")
        FileReadTool().run({"file_path": str(self.path)}, self.ctx)

    def edit(self, **body):
        return FileEditTool().run({"file_path": str(self.path), **body}, self.ctx).output

    def test_several_edits_are_made_in_one_call_each_matched_against_the_original(self):
        out = self.edit(edits=[{"old_string": "alpha = 1", "new_string": "alpha = 10"}, {"old_string": "gamma = 3", "new_string": "gamma = 30\ndelta = 4"}])
        self.assertEqual(self.path.read_text(), "alpha = 10\nbeta = 2\ngamma = 30\ndelta = 4\nbeta_again = 2\n")
        self.assertEqual(out["edits"], 2)
        self.assertTrue(out["structuredPatch"])
        # an edit's old_string is looked for in the file as it was, so one edit cannot depend on another's result
        FileReadTool().run({"file_path": str(self.path)}, self.ctx)
        with self.assertRaises(ToolInputError) as caught:
            self.edit(edits=[{"old_string": "alpha = 10", "new_string": "alpha = 11"}, {"old_string": "alpha = 11", "new_string": "alpha = 12"}])
        self.assertIn("edits[1]", str(caught.exception))

    def test_it_is_all_or_nothing_and_names_the_edit_that_failed(self):
        with self.assertRaises(ToolInputError) as caught:
            self.edit(edits=[{"old_string": "alpha = 1", "new_string": "X"}, {"old_string": "no such line", "new_string": "Y"}])
        self.assertIn("edits[1]: old_string not found", str(caught.exception))
        self.assertEqual(self.path.read_text(), SOURCE)   # the first one was not made either
        with self.assertRaises(ToolInputError) as caught:
            self.edit(edits=[{"old_string": "= 2", "new_string": "= 20"}])   # twice in the file
        self.assertIn("edits[0]", str(caught.exception))
        self.assertEqual(self.path.read_text(), SOURCE)

    def test_two_edits_that_touch_the_same_text_are_refused(self):
        with self.assertRaises(ToolInputError) as caught:
            self.edit(edits=[{"old_string": "beta = 2\ngamma", "new_string": "A"}, {"old_string": "gamma = 3", "new_string": "B"}])
        self.assertIn("touch the same text", str(caught.exception))
        self.assertEqual(self.path.read_text(), SOURCE)

    def test_replace_all_inside_edits_and_the_old_form_still_work(self):
        out = self.edit(edits=[{"old_string": "= 2", "new_string": "= 20", "replace_all": True}, {"old_string": "alpha", "new_string": "first"}])
        self.assertEqual(self.path.read_text(), "first = 1\nbeta = 20\ngamma = 3\nbeta_again = 20\n")
        self.assertTrue(out["replaceAll"])
        FileReadTool().run({"file_path": str(self.path)}, self.ctx)
        self.edit(old_string="gamma = 3", new_string="gamma = 33")   # the single form, as before
        self.assertIn("gamma = 33", self.path.read_text())

    def test_a_loose_match_inside_edits_still_says_so_and_bad_input_is_refused(self):
        self.path.write_text("def f():   \n    return 1\n", encoding="utf-8")
        FileReadTool().run({"file_path": str(self.path)}, self.ctx)
        out = self.edit(edits=[{"old_string": "def f():\n    return 1\n", "new_string": "def f():\n    return 2\n"}])
        self.assertEqual(out["matchedLoosely"], "trailing whitespace")
        for bad in ({"edits": []}, {"edits": "x"}, {"edits": [{"old_string": "", "new_string": "x"}]}, {"edits": [{"old_string": "a"}]},
                    {"edits": [{"old_string": "a", "new_string": "b"}], "old_string": "a", "new_string": "b"}, {"edits": [{"old_string": "a", "new_string": "b"}] * 51}, {}):
            with self.assertRaises(ToolInputError, msg=str(bad)[:60]):
                self.edit(**bad)

    def test_through_the_registry_the_schema_takes_edits_and_a_model_that_sends_them_as_a_string_is_repaired(self):
        registry = build_default_registry()
        spec = next(s for s in registry.list_specs() if s.name == "Edit")
        self.assertEqual(spec.input_schema["required"], ["file_path"])
        name, args = coerce_tool_args("Edit", {"file_path": str(self.path), "edits": '[{"old_string": "alpha = 1", "new_string": "a = 1"},]'})   # a string, with a trailing comma
        self.assertEqual((name, args["edits"]), ("Edit", [{"old_string": "alpha = 1", "new_string": "a = 1"}]))
        _, args = coerce_tool_args("Edit", {"file_path": "x", "edits": {"old_string": "a", "new_string": "b"}})   # one edit, not a list
        self.assertEqual(args["edits"], [{"old_string": "a", "new_string": "b"}])
        registry.dispatch(ToolCall(name="Edit", input={"file_path": str(self.path), "edits": [{"old_string": "alpha = 1", "new_string": "a = 1"}]}, tool_use_id="t"), self.ctx)
        self.assertTrue(self.path.read_text().startswith("a = 1"))


if __name__ == "__main__":
    unittest.main()
