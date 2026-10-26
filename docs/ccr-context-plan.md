# CCR Context Plan: Reversible Compression + Retrieve Tool

**Status:** Built on `feat/ccr-context`, measured first. Across 37 local repos the whole context prompt is 1.1k–3k tokens and
every repo already loses 1–3 sections to a hard cut (instruction files at 4,000 chars, README at 600 tokens, git status at
2,000 chars). So the reversible part makes those existing cuts reversible (`src/context_system/context_cache.py`,
`RetrieveContext`), instruction files included since they were already being cut, and `/context` shows per-section cache
alignment. Not built: summarizing sections that fit (little to save), the `cache_key` prefix and microcompact ordering.
**Owner:** context_system
**Priority:** Moderate

## Background

ClydeCLI builds a context prompt on every turn (`src/context_system/builder.py`) from workspace snapshot, git status, README excerpt, entry points, code map, and memory files (CLYDE.md / CLAUDE.md / AGENTS.md). As a session grows, this context competes with conversation history for the model's context window.

Microcompact (`src/context_system/microcompact.py`) already clears old tool results and strips images/documents when the cache is cold. Auto-compact runs at 80% of the window. But these are lossy: once a tool result is cleared, the model cannot re-read it without re-running the tool.

CCR (Cache-Conscious Retrieval) adds two ideas:

1. **Reversible compression** — compress context sections (especially memory files and long file dumps) into a smaller, model-readable summary, with a way to retrieve the original on demand.
2. **Retrieve tool** — a new tool the model can call to fetch the full original content of a compressed section, keyed by a stable reference.
3. **Cache-alignment flagging** — mark context sections whose boundaries align with the provider's prompt-cache prefix, so repeated turns reuse cached tokens instead of re-prefilling.

## Design

### Reversible compression

Add a compression stage in `build_context_prompt` (or a new `compress` module in `context_system`) that:

- Runs on each context section (workspace snapshot, git, claude_md, project summary, code map).
- Produces a compressed summary (fewer tokens, still useful) plus a stable content hash and section reference.
- The compressed summary goes into the system prompt; the original is stored in a small local store (`~/.clyde/context_cache/`).
- Each compressed section gets a reference id like `ctx:sha256:<hash>` stored alongside the summary.

The model sees only summaries, but if it needs detail it can call the retrieve tool.

### Retrieve tool

A new tool `RetrieveContext` (or `ctx_retrieve`):

- Input: `{ reference: string }` where reference is a `ctx:sha256:...` id.
- Returns: the original full section content.
- The tool is advertised in the system prompt alongside each compressed section:
  > Section "Project Instructions" compressed (420 tokens). Original available via RetrieveContext(reference="ctx:sha256:abc123...").

This keeps the prompt small while preserving the ability to drill in when the model needs it.

### Cache-alignment flagging

Providers cache prompt prefixes (Anthropic's prompt caching, OpenAI's cached input tokens, etc.). When a context section's boundary aligns with a cache checkpoint, subsequent turns re-use the cached prefix instead of re-prefilling those tokens.

Add to `context_analyzer.py`:

- A `cache_alignment` flag on each `ContextCategory` (or a new dataclass) indicating whether the section ends at a cache-friendly boundary.
- A `suggest_compact_point` hint: where to split context so the cached prefix is maximally reused.
- Exposed in `format_context_as_markdown` and `/context` output so users can see which sections are cache-aligned.

Also add a `cache_key` prefix mechanism: the system prompt is built as `style_prompt + context_prompt`. If `context_prompt` is stable across turns (same compressed summaries), its hash can be used as a cache key so the provider caches it once.

## Files to touch

| File | Change |
|------|--------|
| `src/context_system/builder.py` | Add optional compression of sections; emit `ctx:sha256:...` references; store originals locally |
| `src/context_system/models.py` | Add `cache_aligned: bool` and `reference: str | None` to `ContextCategory` |
| `src/context_system/context_analyzer.py` | Add cache-alignment analysis; flag cache-friendly boundaries; suggest compact points |
| `src/context_system/microcompact.py` | Optional: prefer clearing non-cache-aligned sections first |
| `src/tool_system/registry.py` or new `src/tool_system/tools/context_retrieve.py` | Register the `RetrieveContext` tool |
| `src/agent/agent_loop.py` | Wire `RetrieveContext` into the tool loop; handle retrieved content in conversation |
| `docs/features.md` | Document `/context` cache-alignment output and RetrieveContext tool |

## Implementation notes

- Compression should be deterministic: same input → same reference id, so cache hits work across turns.
- Originals are stored under `~/.clyde/context_cache/<hash>/` and TTL'd (e.g., 7 days) to avoid unbounded growth.
- The retrieve tool counts as a tool turn; the model pays for it only when it needs detail.
- Cache-alignment is advisory: the model decides whether to call retrieve; Clyde only flags boundaries.

## After the scanner ships

This is a follow-up plan item. The in-house security scanner (`feat/inhouse-security-scanner`) ships first. Once merged to main, this CCR plan can be picked up as the next context_system investment.
