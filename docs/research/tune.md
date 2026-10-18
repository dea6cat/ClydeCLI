# `clyde tune` — measured, per model, not guessed

*Research note, 2026-10-08. `clyde tune` starts a throwaway `ollama serve` on a free port per setting; the user's own server is never reconfigured. Ollama 0.35.1.*

| Model | Setting | Memory | Agreement with default | Verdict |
|---|---|---|---|---|
| Qwen2.5-Coder 3B Q8_0 | default | 4.69 GB | — | baseline |
| Qwen2.5-Coder 3B Q8_0 | flash + q8_0 KV | **4.17 GB** | **100% alike** | shipped by tune |
| Qwen2.5-Coder 3B Q8_0 | q4_0 KV | lower | **32% alike**, buried fact lost, 12–18% slower | refused |
| Llama 3.2 3B | default @ 91k window | 12.07 GB | — | baseline |
| Llama 3.2 3B | flash + q4_0 @ 131k window | **6.48 GB** | 95% alike, recall kept | shipped by tune |

**The point of the table:** the same setting (q4_0 KV) is refused on one model and passed on another. That is why tune's quality gate is per model, never global.

**How agreement is measured:** greedy probes (temperature 0, seed 1) — deterministic and discriminating; the existing 0–1 eval scored ~1.0 on a 3B model and could not tell settings apart, so it was not usable as a gate.

**Recall probe:** a buried fact at 10/50/90% depth of a ~28,000-token prompt. Default and q8_0 found it every time; q4_0 missed all three. The probe now reads 70% of each candidate's window, capped at 24,000 tokens.

**Noise found by running it for real:** cold first load reads ~0.4 GB low (priming load added); the tool-call eval once sampled unseeded and rejected good settings on one bad sample (fixed: seeded, one retry on a second seed); the same setting measured 31–41 tok/s across runs (fixed: best of two timed runs, 8% noise band).

LM Studio was left out of tune: its load API accepts `flash_attention` but silently ignores it for MLX models, and rejects KV-cache quantization keys.
