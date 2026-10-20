"""Skill problems the loader passes over without a word, for /doctor.

The rules follow the tree validator in Harness² (google-research/harness2, Apache 2.0), adapted to how Clyde loads
skills: a folder the loader skips, frontmatter it cannot read, a skill the model cannot tell when to use or that nobody
can invoke, and a script the skill runs but does not ship.
"""

from __future__ import annotations

import re
from pathlib import Path

from .frontmatter import parse_frontmatter
from .loader import all_skill_dirs

# A script run from the skill's own folder: `python3 scripts/pack.py` or `${CLAUDE_SKILL_DIR}/scripts/run.sh`.
# A longer path such as `tools/scripts/x.py` belongs to some repository, not to the skill, and is not checked.
_SCRIPT_REF = re.compile(r"(?<![\w./-])(?:\$\{?\w+\}?/)?(scripts/[\w./-]+\.(?:py|sh|js|mjs))")


def _short(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home):] if text.startswith(home + "/") else text


def lint_skill_dir(base: Path, confine_to: Path | None = None) -> tuple[int, list[str]]:
    """(skills checked, problems) for one skills folder, read the way load_skills_from_dir reads it."""
    base = base.expanduser()
    if not base.is_dir():
        return 0, []
    if confine_to is not None and not base.resolve().is_relative_to(confine_to):
        return 0, [f"{_short(base)}: points outside the project, so none of its skills load"]
    checked, problems = 0, []
    for entry in sorted(base.iterdir()):
        # A dot folder (.trash, .git) is kept out of the way on purpose.
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        md = entry / "SKILL.md"
        if not md.exists():
            problems.append(f"{_short(entry)}: no SKILL.md, so it is skipped")
            continue
        if confine_to is not None and not (entry.resolve().is_relative_to(confine_to) and md.resolve().is_relative_to(confine_to)):
            problems.append(f"{_short(entry)}: points outside the project, so it is skipped")
            continue
        checked += 1
        text = md.read_text(encoding="utf-8", errors="replace")
        parsed = parse_frontmatter(text)
        fm = parsed.frontmatter
        if text.lstrip().startswith("---") and parsed.body == text:
            problems.append(f"{_short(md)}: frontmatter is never closed with ---, so all of it is read as the body")
        if not str(fm.get("description") or "").strip():
            problems.append(f"{_short(md)}: no `description:`, so the model sees only its first line and may never use it")
        if bool(fm.get("disable-model-invocation", False)) and not bool(fm.get("user-invocable", True)):
            problems.append(f"{_short(md)}: disable-model-invocation and user-invocable: false, so nothing can invoke it")
        for ref in sorted(set(_SCRIPT_REF.findall(parsed.body))):
            if not (entry / ref).is_file():
                problems.append(f"{_short(md)}: runs {ref}, which the skill does not ship")
    return checked, problems


def lint_skills(*, project_root: str | Path | None = None) -> tuple[int, list[str]]:
    """(skills checked, problems) across every folder get_all_skills reads."""
    checked, problems, seen = 0, [], set()
    for base, _, confine_to in all_skill_dirs(project_root=project_root):
        # Run from the home folder, the project's .clyde/skills is ~/.clyde/skills: check it once.
        if base.resolve() in seen:
            continue
        seen.add(base.resolve())
        count, found = lint_skill_dir(base, confine_to)
        checked += count
        problems += found
    return checked, problems
