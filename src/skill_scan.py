"""SkillSpector (github.com/NVIDIA/SkillSpector), bundled: scans the skills, plugins and MCP servers
ClydeCLI picks up from other agents before the model gets them.

Two stages, as SkillSpector runs them. The static stage always runs: fast (about 2 s), offline,
71 patterns. The LLM review runs only when ClydeCLI has a connected model SkillSpector can use
(Anthropic, or any OpenAI-compatible endpoint: NVIDIA, OpenRouter, OpenAI, DeepSeek, Ollama,
LM Studio, ...), and only where a person is waiting anyway: plugin installs, items the static stage
flagged, and /skills scan. It can take minutes, so it never runs at startup.

Verdicts are cached by content hash in ~/.clyde/skill_scans.json, so only new or changed items are
scanned. DO_NOT_INSTALL keeps an item away from the model until the user approves that exact
content (/skills allow); CAUTION loads with a warning. A scanner that fails warns and loads: a
broken scanner must not lock the user out of their own tools.

An MCP server's code isn't local, so its tool list is scanned instead: each tool becomes a SKILL.md
whose description and parameters SkillSpector's tool-poisoning checks read. The server process has
already started by then; the scan decides whether the model sees its tools.
"""
from __future__ import annotations

from src.config import clyde_home

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SAFE, CAUTION, BLOCK, ERROR = "SAFE", "CAUTION", "DO_NOT_INSTALL", "ERROR"
_TIMEOUT_STATIC, _TIMEOUT_LLM = 120, 1800


@dataclass
class Verdict:
    """SkillSpector's answer for one scanned item."""
    name: str
    recommendation: str             # SAFE | CAUTION | DO_NOT_INSTALL | ERROR
    score: int = 0                  # 0-100 risk
    severity: str = ""
    findings: list[str] = field(default_factory=list)   # "ID SEVERITY: what"
    llm: bool = False               # whether the LLM review ran
    approved: bool = False          # the user allowed this exact content despite the verdict

    @property
    def blocked(self) -> bool:
        return self.recommendation == BLOCK and not self.approved


def enabled() -> bool:
    return os.environ.get("CLYDE_SKILL_SCAN", "").lower() not in ("off", "0", "false")


def cache_path() -> Path:
    return clyde_home() / "skill_scans.json"


def _load_cache() -> dict[str, Any]:
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(cache: dict[str, Any]) -> None:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    """Content hash of a file or folder (paths and bytes), so a changed item is scanned again."""
    h = hashlib.sha256()
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    for f in files:
        h.update(str(f.relative_to(path) if f != path else f.name).encode())
        try:
            h.update(f.read_bytes())
        except OSError:
            continue
    return h.hexdigest()


def _exe() -> list[str] | None:
    """The skillspector command shipped beside this Python, else on PATH."""
    beside = Path(sys.executable).parent / "skillspector"
    found = str(beside) if beside.is_file() else shutil.which("skillspector")
    return [found] if found else None


