"""Leaves the parts of a user's global instruction file that are about another language out of a small local model's prompt.

The model only names the language a section is about, which a small model does reliably; code decides what to drop.
A section is dropped only when the answer is a language the project does not use, so any doubt keeps it."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from src.config import clyde_home

LANGUAGES = ("python", "dart", "flutter", "javascript", "typescript", "java", "kotlin", "swift", "rust", "go", "ruby", "php", "csharp", "cpp")
_MANIFESTS = {
    "pyproject.toml": {"python"}, "requirements.txt": {"python"}, "setup.py": {"python"}, "Pipfile": {"python"},
    "pubspec.yaml": {"dart", "flutter"}, "package.json": {"javascript", "typescript"}, "tsconfig.json": {"typescript", "javascript"},
    "Cargo.toml": {"rust"}, "go.mod": {"go"}, "Gemfile": {"ruby"}, "composer.json": {"php"}, "Package.swift": {"swift"},
    "pom.xml": {"java", "kotlin"}, "build.gradle": {"java", "kotlin"}, "build.gradle.kts": {"java", "kotlin"}, "CMakeLists.txt": {"cpp"},
}
_SUFFIXES = {".csproj": {"csharp"}, ".sln": {"csharp"}}
_SECTION_CHARS = 900   # the start of a section is enough to tell what it is about
_ASK = ("{section}\n\nWhich programming language or framework is the text above specifically about? "
        "Answer with one lowercase word: {options}, or general if it applies to any language.")


def project_languages(root: Path) -> frozenset[str]:
    """Languages the project uses, read from its manifests in the root and one folder down (a monorepo's app folders)."""
    found: set[str] = set()
    try:
        folders = [root, *(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name != "node_modules")]
        for folder in folders:
            for entry in folder.iterdir():
                found |= _MANIFESTS.get(entry.name, set()) | _SUFFIXES.get(entry.suffix, set())
    except OSError:
        return frozenset(found)
    return frozenset(found)


def split_sections(text: str) -> list[str]:
    """The text cut before each `## ` heading (outside code fences); the first piece is whatever precedes the first heading."""
    pieces, in_fence = [""], False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        if line.startswith("## ") and not in_fence:
            pieces.append("")
        pieces[-1] += line
    return pieces


def keep_relevant(text: str, languages: frozenset[str], label: Callable[[str], str]) -> str:
    """`text` without the sections `label` says are about a language that is not in `languages`; a note says how many went."""
    preamble, *sections = split_sections(text)
    kept = [s for s in sections if (word := label(s)) not in LANGUAGES or word in languages]
    dropped = len(sections) - len(kept)
    note = f"\n(Left out {dropped} section{'s' * (dropped != 1)} about other languages.)" if dropped else ""
    return preamble + "".join(kept) + note


def _cache_file() -> Path:
    return clyde_home() / "section_languages.json"


def _read_cache() -> dict[str, str]:
    try:
        data = json.loads(_cache_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def model_labeler(provider: Any, model: str) -> Callable[[str], str]:
    """Names the language a section is about, with the user's own model. An answer is remembered by the section's text,
    so each section costs one call ever; a failed call answers "general" (keep the section) and is not remembered."""
    from src.providers.base import ProviderError, stream_with_retry
    from src.providers.types import Conversation, Message
    cache = _read_cache()

    def label(section: str) -> str:
        key = hashlib.sha256(section.encode("utf-8")).hexdigest()
        if key in cache:
            return cache[key]
        ask = _ASK.format(section=section.strip()[:_SECTION_CHARS], options=", ".join(LANGUAGES))
        try:
            reply = stream_with_retry(provider, Conversation("", [Message.user(ask)]), model, (), lambda _chunk: None, retries=0)
        except ProviderError:
            return "general"
        words = re.findall(r"[a-z]+", (reply.message.text or "").lower())
        cache[key] = words[0] if words and words[0] in LANGUAGES else "general"
        try:
            _cache_file().parent.mkdir(parents=True, exist_ok=True)
            _cache_file().write_text(json.dumps(cache, indent=2), encoding="utf-8")
        except OSError:
            pass
        return cache[key]

    return label


def for_project(root: Path, provider: Any, model: str) -> Callable[[str], str] | None:
    """The filter for a project's instruction files, or None when its languages are unknown (then nothing is left out)."""
    languages = project_languages(root)
    if not languages:
        return None
    label = model_labeler(provider, model)
    return lambda text: keep_relevant(text, languages, label)
