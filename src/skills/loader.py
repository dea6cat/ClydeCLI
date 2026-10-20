from __future__ import annotations

from src.config import clyde_home

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .argument_substitution import parse_argument_names
from .frontmatter import parse_frontmatter
from .model import PromptSkill


def _candidate_user_skills_dirs() -> list[Path]:
    """Return candidate user-skill directories in priority order.
    Priority:
      1) $CLYDE_SKILLS_DIR (project-specific)
      2) $CLAUDE_SKILLS_DIR (TS-compatible override)
      3) ~/.clyde/skills (current project default)
      4) ~/.claude/skills (TS-compatible default)
      5) ~/.agents/skills, ~/.codex/skills, ~/.copilot/skills, ~/.gemini/skills (other agents' SKILL.md
         folders, read in place so they stay in sync)
    """
    env_primary = os.environ.get("CLYDE_SKILLS_DIR")
    env_ts = os.environ.get("CLAUDE_SKILLS_DIR")
    dirs: list[Path] = []
    if env_primary:
        dirs.append(Path(env_primary).expanduser().resolve())
    if env_ts:
        p = Path(env_ts).expanduser().resolve()
        if p not in dirs:
            dirs.append(p)
    # Defaults
    for d in (clyde_home() / "skills", *(Path.home() / name / "skills" for name in (".claude", ".agents", ".codex", ".copilot", ".gemini"))):
        p = d.expanduser().resolve()
        if p not in dirs:
            dirs.append(p)
    return dirs


@dataclass
class SkillRegistry:
    by_name: Dict[str, PromptSkill]

    def __init__(self) -> None:
        self.by_name = {}

    def register(self, skill: PromptSkill) -> None:
        self.by_name[skill.name] = skill

    def get(self, name: str) -> Optional[PromptSkill]:
        return self.by_name.get(name)

    def list(self) -> List[PromptSkill]:
        return list(self.by_name.values())

    def clear(self) -> None:
        self.by_name.clear()


_REGISTRY = SkillRegistry()


def clear_skill_registry() -> None:
    _REGISTRY.clear()


def load_skills_from_dir(base_dir: str | Path, *, loaded_from: str = "skills", confine_to: Path | None = None) -> List[PromptSkill]:
    """Skills under `base_dir`. With `confine_to` (a repository's own skills: the repo is untrusted), a skills folder, skill
    folder or SKILL.md whose real location is outside it (a committed symlink to ~/.ssh/id_rsa, say) is skipped."""
    base = Path(base_dir).expanduser().resolve()
    if not base.exists() or not base.is_dir():
        return []
    if confine_to is not None and not base.is_relative_to(confine_to):
        return []

    skills: List[PromptSkill] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        skill_name = entry.name
        md_path = entry / "SKILL.md"
        if not md_path.exists():
            continue
        if confine_to is not None and not (entry.resolve().is_relative_to(confine_to) and md_path.resolve().is_relative_to(confine_to)):
            continue
        content = md_path.read_text(encoding="utf-8")
        parsed = parse_frontmatter(content)
        fm = parsed.frontmatter
        body = parsed.body

        description = str(fm.get("description") or _extract_description(body) or f"Skill: {skill_name}")
        user_invocable = bool(fm.get("user-invocable", True))
        disable_model_invocation = bool(fm.get("disable-model-invocation", False))
        when_to_use = fm.get("when_to_use")
        when_to_use = str(when_to_use) if when_to_use is not None else None
        version = fm.get("version")
        version = str(version) if version is not None else None
        model = fm.get("model")
        model = str(model) if model is not None else None

        allowed_tools = _as_str_list(fm.get("allowed-tools"))
        arg_names = parse_argument_names(fm.get("arguments"))
        context = "fork" if str(fm.get("context", "")).lower() == "fork" else "inline"
        agent = fm.get("agent")
        agent = str(agent) if agent is not None else None
        effort = fm.get("effort")
        effort = str(effort) if effort is not None else None
        paths = _as_str_list(fm.get("paths"))
        if paths == []:
            paths = None

        skill = PromptSkill(
            name=skill_name,
            description=description,
            loaded_from=loaded_from,
            user_invocable=user_invocable,
            disable_model_invocation=disable_model_invocation,
            content_length=len(body),
            is_hidden=not user_invocable,
            skill_root=str(entry),
            when_to_use=when_to_use,
            version=version,
            model=model,
            allowed_tools=allowed_tools,
            arg_names=arg_names,
            context=context,
            agent=agent,
            effort=effort,
            paths=paths,
            markdown_content=body,
        )
        skills.append(skill)
    return skills


def _cleared(skill: PromptSkill) -> bool:
    """Whether SkillSpector's verdict lets this skill reach the model (see src/skill_scan.py)."""
    if not skill.skill_root:
        return True
    from src.security import skill_scan

    return not skill_scan.check("skill", skill.name, Path(skill.skill_root)).blocked


def all_skill_dirs(
    *,
    project_root: str | Path | None = None,
    user_skills_dir: str | Path | None = None,
) -> list[tuple[Path, str, Path | None]]:
    """Every skills folder as (folder, loaded_from, confine_to), lowest priority first: a later skill of the same name wins."""
    found: list[tuple[Path, str, Path | None]] = []
    if user_skills_dir is not None:
        user_dirs = [Path(user_skills_dir).expanduser().resolve()]
    else:
        user_dirs = _candidate_user_skills_dirs()
        # Enabled plugins' skills sit below every user skill folder.
        from src.plugins import skill_dirs
        found += [(plugin_dir, "plugin", None) for plugin_dir in skill_dirs()]
    found += [(user_dir, "user", None) for user_dir in reversed(user_dirs)]

    managed_env = os.environ.get("CLYDE_MANAGED_SKILLS_DIR")
    if managed_env:
        found.append((Path(managed_env).expanduser().resolve(), "managed", None))

    if project_root is not None:
        pr = Path(project_root).expanduser().resolve()
        found += [(pr / ".clyde" / "skills", "project", pr), (pr / ".claude" / "skills", "project", pr)]
    return found


def get_all_skills(
    *,
    project_root: str | Path | None = None,
    user_skills_dir: str | Path | None = None,
) -> Sequence[PromptSkill]:
    clear_skill_registry()
    loaded = [s for base, loaded_from, confine_to in all_skill_dirs(project_root=project_root, user_skills_dir=user_skills_dir)
              for s in load_skills_from_dir(base, loaded_from=loaded_from, confine_to=confine_to)]
    from src.security import skill_scan
    # New skills are scanned together here, so _cleared mostly reads cached verdicts.
    skill_scan.prescan([(s.name, Path(s.skill_root)) for s in loaded if s.skill_root])
    for s in loaded:
        if _cleared(s):
            _REGISTRY.register(s)
    return _REGISTRY.list()


def get_registered_skill(name: str) -> Optional[PromptSkill]:
    return _REGISTRY.get(name)


def _extract_description(body: str) -> Optional[str]:
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        return stripped[:200]
    return None


def _as_str_list(val) -> List[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x) for x in val if str(x)]
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return []
        if "," in s:
            return [x.strip() for x in s.split(",") if x.strip()]
        return [s]
    return [str(val)]