def llm_env(provider: Any, model: str | None) -> dict[str, str] | None:
    """SkillSpector's provider settings for ClydeCLI's connected model, or None when SkillSpector
    can't use it (then the scan runs with --no-llm)."""
    if provider is None or not model:
        return None
    name = getattr(provider, "name", "")
    if name == "cardShuffle":
        from src.providers.card_shuffle import deck
        top = deck("high-roller", provider._candidates())
        if not top:
            return None
        real, _, real_model = top[0].partition(":")
        return llm_env(provider.registry.get(real), real_model)
    if name == "anthropic":
        key = getattr(provider, "api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        return {"SKILLSPECTOR_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": key, "SKILLSPECTOR_MODEL": model} if key else None
    base = getattr(provider, "base_url", None)
    if name in ("ollama", "ollama-cloud") and getattr(provider, "host", None):
        base = f"{provider.host}/v1"
    key = getattr(provider, "api_key", None) or ("ollama" if name == "ollama" else None)
    if not base or not key:
        return None
    return {"SKILLSPECTOR_PROVIDER": "openai_compatible", "SKILLSPECTOR_COMPAT_API_KEY": key,
            "SKILLSPECTOR_COMPAT_BASE_URL": base, "SKILLSPECTOR_MODEL": model}


def default_llm_env() -> dict[str, str] | None:
    """llm_env for the saved default model, for scans run outside the REPL (plugin installs)."""
    try:
        from src.config import get_default_model
        from src.providers import build_registry, keys, resolve

        keys.load_into_env()
        model = get_default_model()
        resolved = resolve(build_registry(), model) if model else None
        return llm_env(*resolved) if resolved else None
    except Exception:
        return None


def _verdicts(report: dict[str, Any]) -> list[Verdict]:
    """One Verdict per scanned skill in a single- or multi-skill JSON report."""
    out = []
    for s in report.get("skills") if report.get("multi_skill") else [report]:
        risk, meta = s.get("risk_assessment") or {}, s.get("metadata") or {}
        skill = s.get("skill")
        name = skill.get("name") if isinstance(skill, dict) else str(skill or "")
        findings = [f"{i.get('id')} {i.get('severity')}: {str(i.get('finding') or i.get('explanation') or '')[:120]}"
                    for i in s.get("issues") or []]
        done = s.get("analysis_completeness") or report.get("analysis_completeness") or {}
        if not findings and isinstance(done, dict) and done.get("status") not in (None, "complete"):
            # CAUTION with nothing found means SkillSpector couldn't inspect everything: say what it couldn't.
            reasons = sorted({str(x.get("message") or x.get("reason_code")) for x in done.get("ledger_exceptions") or []})
            findings = [f"partial scan: {r[:120]}" for r in reasons] or [f"partial scan ({done.get('status')})"]
        out.append(Verdict(name, str(risk.get("recommendation") or ERROR), int(risk.get("score") or 0),
                           str(risk.get("severity") or ""), findings, bool(meta.get("meta_analysis_applied"))))
    return out


def scan(path: Path, *, recursive: bool = False, env: dict[str, str] | None = None) -> list[Verdict]:
    """Run SkillSpector on a skill folder or file (recursive: each subfolder with a SKILL.md is its own
    skill). The LLM review runs when `env` names a provider; otherwise --no-llm."""
    exe = _exe()
    if exe is None:
        return [Verdict(path.name, ERROR, findings=["skillspector is not installed"])]
    if sys.stderr.isatty():
        print(f"\x1b[2m♠ SkillSpector is scanning {path.name}{' with an LLM review (this can take minutes)' if env else ''}…\x1b[0m",
              file=sys.stderr)
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        cmd = [*exe, "scan", str(path), "--format", "json", "--output", str(report)]
        cmd += ["--recursive"] if recursive else []
        cmd += [] if env else ["--no-llm"]
        try:
            subprocess.run(cmd, env={**os.environ, **(env or {})}, capture_output=True, text=True,
                           timeout=_TIMEOUT_LLM if env else _TIMEOUT_STATIC)
            return _verdicts(json.loads(report.read_text(encoding="utf-8")))
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            return [Verdict(path.name, ERROR, findings=[f"scan failed: {type(e).__name__}: {e}"[:160]])]


def check(kind: str, name: str, path: Path, *, env: dict[str, str] | None = None, rescan: bool = False) -> Verdict:
    """The cached verdict for this exact content, scanning it when it is new or changed. An LLM
    review (`env`) replaces a static-only verdict; a flagged static verdict is reviewed when `env` is given."""
    if not enabled():
        return Verdict(name, SAFE)
    key, content = f"{kind}:{name}", digest(path)
    cache = _load_cache()
    entry = cache.get(key) or {}
    cached = Verdict(**entry["verdict"]) if entry.get("hash") == content and "verdict" in entry else None
    needs_review = cached is not None and env is not None and not cached.llm and cached.recommendation != SAFE
    if cached is not None and not rescan and not needs_review:
        return cached
    verdict = next(iter(scan(path, env=env)), Verdict(name, ERROR, findings=["empty report"]))
    verdict.name, verdict.approved = name, bool(cached and cached.approved)
    cache[key] = {"hash": content, "verdict": asdict(verdict)}
    _save_cache(cache)
    return verdict


def approve(kind: str, name: str) -> bool:
    """Allow this exact content despite its verdict; False when it has no verdict yet."""
    cache = _load_cache()
    entry = cache.get(f"{kind}:{name}")
    if not entry or "verdict" not in entry:
        return False
    entry["verdict"]["approved"] = True
    _save_cache(cache)
    return True


def cached_verdicts() -> dict[str, Verdict]:
    """Every cached verdict, keyed kind:name."""
    return {k: Verdict(**v["verdict"]) for k, v in _load_cache().items() if isinstance(v, dict) and "verdict" in v}


def _yaml_str(text: str) -> str:
    return json.dumps(str(text), ensure_ascii=False)   # a JSON string is a valid YAML scalar


def mcp_tools_skill_dir(server: str, tools: list[dict[str, Any]], into: Path) -> Path:
    """Write an MCP server's tools as one SKILL.md each under `into`/<server>, for a recursive scan."""
    root = into / server
    for i, tool in enumerate(tools):
        props = ((tool.get("inputSchema") or {}).get("properties") or {})
        params = "".join(f"\n  - name: {_yaml_str(p)}\n    description: {_yaml_str((spec or {}).get('description', ''))}"
                         for p, spec in props.items())
        folder = root / f"{i:03d}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {_yaml_str(tool.get('name', f'tool{i}'))}\ndescription: {_yaml_str(tool.get('description', ''))}\n"
            f"parameters:{params or ' []'}\n---\nMCP tool `{tool.get('name', '')}` from server `{server}`.\n", encoding="utf-8")
    return root


def check_mcp(server: str, tools: list[dict[str, Any]], *, env: dict[str, str] | None = None) -> Verdict:
    """The worst verdict over an MCP server's tool list, cached by the list's content."""
    if not enabled() or not tools:
        return Verdict(server, SAFE)
    with tempfile.TemporaryDirectory() as tmp:
        root = mcp_tools_skill_dir(server, tools, Path(tmp))
        key, content = f"mcp:{server}", digest(root)
        cache = _load_cache()
        entry = cache.get(key) or {}
        if entry.get("hash") == content and "verdict" in entry:
            return Verdict(**entry["verdict"])
        verdicts = scan(root, recursive=True, env=env) or [Verdict(server, ERROR, findings=["empty report"])]
    rank = {SAFE: 0, ERROR: 1, CAUTION: 2, BLOCK: 3}
    worst = max(verdicts, key=lambda v: (rank.get(v.recommendation, 1), v.score))
    verdict = Verdict(server, worst.recommendation, worst.score, worst.severity,
                      [f"{v.name}: {f}" for v in verdicts for f in v.findings], any(v.llm for v in verdicts))
    cache[key] = {"hash": content, "verdict": asdict(verdict)}
    _save_cache(cache)
    return verdict
