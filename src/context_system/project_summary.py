from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from ..token_estimation import rough_token_count
from .models import ProjectSummary

_README_NAMES = ("readme.md", "readme.rst", "readme.txt", "readme")
_HEADING = re.compile(r"^#{1,6}\s")


def build_project_summary(
    workspace_root: str | Path,
    *,
    max_readme_tokens: int = 600,
) -> ProjectSummary:
    root = Path(workspace_root).expanduser().resolve()
    readme = _find_readme(root)
    excerpt = ""
    if readme is not None:
        try:
            excerpt = _excerpt(readme.read_text(encoding="utf-8", errors="replace"), max_readme_tokens)
        except OSError:
            readme = None
    return ProjectSummary(
        readme_path=readme if excerpt else None,
        readme_excerpt=excerpt,
        entry_points=_python_scripts(root) + _package_json_entries(root),
    )


def _find_readme(root: Path) -> Path | None:
    try:
        files = {p.name.lower(): p for p in root.iterdir() if p.is_file()}
    except OSError:
        return None
    return next((files[name] for name in _README_NAMES if name in files), None)


def _excerpt(text: str, max_tokens: int) -> str:
    """Keep the title and whole leading sections that fit the token budget."""
    sections: list[list[str]] = [[]]
    for line in text.strip().splitlines():
        if _HEADING.match(line) and sections[-1]:
            sections.append([])
        sections[-1].append(line)

    kept = ""
    for section in sections:
        candidate = "\n".join(filter(None, [kept, "\n".join(section).strip()]))
        if rough_token_count(candidate) > max_tokens:
            break
        kept = candidate
    if kept:
        return kept if kept == text.strip() else kept + "\n...[truncated]"
    # First section alone is over budget: hard-cut it (rough_token_count is chars // 4).
    return text.strip()[: max_tokens * 4].rstrip() + "\n...[truncated]"


def _python_scripts(root: Path) -> tuple[str, ...]:
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    scripts = data.get("project", {}).get("scripts", {})
    if not isinstance(scripts, dict):
        return ()
    return tuple(f"{name} -> {target} (pyproject)" for name, target in scripts.items())


def _package_json_entries(root: Path) -> tuple[str, ...]:
    try:
        data = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    if not isinstance(data, dict):
        return ()
    entries: list[str] = []
    if isinstance(data.get("main"), str):
        entries.append(f"main -> {data['main']} (package.json)")
    bin_field = data.get("bin")
    if isinstance(bin_field, str):
        entries.append(f"{data.get('name', 'bin')} -> {bin_field} (package.json)")
    elif isinstance(bin_field, dict):
        entries.extend(f"{name} -> {target} (package.json)" for name, target in bin_field.items())
    return tuple(entries)
