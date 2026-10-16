"""A small model fills in a field from its name alone. These three tools were misused that way on Qwen2.5-Coder 3B:
the question text went into `header`, `activeForm` was left empty, `Map` was called without the field its action needs.
Every field of theirs, nested ones included, now says what it holds."""
from __future__ import annotations

import unittest

from src.tool_system.defaults import build_default_registry

# Optional or filled in by Clyde, never by the model.
EXEMPT = {"AskUserQuestion": {"preview", "answers", "annotations", "metadata"}, "TodoWrite": {"status"}, "Map": set()}


def _undocumented(schema: dict, exempt: set[str], path: str = "") -> list[str]:
    missing = []
    for name, sub in (schema.get("properties") or {}).items():
        if name not in exempt and not sub.get("description"):
            missing.append(path + name)
        missing += _undocumented(sub, exempt, f"{path}{name}.")
    items = schema.get("items")
    return missing + (_undocumented(items, exempt, path) if isinstance(items, dict) else [])


class TestSchemaDescriptions(unittest.TestCase):
    def test_every_field_of_the_tools_small_models_misused_is_described(self):
        specs = {s.name: s for s in build_default_registry().list_specs()}
        for tool, exempt in EXEMPT.items():
            with self.subTest(tool=tool):
                self.assertEqual(_undocumented(specs[tool].input_schema, exempt), [])

    def test_the_map_action_says_which_fields_each_action_needs(self):
        text = next(s for s in build_default_registry().list_specs() if s.name == "Map").input_schema["properties"]["action"]["description"]
        for needs in ("query needs question", "path needs source and target", "explain and affected need target"):
            self.assertIn(needs, text)


if __name__ == "__main__":
    unittest.main()
