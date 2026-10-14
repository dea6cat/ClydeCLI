"""`clyde acp install zed`: add Clyde to Zed's settings.json as a custom ACP agent, so it shows up under External Agents.

Zed's settings are JSON with comments and trailing commas, and the user owns the file, so the entry is inserted as text:
every comment and every other setting stays exactly as it was. Nothing is written unless the result still parses.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

AGENT_NAME = "Clyde"
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')


def settings_path() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "Zed" / "settings.json"
    return Path.home() / ".config" / "zed" / "settings.json"


def _blank_comments(text: str) -> str:
    """The text with every comment replaced by spaces (newlines kept), so indexes still match the original."""
    out, i = [], 0
    while i < len(text):
        string = _STRING.match(text, i)
        if string:
            out.append(string.group())
            i = string.end()
        elif text.startswith("//", i) or text.startswith("/*", i):
            end = text.find("\n" if text[i + 1] == "/" else "*/", i + 2)
            end = len(text) if end < 0 else end + (0 if text[i + 1] == "/" else 2)
            out.append("".join(c if c == "\n" else " " for c in text[i:end]))
            i = end
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _parse(text: str) -> dict[str, Any] | None:
    """The settings as a dict, or None when the file isn't a JSON object (comments and trailing commas are fine)."""
    try:
        data = json.loads(_TRAILING_COMMA.sub(r"\1", _blank_comments(text)))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _top_level_value(clean: str, key: str) -> int | None:
    """Index of the first character of the top-level `key`'s value in comment-free text, or None when it isn't there."""
    depth, i, expect_key = 0, 0, False
    while i < len(clean):
        string = _STRING.match(clean, i)
        if string:
            if depth == 1 and expect_key and json.loads(string.group()) == key:
                after_colon = clean.index(":", string.end()) + 1
                return after_colon + len(clean[after_colon:]) - len(clean[after_colon:].lstrip())
            expect_key, i = False, string.end()
            continue
        c = clean[i]
        if c in "{[":
            depth, expect_key = depth + 1, c == "{" and depth == 0
        elif c in "}]":
            depth -= 1
        elif c == "," and depth == 1:
            expect_key = True
        i += 1
    return None


def _entry(command: str, indent: str) -> str:
    return (f'{indent}"{AGENT_NAME}": {{\n{indent}  "type": "custom",\n{indent}  "command": {json.dumps(command)},\n'
            f'{indent}  "args": ["--acp"]\n{indent}}}')


def with_agent(text: str, command: str) -> str | None:
    """`text` with the Clyde agent added under `agent_servers`, or None when the file isn't a JSON object."""
    if _parse(text) is None:
        return None
    clean = _blank_comments(text)
    open_brace = clean.index("{")
    value = _top_level_value(clean, "agent_servers")
    if value is None:
        body = f'\n  "agent_servers": {{\n{_entry(command, "    ")}\n  }}'
        empty = clean[open_brace + 1:].strip() == "}"
        return text[:open_brace + 1] + body + ("" if empty else ",") + text[open_brace + 1:]
    line = text[text.rfind("\n", 0, value) + 1:value]
    indent = line[:len(line) - len(line.lstrip())] + "  "
    brace = value + 1
    empty = clean[brace:].lstrip().startswith("}")
    return text[:brace] + "\n" + _entry(command, indent) + ("" if empty else ",") + text[brace:]


def install(console: Any, command: str | None = None, path: Path | None = None, assume_yes: bool = False) -> int:
    """Add Clyde to Zed's settings after showing the change. 0 on success or when already there, 1 when it can't."""
    command = command or shutil.which("clyde")
    if command is None:
        console.print("[red]Can't find the clyde command on PATH.[/red] Run this where clyde is installed, then try again.")
        return 1
    path = path or settings_path()
    old = path.read_text(encoding="utf-8") if path.exists() else "{\n}\n"
    data = _parse(old)
    if data is None:
        console.print(f"[red]Can't read {path} as JSON.[/red] Nothing was changed. Add this under \"agent_servers\" by hand:")
        console.print(f'"{AGENT_NAME}": {{"type": "custom", "command": "{command}", "args": ["--acp"]}}', markup=False, highlight=False)
        return 1
    existing = (data.get("agent_servers") or {}).get(AGENT_NAME)
    if existing is not None:
        same = existing.get("command") == command and existing.get("args") == ["--acp"]
        console.print(f"Zed already has an agent named {AGENT_NAME} in {path}" + ("." if same else
                      f", with a different command ({existing.get('command')}). Edit or delete that entry, then run this again."))
        return 0
    new = with_agent(old, command)
    if new is None or _parse(new) is None:
        console.print(f"[red]Couldn't add the agent to {path} safely.[/red] Nothing was changed.")
        return 1
    console.print(f"Adding {AGENT_NAME} to {path}:")
    console.print("".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "before", "after", n=2)), markup=False, highlight=False)
    if not assume_yes:
        from rich.prompt import Confirm
        if not Confirm.ask("Write it?", default=True, console=console):
            console.print("Nothing was changed.")
            return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".clyde-bak"))
    path.write_text(new, encoding="utf-8")
    console.print(f"[green]✓ Done.[/green] In Zed, open the agent panel's + menu: {AGENT_NAME} is under External Agents.")
    return 0
