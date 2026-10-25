"""SkillSpector (github.com/NVIDIA/SkillSpector), bundled: scans the skills, plugins and MCP servers
ClydeCLI picks up from other agents before the model gets them.

Two stages, as SkillSpector runs them. The static stage always runs: fast (about 2 s), offline,
71 patterns. The LLM review runs only when ClydeCLI has a connected model SkillSpector can use
(Anthropic, or any OpenAI-compatible endpoint: NVIDIA, OpenRouter, OpenAI, DeepSeek, Ollama,
oMLX, ...), and only where a person is waiting anyway: plugin installs, items the static stage
flagged, and /skills scan. It can take minutes, so it never runs at startup.

Verdicts are cached by content hash in ~/.clyde/skill_scans.json, so only new or changed items are
scanned. DO_NOT_INSTALL keeps an item away from the model until the user approves that exact
content (/skills allow); CAUTION loads with a warning. A scanner that fails warns loudly (once per item, on
stderr and as a `scan_failed` trace event) and loads: a broken scanner must not lock the user out of their
own tools. CLYDE_SKILL_SCAN=closed turns that around for people who would rather have nothing than something
unscanned: an item whose scan failed is held back (CLYDE_SKILL_SCAN=off loads everything unscanned).

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
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SAFE, CAUTION, BLOCK, ERROR = "SAFE", "CAUTION", "DO_NOT_INSTALL", "ERROR"
_TIMEOUT_STATIC, _TIMEOUT_LLM = 120, 300   # a review that takes longer is skipped, not waited for
_CHUNK_SKILLS, _CHUNK_WORKERS = 30, 4   # a scan costs ~2 s plus ~0.25 s per file: big plugins go in parallel chunks
_RETRY_AFTER = 24 * 3600                # a scan that failed is not repeated at every launch


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
        """Kept from the model: a DO_NOT_INSTALL verdict nobody allowed, or, with CLYDE_SKILL_SCAN=closed, a scan that failed."""
        return not self.approved and (self.recommendation == BLOCK or (self.recommendation == ERROR and closed()))


def enabled() -> bool:
    return os.environ.get("CLYDE_SKILL_SCAN", "").lower() not in ("off", "0", "false")


def closed() -> bool:
    """CLYDE_SKILL_SCAN=closed: an item whose scan failed is held back instead of loaded. The default is open (warn and load), so a
    broken scanner never locks anyone out of their own tools."""
    return os.environ.get("CLYDE_SKILL_SCAN", "").lower() == "closed"


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
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _store(key: str, entry: dict[str, Any]) -> None:
    """Write one entry into the freshest cache: a scan takes seconds, and other sessions save meanwhile."""
    cache = _load_cache()
    cache[key] = entry
    _save_cache(cache)


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


def _verdict_from_scan_result(result: ScanResult, llm: bool = False) -> Verdict:
    """Convert an in-house ScanResult into a skill_scan Verdict."""
    return Verdict(
        name=result.name,
        recommendation=result.recommendation,
        score=result.score,
        severity=result.severity,
        findings=[f"{f.rule_id} {f.severity}: {f.message}" for f in result.findings],
        llm=llm,
        approved=False,
    )


def _provider_from_env(env: dict[str, str]) -> tuple[Any, str | None]:
    """Build a provider object and model from the env dict produced by llm_env().

    Returns (provider, model), or (None, None) when no reviewable provider is configured.
    """
    prov = env.get("SKILLSPECTOR_PROVIDER")
    model = env.get("SKILLSPECTOR_MODEL")
    if not prov or not model:
        return None, None
    if prov == "anthropic":
        key = env.get("ANTHROPIC_API_KEY", "")
        if not key:
            return None, None
        os.environ["ANTHROPIC_API_KEY"] = key
        from src.providers.anthropic import AnthropicProvider

        return AnthropicProvider(name="anthropic"), model
    if prov == "openai_compatible":
        key = env.get("SKILLSPECTOR_COMPAT_API_KEY", "")
        base = env.get("SKILLSPECTOR_COMPAT_BASE_URL", "")
        if not key or not base:
            return None, None
        os.environ["SKILLSPECTOR_COMPAT_API_KEY"] = key
        from src.providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            name="clyde-review", base_url=base, key_env="SKILLSPECTOR_COMPAT_API_KEY"
        ), model
    return None, None


def _to_verdicts(results: list[ScanResult], env: dict[str, str] | None = None) -> list[Verdict]:
    """Run optional LLM review over scan results and convert them to Verdicts."""
    from src.security.scanner.llm_review import enhance_with_llm

    provider, model = _provider_from_env(env) if env else (None, None)
    verdicts: list[Verdict] = []
    for result in results:
        llm_reviewed = False
        if provider and model:
            try:
                result = enhance_with_llm(result, provider, model)
                llm_reviewed = True
            except Exception:
                pass
        verdicts.append(_verdict_from_scan_result(result, llm=llm_reviewed))
    return verdicts


def scan(path: Path, *, recursive: bool = False, env: dict[str, str] | None = None) -> list[Verdict]:
    """Scan with the in-house security scanner, replacing SkillSpector.

    The static scan always runs. The LLM review runs when `env` names a provider
    (built by llm_env / default_llm_env); otherwise static scan only.
    """
    if sys.stderr.isatty():
        label = " with LLM review" if env else ""
        print(
            f"\x1b[2m♠ Scanning {path.name}{label}…\x1b[0m",
            end="",
            file=sys.stderr,
            flush=True,
        )
    try:
        from src.security.scanner import scan as inhouse_scan

        results = inhouse_scan(path, recursive=recursive)
    except Exception as e:
        return [Verdict(path.name, ERROR, findings=[f"scan failed: {type(e).__name__}: {e}"])]
    finally:
        if sys.stderr.isatty():
            print("\r\x1b[2K", end="", file=sys.stderr, flush=True)
    return _to_verdicts(results, env)


# What a plugin can make ClydeCLI load (src/plugins.py). The rest of its folder (a repo's packages, tests,
# docs) never reaches the model or runs, and scanning it all overruns the timeout.
_PLUGIN_PARTS = ("skills", "hooks", "tools", ".mcp.json")


def check(kind: str, name: str, path: Path, *, env: dict[str, str] | None = None, rescan: bool = False) -> Verdict:
    """The cached verdict for this exact content, scanning it when it is new or changed. An LLM
    review (`env`) replaces a static-only verdict; a flagged static verdict is reviewed when `env` is given.
    A plugin is judged by the parts ClydeCLI loads, not its whole folder."""
    if kind != "plugin":
        return _check(kind, name, path, env, rescan)
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / path.name
        staged.mkdir()
        for part in _PLUGIN_PARTS:
            src = path / part
            if src.is_dir():
                shutil.copytree(src, staged / part)
            elif src.is_file():
                shutil.copy2(src, staged / part)
        return _check(kind, name, staged, env, rescan)


def _chunks(path: Path, tmp: Path) -> list[Path]:
    """`path` itself, or when it holds many skills, folders of at most _CHUNK_SKILLS skills each (the first
    also carries everything that isn't a skill, e.g. hooks and .mcp.json)."""
    skills = sorted(d for d in (path / "skills").iterdir() if d.is_dir()) if (path / "skills").is_dir() else []
    if len(skills) <= _CHUNK_SKILLS:
        return [path]
    chunks = []
    for i in range(0, len(skills), _CHUNK_SKILLS):
        chunk = tmp / f"{path.name}-{i // _CHUNK_SKILLS}"
        (chunk / "skills").mkdir(parents=True)
        for d in skills[i:i + _CHUNK_SKILLS]:
            shutil.copytree(d, chunk / "skills" / d.name)
        if i == 0:
            for rest in (p for p in path.iterdir() if p.name != "skills"):
                shutil.copytree(rest, chunk / rest.name) if rest.is_dir() else shutil.copy2(rest, chunk / rest.name)
        chunks.append(chunk)
    return chunks


def _worst(name: str, verdicts: list[Verdict]) -> Verdict:
    """One verdict for several: the worst recommendation, every finding. A BLOCK stands even if another
    part failed to scan; otherwise any failed part makes the whole an ERROR, since it was not fully inspected."""
    rank = {SAFE: 0, ERROR: 1, CAUTION: 2, BLOCK: 3}
    worst = max(verdicts, key=lambda v: (rank.get(v.recommendation, 1), v.score))
    failed = next((v for v in verdicts if v.recommendation == ERROR), None)
    if failed and worst.recommendation != BLOCK:
        return Verdict(name, ERROR, findings=failed.findings)
    return Verdict(name, worst.recommendation, worst.score, worst.severity,
                   [f"{v.name}: {f}" if len(verdicts) > 1 else f for v in verdicts for f in v.findings], all(v.llm for v in verdicts))


def _scan_chunked(name: str, path: Path, env: dict[str, str] | None) -> Verdict:
    with tempfile.TemporaryDirectory() as tmp:
        chunks = _chunks(path, Path(tmp))
        if len(chunks) == 1:
            return next(iter(scan(path, env=env)), Verdict(name, ERROR, findings=["empty report"]))
        with ThreadPoolExecutor(_CHUNK_WORKERS) as pool:
            parts = list(pool.map(lambda c: next(iter(scan(c, env=env)), Verdict(c.name, ERROR, findings=["empty report"])), chunks))
    return _worst(name, parts)


_announced: set[str] = set()


def _announce_failure(kind: str, name: str, verdict: Verdict) -> None:
    """A scan that failed says so, once per item per process: on stderr (loud, with the reason), and in the trace as `scan_failed`.
    Without this an item whose scan failed loaded unscanned and nobody was told."""
    if verdict.recommendation != ERROR or f"{kind}:{name}" in _announced:
        return
    _announced.add(f"{kind}:{name}")
    reason = "; ".join(verdict.findings)[:160] or "no reason given"
    from src.agent import trace
    trace.record("scan_failed", kind=kind, name=name, reason=reason, closed=closed())
    outcome = ("held back, because CLYDE_SKILL_SCAN=closed (set it to off to load it anyway)" if closed()
               else "loaded WITHOUT a scan (CLYDE_SKILL_SCAN=closed holds such items back)")
    print(f"\x1b[33m⚠ Scanner could not scan {kind} {name}: {reason}. It is {outcome}.\x1b[0m", file=sys.stderr, flush=True)


def _check(kind: str, name: str, path: Path, env: dict[str, str] | None, rescan: bool) -> Verdict:
    verdict = _check_cached_or_scan(kind, name, path, env, rescan)
    _announce_failure(kind, name, verdict)
    return verdict


def _check_cached_or_scan(kind: str, name: str, path: Path, env: dict[str, str] | None, rescan: bool) -> Verdict:
    if not enabled():
        return Verdict(name, SAFE)
    where = str(path) if kind == "skill" else ""
    key, content = _key(kind, name, where, _load_cache()), digest(path)
    entry = _load_cache().get(key) or {}
    cached = Verdict(**entry["verdict"]) if entry.get("hash") == content and "verdict" in entry else None
    failed = entry.get("failed") or {}
    if (not rescan and env is None and failed.get("hash") == content and time.time() - failed.get("at", 0) < _RETRY_AFTER
            and cached is None):
        return Verdict(name, ERROR, findings=["an earlier scan failed; trying again within a day or on /skills scan"])
    needs_review = cached is not None and env is not None and not cached.llm and cached.recommendation != SAFE
    if cached is not None and not rescan and not needs_review:
        return cached
    verdict = _scan_chunked(name, path, env)
    verdict.name, verdict.approved = name, bool(cached and cached.approved)
    if verdict.recommendation == ERROR:
        # a timeout or a missing report says nothing about the content, so no verdict is kept; the failure is
        # remembered so the next launches don't pay for the same timeout
        if env is None:
            _store(key, {**entry, "path": where, "failed": {"hash": content, "at": time.time()}})
        return verdict
    _store(key, {"hash": content, "path": where, "verdict": asdict(verdict)})
    return verdict


def _key(kind: str, name: str, where: str, cache: dict[str, Any]) -> str:
    """Cache key for one item. Skills with the same name in different folders (a plugin's copy and an
    agents' copy) hold different content, so a second folder gets its own key instead of overwriting the
    first one's verdict, which made every load scan both again."""
    base = f"{kind}:{name}"
    owner = (cache.get(base) or {}).get("path")
    return base if owner in (None, where) else f"{base} ({where})"


def prescan(items: list[tuple[str, Path]]) -> None:
    """Judge every new or changed skill in `items` using the in-house scanner."""
    if not enabled():
        return
    cache = _load_cache()
    judged = {e["hash"]: e["verdict"] for e in cache.values() if isinstance(e, dict) and "hash" in e and "verdict" in e}
    results: dict[str, dict[str, Any]] = {}
    pending: dict[str, tuple[list[tuple[str, str, str]], Path]] = {}
    for name, path in items:
        where = str(path)
        key, content = _key("skill", name, where, cache), digest(path)
        entry = cache.get(key) or {}
        cache[key] = {**entry, "path": where}
        failed = entry.get("failed") or {}
        if (entry.get("hash") == content and "verdict" in entry) or (
                failed.get("hash") == content and time.time() - failed.get("at", 0) < _RETRY_AFTER):
            continue
        if content in judged:
            results[key] = {"hash": content, "path": where, "verdict": {**judged[content], "name": name, "approved": False}}
        elif all(p.parent == path for p in path.rglob("SKILL.md")):
            if content not in pending:
                pending[content] = ([], path)
            pending[content][0].append((key, name, where))
    for content, (entries, path) in pending.items():
        try:
            from src.security.scanner import scan as inhouse_scan
            scan_results = inhouse_scan(path, recursive=False)
        except Exception:
            scan_results = []
        verdicts = _to_verdicts(scan_results)
        verdict = verdicts[0] if verdicts else Verdict(path.name, ERROR, findings=["scan failed: no results"])
        if verdict.recommendation == ERROR:
            continue   # a failed scan says nothing: leave it to check(), which remembers the failure
        for key, name, where in entries:
            results[key] = {"hash": content, "path": where, "verdict": asdict(verdict)}
    if results:
        fresh = _load_cache()
        fresh.update(results)
        _save_cache(fresh)


def approve(kind: str, name: str) -> bool:
    """Allow this exact content despite its verdict (every folder's copy of a skill); False when it has no verdict yet."""
    cache = _load_cache()
    base = f"{kind}:{name}"
    entries = [e for k, e in cache.items() if (k == base or k.startswith(f"{base} (")) and isinstance(e, dict) and "verdict" in e]
    for entry in entries:
        entry["verdict"]["approved"] = True
    if entries:
        _save_cache(cache)
    return bool(entries)


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
    if verdict.recommendation != ERROR:   # a failed scan says nothing about the content, so keep no verdict: the next connect tries again
        _store(key, {"hash": content, "verdict": asdict(verdict)})
    _announce_failure("mcp", server, verdict)
    return verdict
