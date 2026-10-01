from __future__ import annotations

from pathlib import Path

from .models import ClaudeMdContext, ClaudeMdFile

# Memory files, one per location: the first name that exists wins, so a repo that keeps the same
# notes for several agents doesn't load them twice. CLYDE.md is ClydeCLI's own name; the others are
# read so files written for other harnesses keep working: CLAUDE.md (Claude Code), AGENTS.md (Codex,
# Cursor, Copilot), GEMINI.md (Gemini CLI), .cursorrules (Cursor) and copilot-instructions (Copilot).
# CLYDE.local.md / CLAUDE.local.md is the personal, usually gitignored, per-project file.
_MEMORY_NAMES = ("CLYDE.md", "CLAUDE.md", "AGENTS.md", "GEMINI.md")
_PROJECT_GROUPS = (
    (*_MEMORY_NAMES, ".cursorrules", ".github/copilot-instructions.md"),
    tuple(f".clyde/{n}" for n in _MEMORY_NAMES),
    (".claude/CLAUDE.md",),
    ("CLYDE.local.md", "CLAUDE.local.md"),
)
_USER_GROUPS = (
    tuple(f".clyde/{n}" for n in _MEMORY_NAMES),
    (".claude/CLAUDE.md",),
)


def _first_existing(base: Path, names: tuple[str, ...]) -> Path | None:
    for rel in names:
        path = (base / rel).resolve()
        if path.is_file():
            return path
    return None


def load_claude_md_context(
    workspace_root: str | Path,
    *,
    cwd: str | Path | None = None,
    max_files: int = 6,
    max_chars_per_file: int = 4_000,
    max_total_chars: int = 12_000,
) -> ClaudeMdContext:
    root = Path(workspace_root).expanduser().resolve()
    current = Path(cwd).expanduser().resolve() if cwd is not None else root

    candidates: list[Path] = []

    home = Path.home()
    for group in _USER_GROUPS:
        path = _first_existing(home, group)
        if path is not None and path not in candidates:
            candidates.append(path)

    for base in _walk_up_to_root(current, root):
        for group in _PROJECT_GROUPS:
            path = _first_existing(base, group)
            if path is not None and path not in candidates:
                candidates.append(path)

    files: list[ClaudeMdFile] = []
    total_chars = 0
    truncated = False
    for path in candidates:
        if len(files) >= max_files or total_chars >= max_total_chars:
            truncated = True
            break
        if not path.exists() or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if not content:
            continue
        if len(content) > max_chars_per_file:
            content = content[: max_chars_per_file - 32].rstrip() + "\n...[truncated]"
            truncated = True
        remaining = max_total_chars - total_chars
        if remaining <= 0:
            truncated = True
            break
        if len(content) > remaining:
            content = content[: max(0, remaining - 32)].rstrip() + "\n...[truncated]"
            truncated = True
        total_chars += len(content)
        files.append(ClaudeMdFile(path=path, content=content))

    return ClaudeMdContext(files=tuple(files), truncated=truncated)


def _walk_up_to_root(current: Path, root: Path) -> list[Path]:
    current = current.resolve()
    root = root.resolve()
    if current != root:
        try:
            current.relative_to(root)
        except ValueError:
            current = root

    bases: list[Path] = []
    node = current
    while True:
        if node not in bases:
            bases.append(node)
        if node == root:
            break
        parent = node.parent
        if parent == node:
            break
        node = parent
    return bases
