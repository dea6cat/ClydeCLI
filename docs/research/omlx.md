# oMLX on an 18 GB Mac — what its SSD cache buys

*Research note, 2026-10-22. Machine: Apple M3 Pro, 18 GB. oMLX v0.7.2 (mlx 0.32.4, mlx-lm 0.31.4.dev, native Metal kernels built). One run per number.*

## The headline

After a server restart, oMLX answered a 3,555-token prompt as fast as a warm repeat: its SSD cache tier restored the prompt's KV state instead of recomputing it. That restart case, not a warm repeat, is where it pays: Clyde starts and stops oMLX's server, and an 18 GB Mac evicts models often.

## Measurements

Model `Parable-Qwen3-4B-Claude-Fable-5-MLX-8bit` (Qwen3 4B, 8-bit, 4.2 GB), served from `~/.lmstudio/models` through Clyde's own start path, window 8192 (`CLYDE_CONTEXT_TOKENS`).

| Request | First token |
|---|---|
| Cold: SSD and in-memory caches cleared first | 7.56 s |
| Warm: the same prompt again | 1.01 s |
| After a full server restart | **0.96 s** (101% of the way from cold back to warm) |

Peak oMLX resident memory 3.25 GB, swap 0 throughout, memory pressure normal. The cache left 468 MB in `~/.omlx/cache`.

**Method.** The server was started through `OMLXProvider._ensure_server()` with the `balanced` memory guard. Both caches were cleared through oMLX's admin API (`/admin/api/ssd-cache/clear`, `/hot-cache/clear`) right before the cold request, so an earlier run's cache could not make "cold" look fast. A throwaway request (`hi`) loaded the model before each timed one, so loading isn't counted. The prompt was the first 15,000 characters of `src/agent/agent_loop.py` plus a one-word question, streamed with `max_tokens` 4. First token means the first chunk carrying generated content or reasoning: oMLX streams an empty role chunk before prefill, and timing that one gave a meaningless 0.01 s in an earlier attempt. The restart killed the `omlx-server` process and started it again through the same path. A watcher checked swap and memory pressure every 2 seconds and would have stopped the run.

## The memory guard on 18 GB

| Guard | Ceiling it gave | 4.2 GB model |
|---|---|---|
| `safe` | 1.58 GB, with 8.2 GB free + inactive | refused: HTTP 507 "does not fit under the dynamic memory ceiling" |
| `balanced` | 4.1 GB with nothing loaded, rising as needed | loaded; numbers above |
| `custom 9 GB` | 9.0 GB fixed | not timed; checked that it starts with that ceiling |

`safe` reserves at least 6 GB, so on this machine it needs about 10 GB free before it loads even a 4 GB model. Clyde starts oMLX with `balanced` and offers the others in `/settings`.

## Other measurements

- Download through oMLX's own downloader: `mlx-community/Qwen3-0.6B-4bit`, 351 MB in 14 s.
- Clyde's installer from a clean folder (pinned source, uv venv, Metal kernels): 33.5 s with uv's package cache warm from an earlier install. A first install downloads 111 packages, so expect minutes.

## What this does not show

- **No comparison with LM Studio or plain mlx-lm on this prompt.** The lift measured here is oMLX's restart against its own cold and warm runs. For a cross-engine number, [Michael Hannecke's comparison](https://medium.com/macoclock/mlx-lm-vs-omlx-i-was-wrong-about-the-winner-8f36be328069) (M4 Max, 64 GB, oMLX 0.4.4, 8k-token prefix) found warm prefill and decode a tie, while after a restart mlx-lm recovered 51% of the way to warm and oMLX 97%. That is a different machine and version, not a measurement of ours.
- One model, one run per number. Directional, not a benchmark.
- Resident memory comes from `ps` and undercounts the Metal memory oMLX wires for the model.
- oMLX's community benchmarks list no M3 Pro results at 18 GB or less, so there is no published number for this machine to check against.
