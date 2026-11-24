"""/skills and /mcp remove only ClydeCLI's own copies: ~/.clyde/skills and mcpServers in ~/.clyde/settings.json."""

from __future__ import annotations

import json
import unittest

from src.skills.loader import get_all_skills, own_skill, remove_skill, skill_source
from src.tool_system.mcp_client import load_servers, remove_user_server, user_server_file
from tests.test_plugins import PluginHomeCase


def _skill(folder, name: str):
    root = folder / name
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(f"---\ndescription: {name} things\n---\nDo {name}.\n")
    return root


def _named(name: str):
    return next(s for s in get_all_skills() if s.name == name)


class TestOwnSkills(PluginHomeCase):
    def test_a_skill_in_clydes_folder_is_yours_and_can_be_removed(self) -> None:
        root = _skill(self.home / ".clyde" / "skills", "mine")
        skill = _named("mine")
        self.assertTrue(own_skill(skill))
        self.assertEqual(skill_source(skill), "yours")
        remove_skill(skill)
        self.assertFalse(root.exists())

    def test_another_agents_skill_is_shared_and_is_never_removed(self) -> None:
        root = _skill(self.home / ".claude" / "skills", "theirs")
        skill = _named("theirs")
        self.assertFalse(own_skill(skill))
        self.assertEqual(skill_source(skill), "Claude Code, shared")
        with self.assertRaises(ValueError):
            remove_skill(skill)
        self.assertTrue(root.exists())

    def test_clydes_folder_linked_to_another_agents_is_not_yours(self) -> None:
        shared = self.home / ".claude" / "skills"
        root = _skill(shared, "linked")
        (self.home / ".clyde").mkdir()
        (self.home / ".clyde" / "skills").symlink_to(shared, target_is_directory=True)
        self.assertFalse(own_skill(_named("linked")))
        with self.assertRaises(ValueError):
            remove_skill(_named("linked"))
        self.assertTrue(root.exists())

    def test_a_linked_skill_in_clydes_folder_loses_the_link_not_its_target(self) -> None:
        target = _skill(self.home / "elsewhere", "pointed")
        own = self.home / ".clyde" / "skills"
        own.mkdir(parents=True)
        (own / "pointed").symlink_to(target, target_is_directory=True)
        remove_skill(_named("pointed"))
        self.assertFalse((own / "pointed").exists())
        self.assertTrue((target / "SKILL.md").exists())


class TestOwnServers(PluginHomeCase):
    def test_a_server_in_settings_json_is_removed_and_the_rest_kept(self) -> None:
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(json.dumps({"model": "x", "mcpServers": {"a": {"command": "a"}, "b": {"command": "b"}}}))
        self.assertEqual(user_server_file("a"), self.settings)
        self.assertEqual(remove_user_server("a"), {"command": "a"})
        data = json.loads(self.settings.read_text())
        self.assertEqual((data["model"], list(data["mcpServers"])), ("x", ["b"]))

    def test_a_server_only_in_settings_toml_is_never_edited(self) -> None:
        toml = self.home / ".clyde" / "settings.toml"
        toml.parent.mkdir(parents=True, exist_ok=True)
        toml.write_text('[mcpServers.t]\ncommand = "t"\n')
        self.assertEqual(user_server_file("t"), toml)
        self.assertIsNone(remove_user_server("t"))
        self.assertIn("t", load_servers(toml))

    def test_an_unreadable_settings_file_is_not_overwritten(self) -> None:
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text("[1, 2]")
        with self.assertRaises(ValueError):
            remove_user_server("a")
        self.assertEqual(self.settings.read_text(), "[1, 2]")


if __name__ == "__main__":
    unittest.main()
