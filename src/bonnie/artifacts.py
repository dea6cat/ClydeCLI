"""Artifacts: the files Clyde wrote or edited for the user, found from the saved sessions of the current project.

A file counts when a Write, Edit or NotebookEdit call that named it succeeded (changes made by shell commands aren't
visible here, the same limit /rewind has). Reading a file back is limited to files in that list that still sit inside
the project folder the session ran in, so the API can't be used to read anything else on the machine.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from src.agent.session import Session

EDIT_TOOLS = {"write": "file_path", "edit": "file_path", "notebookedit": "notebook_path"}
MAX_TEXT = 400_000          # how much of a text file the preview reads
MAX_RAW = 50_000_000        # the largest file served for download or an image preview
IMAGES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml"}
_DOCUMENTS = {"md", "markdown", "txt", "rst", "csv", "log"}
_CODE = {"py", "js", "mjs", "ts", "tsx", "jsx", "css", "json", "yaml", "yml", "toml", "ini", "cfg", "sh", "bash", "zsh", "rb", "go", "rs", "java",
         "kt", "swift", "c", "h", "cpp", "hpp", "cs", "php", "sql", "xml", "dart", "lua", "r", "ipynb", "env", "lock"}


def classify(path: str | Path) -> tuple[str, str]:
    """(kind, group): kind says how to preview it (html, markdown, image, text, other), group which filter it belongs under."""
    ext = Path(path).suffix.lower().lstrip(".")
    if ext in ("html", "htm"):
        return "html", "page"
    if ext in ("md", "markdown"):
        return "markdown", "document"
    if ext in IMAGES:
        return "image", "image"
    if ext in _DOCUMENTS:
        return "text", "document"
    if ext in _CODE:
        return "text", "code"
    return "other", "other"


def collect(sessions: list[Session], title_of: Callable[[Session], str]) -> list[dict[str, Any]]:
    """One row per file, newest session first. `sessions` come newest first; a file keeps the newest session that touched it."""
    rows: dict[str, dict[str, Any]] = {}
    for session in sessions:
        failed: set[str] = set()
        uses: list[tuple[str, str, str]] = []
        for message in session.conversation.messages:
            if isinstance(message.content, str):
                continue
            for block in message.content:
                kind = getattr(block, "type", None)
                if kind == "tool_result" and getattr(block, "is_error", False):
                    failed.add(block.tool_use_id)
                elif kind == "tool_use":
                    field = EDIT_TOOLS.get(str(block.name).lower())
                    raw = (block.input or {}).get(field) if field else None
                    if isinstance(raw, str) and raw.strip():
                        uses.append((block.id, block.name, raw))
        for use_id, tool, raw in uses:
            if use_id in failed:
                continue
            path = Path(raw).expanduser()
            path = path if path.is_absolute() else Path(session.cwd) / path
            key = str(path)
            row = rows.get(key)
            if row is None:
                kind, group = classify(path)
                rows[key] = {"path": key, "name": path.name, "tool": tool, "kind": kind, "group": group, "changes": 1, "cwd": session.cwd,
                             "updated": session.updated_at, "session": {"id": session.session_id, "title": title_of(session)}}
            else:
                row["changes"] += 1
                if row["session"]["id"] == session.session_id:
                    row["tool"] = tool
    for row in rows.values():
        path = Path(row["path"])
        try:
            stat = path.stat()
            row["exists"], row["size"] = path.is_file(), stat.st_size
        except OSError:
            row["exists"], row["size"] = False, 0
        try:
            row["folder"] = str(path.parent.relative_to(row["cwd"])) if row["cwd"] else str(path.parent)
        except ValueError:
            row["folder"] = str(path.parent)
        if row["folder"] == ".":
            row["folder"] = ""
    return list(rows.values())


def public(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k != "cwd"}


def find(path: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The row for `path`, only if it is a listed artifact that still resolves to somewhere inside its project folder
    (so a link swapped in afterwards can't point the preview at another file)."""
    for row in rows:
        if row["path"] == str(Path(path)) and row["cwd"]:
            try:
                if Path(row["path"]).resolve().is_relative_to(Path(row["cwd"]).resolve()):
                    return row
            except OSError:
                return None
    return None


def read_text(path: Path) -> dict[str, Any]:
    """The text of a file for the preview, cut at MAX_TEXT; a file that isn't text comes back as kind other."""
    with path.open("rb") as f:
        data = f.read(MAX_TEXT + 1)
    if b"\x00" in data[:8192]:
        return {"kind": "other"}
    return {"text": data[:MAX_TEXT].decode("utf-8", errors="replace"), "truncated": len(data) > MAX_TEXT}


def reveal(path: Path) -> bool:
    """Show the file in the system file manager (Finder on macOS)."""
    command = ["open", "-R", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path.parent)]
    try:
        return subprocess.run(command, timeout=5, check=False, capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
