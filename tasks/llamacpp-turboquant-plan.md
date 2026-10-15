# Implementation Plan: smaller local LLMs through a llama.cpp provider

## VERDICT (2026-10-15): do not build this plan
Read this block first. The sections below are the research record and contain conclusions that were later withdrawn, so do not act on them without checking the dated results.

- **Phase 1 (llama.cpp provider, turbo KV types, fork binary): do not build.** The only cache setting with KL divergence under 0.001 is `q8_0` K and V. Ollama already offers it, and Clyde's tuner (`src/tuning/tune.py`) already tries flash attention with `q8_0` or `q4_0` KV cache, sizes the window with the same bit counts measured here (`_KV_SHRINK`), and gates each candidate on speed, memory, answer similarity, tool calling and long-context recall. The fork's best pair, `q8_0`/`turbo3`, is about 1.4x smaller than `q8_0`, about 10x its KL divergence, and 9% to 19% slower at decode, and it would add a nightly binary, a supply-chain check and a new provider.
- **Per-channel K scale: research only, do not build.** It halves the KL divergence of `q4_0` on Qwen3-4B, but that is still 20x to 60x worse than `q8_0`, it was tested on one model, it needs per-model calibration, and it is a core-graph patch on a nightly fork. The patch survives as commit `1b9fca6d9` on the fork's local branch `research/k-compression`, not pushed.
- **`q4_0` KV cache is lossy, and the existing gate is lenient on purpose.** KL divergence 0.04 to 0.054, and the top next-token choice changes 7% to 11% of the time, on two models and three texts. Clyde's tuner allows it only for the `chat` and `quick` profiles, where answer similarity of 0.8 is accepted. That is a reasonable design for users who opted into lossy output, and no code change is needed. Keep `allow_q4` narrow.
- **MoE tasks 6 to 9: do not build. Task 7 (rate a MoE by active parameters) is contraindicated.** On Apple Silicon the whole file must fit in memory. Rating the 30B-A3B by its 3B active parameters would have called it a fit on this 18 GB Mac, and running it crashed the machine. Total file size is the right rating. Do not revive Task 7.
- **"Never start a model that does not fit"** was a rule for the provider that is not being built. Ollama and LM Studio make their own fit checks. It stays here as a lesson.
- **Gap, stated plainly:** MoE was never run through Ollama or LM Studio on this machine. The CPU-only numbers (gpt-oss-20b: about 14.5 tok/s decode, about 16 tok/s prefill) come from the fork's binary, so they are not Clyde's user experience. The verdict holds either way: if Ollama runs MoE models, there is nothing to build, and if it does not, the fork's GPU path is broken on this machine.
- **Durability:** the fork commit is the only research code that survived the Mac's restart. The probe scripts, scale files and raw logs were lost. The verdict does not depend on them.
- Evidence: see "KL divergence, two models, three texts", "Speed benchmark: results" and "Gate 2 results" below.

### External evidence checked on 2026-10-15 (web, not reproduced here)
- **Ollama FAQ** (docs.ollama.com/faq): default cache type is `f16`, one global setting for all models, needs flash attention. It describes `q8_0` as about half the memory "with a very small loss in precision" and `q4_0` as about a quarter "with a small-medium loss in precision" that "may be more noticeable at higher context sizes". It warns the effect depends on model and task, and that models with a high GQA count (for example Qwen2) may be more affected. It has no per-model check.
- **LocalBench** (localbench.substack.com, KV cache benchmark): Gemma 4 and Qwen 3.6, BF16 weights, about 250,000 tokens, KL on top-40 log-probabilities, one machine. Qwen 3.6 27B `q8_0` KL 0.024, 35B-A3B `q8_0` 0.039, Qwen `q4_0` 0.087 to 0.117. Gemma 4 31B `q8_0` 0.108, Gemma 4 26B-A4B `q8_0` 0.377 and `q4_0` 1.088 (68% top-1). The author says "q8_0 is practically lossless" is wrong for Gemma. This agrees with our direction (`q8_0` far better than `q4_0`, Qwen less sensitive than Gemma). The absolute numbers are not comparable with ours: different models, weights, text, context and KL definition.
- **InventiveHQ** (inventivehq.com, KV cache quality benchmark): Qwen2.5-Coder-7B Q4_K_M, greedy, 12 prompts, difflib similarity to f16. `q8_0` 81.6% similar, `q4_0` 8.3%. On an M3 Max `q4_0` lost about 42% of decode speed (54.1 to 31.2 tok/s). It also says speed is not a quality signal, since `q4_0` was nearly as fast as f16 on an RTX 5060 Ti. Single model, 8K context, one run per config.
- **Consequences for the verdict:**
  - **`q8_0` is not safe for every model.** Our "`q8_0` is the only safe default" holds for Qwen3-4B and Llama-3.2-3B only. Gemma-class models show large `q8_0` divergence in the external data. A fixed default would be wrong. Clyde's tuner measures the user's own model on the user's own machine (answer similarity, tool calling, long-context recall) and falls back to the default setting if a candidate fails, which is the right design. Do not hardcode `q8_0` as a universal setting.
  - **The tuner's similarity measure is the same one InventiveHQ used (difflib on greedy replies).** At 81.6% for `q8_0` on one model, a strict profile with `min_fidelity` 0.95 would reject `q8_0` there. That is the tuner working as designed, but it means strict profiles may rarely get a cache change.
  - **`q4_0` speed loss on Metal is corroborated** by InventiveHQ (42% on M3 Max). We did not see it for same-type `q4_0` on an M3 Pro with this fork's build, so it depends on the build.
- **Harnesses examined and what they do with the KV cache:** Ollama (global setting, default `f16`, no check), llama.cpp server (`-ctk` and `-ctv`, default `f16`, no check), VLS (no KV compression, only a fit check before download), `turboquant-mlx` (own KV and weight compression, stress tests per model, large decode slowdowns at long context), `VeloxQuant-MLX` and `tqai` (no real runtime memory saving per their own READMEs). LM Studio's KV setting could not be confirmed from its own documentation, only from an SDK issue. opencode and Hermes are clients of an OpenAI-compatible server and do not manage the cache. I did not survey koboldcpp, Jan, vLLM or others, so "no other harness validates quality per model and machine" is not claimed.

## Overview
Let Clyde run big local models in less RAM. Techniques 1 and 2 come from the TurboQuant fork of llama.cpp
(`AtomicBot-ai/atomic-llama-cpp-turboquant-nightly`), technique 3 is a small patch on top of it, all reached through a new `llamacpp` provider:

1. **Turbo KV cache** (`turbo2`/`turbo3`/`turbo4`): the KV cache shrinks 3.8x to 6.4x versus f16, which is the RAM cost that grows with context.
2. **MoE expert placement**: keep experts in CPU RAM (`-ncmoe`, `--moe-cache`) or page them from the SSD (`--load-mode mmap`) so a Mixture-of-Experts model larger than VRAM or RAM still runs.

3. **Per-channel K scale** (found during Gate 1, not part of the fork): a static per-(layer, KV head, channel) scale divides K and multiplies Q before the cache write, so the product is unchanged and the cache needs no extra bits. On Qwen3-4B it made plain upstream `q4_0` K and V match `q8_0` on prose perplexity, but later tests on code text showed it hurts there (see "Generality tests"). Treat it as unproven and not a default.

Clyde does not implement quantization or streaming. It picks flags, starts `llama-server`, and talks to it over the OpenAI-compatible API, the way `lmstudio.py` drives `lms`.

## Out of scope
- TQ3_1S and TQ4_1S weight quantization. It needs re-quantized GGUFs and changes to `huggingface.py` and `best_fit.py`. Revisit only if KV-only proves worth it.
- Strata (`Niko1221/Strata`). It runs one 125B model, needs 46 GB or more, and is a separate product. Not integrated.
- Any platform except macOS arm64 until a gate passes on it.

## Decisions
- **Opt-in, never default.** The provider is only used when the user picks it or enables it in settings. No silent install, following `lmstudio.py`.
- **Pinned release.** The fork publishes nightly pre-releases. Clyde pins one tag and a SHA-256 in a constant. Bumping it is a deliberate commit that re-runs Gate 1. Candidate pin: tag `turboquant-9ca222f` (2026-10-06), macOS arm64 zip, SHA-256 `9bb38630dbbc6da7abc83c8eb93837f965ecd13015256570fbc39f8c508dbe67` (28 MB), signed Developer ID Application: AtomicMail Systems OU, team `MU9G7XKJUL`, `codesign --verify --strict` passes. GitHub publishes no digest, so this hash was computed from my own download.
- **Safe defaults.** K `q8_0` and V `q8_0` (KLD under 0.001 on two models and three texts). Anything smaller is an explicit setting with its cost stated (see "KL divergence").
- **Never start a model that does not fit.** The provider checks weights plus cache against the `fit.py` budget before launch and refuses otherwise. A model larger than memory crashed this Mac during Gate 2.
- **Channel scale is not a default.** It helped on prose and hurt on code, so it stays an experiment. If it is ever used, it needs a one-time per-model calibration (a 147 KB file for Qwen3-4B), and a model with no file gets no scale.
- **Fallback.** If `llama-server` fails to start or fails the health probe, Clyde falls back to Ollama or LM Studio with a visible message.
- **Verify before run.** Download over HTTPS into `~/.clyde/llamacpp/<tag>/`, check the SHA-256 and `codesign --verify --strict` (expected team ID `MU9G7XKJUL`, AtomicMail Systems OU).

## Gates
Nothing in a later phase starts until the gate before it passes.

### Gate 1: KV quality (manual, before any Clyde code). Partly done, see results
Machine: Apple M3 Pro, 18 GB. Model: Qwen3-4B-Instruct-2507 Q8_0 GGUF. Binaries: the macOS arm64 release, extracted to its own folder.

- Method: `llama-perplexity` on wikitext-2, `-c 512 --chunks 32 -fa on -ngl 99`. Baseline `q8_0`/`q8_0` = 8.8439, f16 = 8.8536. Standard error is about 0.29, so differences under 1% are not provable.
- **Pass:** within 2% of `q8_0`, no coherence failure in a short generation.
- **Why a gate:** the fork's own `docs/quality-benchmarks.md` still shows empty result tables and a "27x worse" failure note that nothing in the repo says was fixed.

Results, stock fork types (K / V): `q8_0`/`turbo3` +0.64% pass. `q8_0`/`turbo2` +0.88% pass. `q5_0`/`turbo2` +2.62% fail. `q4_0`/`turbo2` +3.63% fail. `turbo4`/`turbo3` +5.79% fail. `turbo3`/`turbo3` +26.9% fail, and `TURBO_LAYER_ADAPTIVE=7` makes it worse. CPU matches Metal, so the loss comes from the scheme and not from a Metal bug. Releases `6df272c` and `9ca222f` give the same numbers.

Results with the per-channel K scale (strength 0.5, calibrated on 939 tokens of wikitext):

| K / V | Avg bits | Size vs `q8_0` cache | Perplexity vs `q8_0` |
|---|---|---|---|
| `q4_0`/`q4_0` plain | 4.5 | 1.9x smaller | +2.20% fail |
| `q4_0`/`q4_0` scaled | 4.5 | 1.9x smaller | -0.29% pass |
| `q4_0`/`q5_0` scaled | 5.0 | 1.7x smaller | -0.38% pass |
| `q4_0`/`turbo3` scaled | 3.9 | 2.2x smaller | +0.10% pass |
| `q4_0`/`turbo2` scaled | 3.5 | 2.4x smaller | +0.98% pass |
| `turbo4`/`turbo3` scaled | 3.7 | 2.3x smaller | +1.53% pass |
| `turbo4`/`turbo2` scaled | 3.3 | 2.6x smaller | +2.12% fail |
| `turbo3`/`turbo3` scaled | 3.25 | 2.6x smaller | +4.04% fail |

Reading (first pass, wikitext only, superseded by the generality tests below): the scale looked like the larger win on prose. The fork patch is committed locally on branch `research/k-compression` of the fork (commit `1b9fca6d9`, not pushed). It is env-gated by `KV_CHSCALE_FILE` and covers only the `llm_graph_input_attn_kv` overload that Qwen3 uses.

Still open, and required before any Clyde code:
- Done: calibrate on code and test on different text (see "Generality tests": the scale does not generalize). Still open: chat text.
- A second, larger architecture (Llama or Gemma), and a model with Q4 weights.
- A KL-divergence run against f16 logits, and a short generation coherence check.
- Long context (8k to 16k) with a needle-in-a-haystack check, since that is where the cache matters.
- Decide the route: Clyde ships or builds a patched `llama-server`, or the scale goes upstream. If the scale cannot be proven general, fall back to `q8_0`/`turbo3` without a scale.
- Speed benchmark, below. Perplexity says nothing about tokens per second, and "smaller cache, no slowdown" is an expectation, not a result.

#### Speed benchmark: results (run 2026-10-15, Apple M3 Pro 18 GB, Qwen3-4B-Instruct Q8_0, Metal, `-fa on -p 512 -n 128 -r 3`)
Decode (tg) and prefill (pp) in tokens per second, with peak resident memory over the whole run (depths 0, 8k, 16k):

| K / V | pp 0 | pp 16k | tg 0 | tg 8k | tg 16k | Peak RSS |
|---|---|---|---|---|---|---|
| f16/f16 | 540 | 194 | 29.7 | 16.3 (noisy) | 19.7 (noisy) | 9.6 GB |
| `q8_0`/`q8_0` (my build) | 510 | 127 | 28.7 | 19.9 | 16.4 | 7.7 GB |
| `q8_0`/`q8_0` (release) | 513 | 127 | 27.7 | 20.9 | 16.4 | 7.6 GB |
| `q4_0`/`q4_0` plain | 527 | 135 | 29.0 | 21.0 | 16.7 | 6.2 GB |
| `q4_0`/`q4_0` scaled | 526 | 136 | 28.5 | 20.5 | 14.9 | 6.2 GB |
| `q8_0`/`turbo3` (release) | 520 | not run | 25.2 | 17.0 | not run | not recorded |
| `q4_0`/`turbo3` scaled (my build) | 129 | not run | 18.7 | not run | not run | not recorded |

Findings:
- Memory is the win: peak memory at 16k depth falls from 9.6 GB (f16) to 6.2 GB (`q4_0`). Short-context decode is unchanged.
- Compressed caches cost prefill speed at depth: about 135 tok/s at 16k against 194 for f16, roughly 30% slower.
- The scale file costs nothing at depth 0 (f16 29.3 with the file, 29.7 without). At 16k, scaled `q4_0` decodes at 14.9 against 16.7 for plain `q4_0` and 16.4 for `q8_0`, about 9% slower than `q8_0` with a standard deviation of 0.5. That missed the "no slower than `q8_0` at 16k" bar by a small margin, so I reran decode at 16k depth, interleaved over two rounds of two repetitions each. Means: `q8_0`/`q8_0` 16.1, plain `q4_0`/`q4_0` 16.5, scaled `q4_0`/`q4_0` 15.5 tok/s. Scaled is about 4% slower than `q8_0` and 6% slower than plain `q4_0`, but one scaled run had a standard deviation of 1.5, so a small real cost of the scale (under about 6%) is possible and not proven. This is a marginal miss of the proposed bar and is accepted as a known cost, to be re-measured on any model added later.
- Stock `q8_0`/`turbo3` works but is slower: decode is 9% lower at depth 0 and 19% lower at 8k than `q8_0`/`q8_0`. At 5.9 average bits it is also larger than scaled `q4_0`/`q4_0` at 4.5.
- `q4_0` K with `turbo3` V in my patched build is very slow (prefill 129 at depth 0, 6 at 8k depth, so I stopped it). The cause is untested. The likely cause is a missing fast attention path for that K/V pair on Metal, not `turbo3` itself, since the stock `q8_0`/`turbo3` run is fine. Either way, it is not usable as built.
- f16 numbers at 8k and 16k have a large standard deviation and are not reliable. The ordering of f16 decode speed by depth should not be read.
- Decision (speed only): `q4_0`/`q4_0`, plain or scaled, is smaller and as fast as or faster than any turbo option tested, so turbo types drop out of the first product unless a later test changes this. Whether plain or scaled is safe is decided by the quality tests below, not by speed.

#### Generality tests (run 2026-10-15)
Same machine, `-c 512 --chunks 32 -fa on`, perplexity. Q4 weights are `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` from `lmstudio-community` (2,497,280,448 bytes, SHA-256 `8cdb57cb…2641fc`, matches the Hugging Face listing). Scale files were calibrated on 939 tokens of wikitext or 1,407 tokens of Clyde's own Python (`fit.py` and `ollama.py`, which are excluded from the code test corpus).

| Weights | Test text | Config (K/V `q4_0`/`q4_0`) | Perplexity | vs `q8_0`/`q8_0` |
|---|---|---|---|---|
| Q8_0 | wikitext | plain | 9.0385 | +2.20% |
| Q8_0 | wikitext | scale calibrated on wikitext | 8.8183 | -0.29% |
| Q8_0 | wikitext | scale calibrated on code | 8.9677 | +1.40% |
| Q8_0 | code | plain | 5.1693 | -0.11% (base 5.1752) |
| Q8_0 | code | scale calibrated on wikitext | 5.2828 | +2.08% |
| Q8_0 | code | scale calibrated on code | 5.2891 | +2.20% |
| Q4_K_M | wikitext | plain | 9.2476 | +2.36% (base 9.0344) |
| Q4_K_M | wikitext | scale from the Q8 model, wikitext | 9.0527 | +0.20% |
| Q4_K_M | wikitext | scale from the Q4 model, wikitext | 9.1081 | +0.82% |
| Q4_K_M | wikitext | scale from the Q4 model, code | 9.1467 | +1.25% |

Checks: the scale patch is neutral at f16 on code (5.1790 without a file, 5.1791 and 5.1789 with the two files), so the code result is not a patch bug. The scale generator reproduces the original scale file exactly. Standard error is about 0.3 on wikitext and 0.17 on code, so differences under about 1% are suggestive, not proven.

Findings:
- **Q4 weights do not collapse.** `turboquant-mlx` warns that 3-bit K on 3-bit weights breaks long generation. `q4_0` K on Q4_K_M weights stayed within 0.2% to 2.4% on prose. Long generations were not tested here.
- **The scale does not generalize.** It helps on prose (+2.2% to -0.3%), and it hurts on code (-0.1% to +2.1%), even when calibrated on code. A scale calibrated on code text also costs more on prose than one calibrated on prose. The earlier "lossless" claim is withdrawn.
- **Plain `q4_0`/`q4_0` is text-dependent**: fine on code, +2.2% to +2.4% on prose. That is marginally over the 2% gate on prose and untested on chat.
- **No default can be named yet.** Both candidates sit at about the 2% gate on one text type or the other. The cause of the code loss is not understood.

#### Mixed K/V types, plain (Q8_0 weights, base `q8_0`/`q8_0`: wikitext 8.8439, code 5.1752)

| K / V | Avg bits | wikitext | code |
|---|---|---|---|
| `q8_0`/`q4_0` | 6.5 | 8.8636 (+0.22%) | 5.1735 (-0.03%) |
| `q8_0`/`turbo3` (stock fork) | 5.9 | 8.9009 (+0.64%) | 5.1806 (+0.10%) |
| `q5_0`/`q5_0` | 5.5 | 8.9188 (+0.85%) | 5.2362 (+1.18%) |
| `q5_0`/`q4_0` | 5.0 | 8.9236 (+0.90%) | 5.2539 (+1.52%) |

Findings:
- **K is the sensitive side, V is not.** Any K below 8 bits costs 0.85% to 1.5%. `q4_0` V costs nothing measurable at `q8_0` K.
- **Best quality: K `q8_0`, V `q4_0`, but it is unusable on Metal as built.** It is within noise of `q8_0`/`q8_0` on both text types, but its speed collapses: decode 23.7 against 28.7 tok/s and prefill 160 against 510 at depth 0, and at 8k depth decode falls to 1.8 tok/s and prefill to 5 tok/s (run stopped). `q4_0`/`turbo3` showed the same collapse, so the likely cause is that Metal has no fast attention path for mixed K/V types (not confirmed in the code). Stock `q8_0`/`turbo3` is fine, so the fork special-cases its own pair.
- **Same-type `q5_0`/`q5_0` is slow at decode**: 20.5 tok/s at depth 0 and 13.4 at 8k, against 28.7 and 19.9 for `q8_0`/`q8_0`, roughly 30% lower. Prefill is close to normal (492 at depth 0, 181 at 8k).
- **Speed-safe pairs on Metal, from all measurements:** `q8_0`/`q8_0`, plain `q4_0`/`q4_0`, and the fork's `q8_0`/`turbo3` (decode 9% to 19% lower). Quality of those: `q4_0`/`q4_0` is -0.1% to +2.4% depending on text, `q8_0`/`turbo3` is +0.1% to +0.6%.
- **No pair is both smaller than `q8_0`/`q8_0` and clearly lossless and fast.** Plain `q4_0`/`q4_0` is the closest: 1.9x smaller, no speed cost, text-dependent loss. `q8_0`/`turbo3` is 1.4x smaller, lossless on the two texts tried, and slower.
- Not yet measured: long generation coherence, chat text, a second model.

#### KL divergence, two models, three texts (run 2026-10-15)
Method: `llama-perplexity --kl-divergence`, `-c 512 --chunks 16`, Q8_0 weights, f16 cache as the reference. Mean KLD is the average divergence of the next-token distribution from f16 (lower is better). Top-1 is how often the most likely next token is unchanged. Models: Qwen3-4B-Instruct-2507 and Llama-3.2-3B-Instruct (`lmstudio-community`, SHA-256 `94f22b72…47fa8f21`, verified). Texts: wikitext, Clyde's own Python, and 100 ultrachat conversations (public Hugging Face sample, formatted as `User:`/`Assistant:`).

| K / V (plain unless noted) | Mean KLD, range over 6 model/text cells | Top-1 unchanged |
|---|---|---|
| `q8_0`/`q8_0` | 0.0001 to 0.0008 | 99.2% to 99.6% |
| `q8_0`/`q4_0` (slow on Metal, see above) | 0.0031 to 0.0040 | 96.5% to 97.7% |
| `q8_0`/`turbo3` | 0.0099 to 0.0120 | 94.9% to 96.4% |
| `q5_0`/`q5_0` | 0.0081 to 0.0211 | 94.3% to 95.8% |
| scaled `q4_0`/`q4_0` (Qwen only, wikitext and code) | 0.0181 to 0.0264 | 93.6% to 95.7% |
| plain `q4_0`/`q4_0` | 0.0394 to 0.0540 | 89.3% to 93.0% |

Findings:
- **Perplexity understated the damage.** Plain `q4_0`/`q4_0` looked like +0% to +2.4% perplexity, but it changes the top next-token choice about 7% to 11% of the time on both models and all three text types. That is 50 to 100 times the divergence of `q8_0`/`q8_0`. The earlier "plain `q4_0` is the closest candidate" reading is withdrawn.
- **The scale does help by this measure**, about 2x lower KLD than plain `q4_0` on both wikitext and code (it looked harmful on code by perplexity). Perplexity and KLD disagree here and KLD uses far more information per token, so I trust KLD more, but the scale is still Qwen-only and was calibrated on one text.
- **Only `q8_0`/`q8_0` is clearly safe** (KLD under 0.001). `q8_0`/`q4_0` is the best compressed option by KLD but is unusable on Metal. `q8_0`/`turbo3` is about 10x worse than `q8_0` and slower.
- Results agree across both models and all three texts, so this is not a Qwen quirk.

#### Generation checks (Qwen3-4B, `llama-server` release build, greedy, 16k context)
- Both `q8_0`/`q8_0` and plain `q4_0`/`q4_0` wrote 1,800 tokens of a long technical essay without collapse or loops. They diverge from the first sentence, as expected from the KLD. The `q4_0` text has about 8x the repeated 6-grams (0.0125 against 0.0016), but the repeats are the legitimate RTT-by-RTT worked example, not a loop. It also drops the headings the `q8_0` text uses.
- Both found a code buried in a 4.4k-token document (`4417-LAMBDA`). This is a short test. Long context (8k to 16k) needle tests were not run.
- Limits: one prompt, greedy, one model.

#### Result of the cache research
`q8_0`/`q8_0` is the only default backed by the measurements: about 1.9x smaller than f16 with KLD under 0.001. Everything smaller costs measurable divergence (KLD 0.003 to 0.05), and the smallest options also lose speed or are unavailable on Metal. A smaller default should be offered only as an explicit user setting with this tradeoff stated, not as a default. This reduces the cache half of the plan to: use `q8_0` KV cache (also available in Ollama and LM Studio today), so the case for shipping a patched fork for the cache alone is weak. The MoE half (Gate 2) is now the main reason left to add a llama.cpp provider.

## MLX alternatives checked (read-only, 2026-10-15)
Three local clones: `turboquant-mlx` (Apache-2.0, 128 commits), `VeloxQuant-MLX` (MIT, 1,044 commits, 43 methods), `tqai` (MIT, 67 commits, PyTorch and MLX). All three are Python on MLX or PyTorch, not llama.cpp, and none reads GGUF.

| Project | Memory saved at runtime? | Speed | Quality evidence |
|---|---|---|---|
| `turboquant-mlx` | Yes, measured: 2.1 GB at 63k context on a 35B MoE | Up to 6.6x slower decode at 63k on small-KV models (its own table) | Perplexity on weights, cosine on KV, stress tests |
| `VeloxQuant-MLX` | No for most methods: its README says ratios are bit-width accounting and most methods keep fp16 internally | Not the point | Sample outputs and cosine similarity. Its perplexity benchmark is an unchecked TODO |
| `tqai` | No on Apple Silicon: its README says peak memory is within 0.2 GB of baseline, pending a fused kernel | Not the point | Claims zero perplexity change on 8B+ models, its own measurement, not reproduced here |

Verdict: none of them beats the llama.cpp path on the thing we need, which is real memory saved at low speed cost with measured quality. K at 8 bits is also the setting `turboquant-mlx` recommends, so it has no K-compression advantage over `q8_0` K either. Adopting MLX would mean a new provider, a Python dependency, and weights outside GGUF, for no measured gain on KV. Its real differentiators are 3-bit weights and expert streaming, which are separate from this plan. Revisit only if Gate 2 shows llama.cpp cannot stream experts usably.

Next tests, before any default is chosen: speed of `q8_0`/`q4_0` with depth, a chat-style text, a second model, and a long generation check.

#### Speed benchmark: method (as run)
Question: does a smaller cache keep decode speed, especially as context grows? Quantized caches pay a dequantize cost, turbo types pay a rotation cost, and the scale patch adds two multiplies per layer. A smaller cache should read less memory per token, so long-context decode may get faster. Nobody has measured it here.

- Tool: `llama-bench`, same model and machine as above, plugged in, nothing else running, `-ngl 99 -fa on -p 512 -n 128 -d 0,8192,16384 -r 3` plus `-ctk` and `-ctv` per configuration. The release's `llama-bench` has `-d/--n-depth`, `-r`, `-ctk`, `-ctv` and `-fa on|off|auto`, checked against its `--help`.
- Configurations (K / V): f16/f16, `q8_0`/`q8_0`, `q8_0`/`turbo3` (stock release binary), scaled `q4_0`/`q4_0` and scaled `q4_0`/`turbo3` (my patched build with `KV_CHSCALE_FILE`). The patched build in the scratchpad has no `llama-bench` yet, so build that target first.
- Also run f16/f16 on the patched build with and without the scale file, to isolate the cost of the two multiplies from the cost of the cache type.
- Record: prefill and decode tokens per second at each depth, and peak memory (`/usr/bin/time -l`, maximum resident set size), plus whether the machine swapped.
- **Pass (proposed, to be confirmed once numbers exist):** decode at depth 0 within 10% of `q8_0`/`q8_0`, and decode at 16k depth no slower than `q8_0`/`q8_0`. A config that saves memory but loses more than that is reported as a memory-for-speed trade and is not made a default.
- The numbers feed Task 4 as well, since the real context Clyde can offer depends on both memory and speed.

### Gate 2: MoE offload measurement (manual)
- Run a small MoE GGUF (for example Qwen3-30B-A3B at Q4) with `--load-mode mmap` and compare tokens/s and RAM against Ollama's default load.
- On unified memory, `-cmoe` and `--moe-cache` do not apply, so the question here is whether mmap paging is usable.
- **Pass:** decode speed stays usable for chat (a threshold to be set from the measured numbers) and the machine stays responsive.

#### Gate 2 results (run 2026-10-15, partial, FAILED SAFETY)
Model: `Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf` from `lmstudio-community` (18,556,685,824 bytes, SHA-256 `88168cc3…57886d8`, verified). It is 18.56 GB on a machine with 18 GB of RAM and a 14.3 GB Metal limit (`recommendedMaxWorkingSetSize`). Release binary `turboquant-9ca222f`, `llama-bench -fa on -p 128 -n 32`.

| Config | Result |
|---|---|
| CPU only, `-ngl 0`, repack default | killed by the system, no output (peak footprint 15.5 GB, swap grew from 3 GB to 10.6 GB) |
| CPU only, `-ngl 0 --repack off` | **works: 6.5 tok/s decode, 13.8 tok/s prefill, 12.9 GB resident** |
| `-ngl 99 -ncmoe 30` | aborts: `GGML_ASSERT(i02 >= 0 && i02 < n_as)` in `ggml-cpu/repack.cpp:4461` |
| `-ngl 99 -ncmoe 24`, `-ngl 24`, and with `--repack off`: `-ncmoe 36`, `-ngl 20`, `-ngl 8`, `-ngl 2` | all fail with `failed to decode prompt batch, res = -3` (GPU error), even with only 2 layers on the GPU |
| `llama-cli -ngl 2` / `-ngl 20` | **kernel panic: `watchdog timeout: no checkins from watchdogd in 90 seconds`, "LOW swap space", machine restarted** |

Findings:
- **A model larger than RAM runs only on the CPU, at 6.5 tok/s decode.** Every GPU offload failed. The cause of the `-3` decode error is not known: it fails even at `-ngl 2`, so it is not simply the memory limit. It could be a bug in the fork's Metal path for this model, which I did not isolate.
- **The `--repack` default asserts on this MoE model on CPU with `-ncmoe`**, and `--repack off` avoids the assert. That is a fork bug to report or work around.
- **Running this test crashed the whole Mac.** This is the failure `turboquant-mlx`'s README warns about (kernel watchdog starved when memory use and allocation rate run near the wired limit). The test was mine and it was unsafe. The panic log shows heavy swapping across 11 swap files.
- **Rule for the provider, not optional:** Clyde must never start a model whose weights plus cache exceed the memory budget from `fit.py` (the wired limit and free RAM), and must never offer GPU offload for such a model on Apple Silicon. A model that does not fit stays on Ollama or LM Studio, or runs CPU only with an explicit speed warning.
- Not tested, because of the panic: any MoE that fits in memory (for example gpt-oss-20b at 12 GB), `--moe-cache`, `--load-mode`, and the mmap paging question. Do not retry on this machine without closing other apps and getting the user's go-ahead for each model.
- All raw logs and the 18.5 GB model were lost when the scratch folder was cleared by the restart. The numbers above are copied from the runs before the panic.

#### Gate 2, second attempt: CPU only, with a kill switch (run 2026-10-15 after the restart)
Rules set by the user: no GPU at all, and any early warning stops everything. Setup: `llama-bench -dev none -ngl 0 --repack off`, with a watcher sampling `kern.memorystatus_vm_pressure_level`, swap and free-memory percentage every second, ready to kill the benchmark if pressure reached 2, swap grew by 300 MB, or free memory fell under 12%. The re-downloaded release matched the pinned SHA-256 `9bb38630…508dbe67`. Model: `gpt-oss-20b-MXFP4.gguf` from `lmstudio-community` (12,109,565,632 bytes, SHA-256 `65d06d31…cde53ab`, verified), a 21B MoE with about 3.6B active parameters. Baseline: swap 0, pressure level 1, 71% free.

| Run | Prefill | Decode | Peak resident | Warnings |
|---|---|---|---|---|
| `-p 64 -n 16` | 5.9 tok/s | 14.3 tok/s | 7.0 GB | none |
| `-p 256 -n 128` | 16.2 tok/s | 14.5 tok/s | 7.1 GB | none (swap stayed 0, free memory never below 48%, pressure level 1) |

Findings:
- **CPU-only MoE decode is usable for chat: about 14.5 tok/s** for a 20B model, because only about 3.6B parameters are read per token. For comparison, the dense 4B model decodes at about 28 tok/s on the GPU.
- **CPU-only prefill is the weakness: about 16 tok/s.** A 4,000-token prompt takes over four minutes. The dense 4B model on the GPU prefills at about 510 tok/s. Agent-style prompts are long, so CPU-only MoE is a poor fit for Clyde's main use.
- **mmap keeps the resident set small.** Only about 7 GB of the 12.1 GB file was touched, because experts that are never routed to are never paged in.
- **The 30B model (18.6 GB, larger than RAM) also decoded CPU-only at 6.5 tok/s with prefill 13.8 tok/s** and `--repack off`, but with a footprint of 12.9 GB resident and swap growing in the earlier run. With the default repack it was killed. `--repack off` is needed for MoE on CPU in this build.
- **Not tested, by instruction: any GPU path.** The Metal decode error and the panic stay unexplained, so a GPU MoE path cannot be recommended. Without a working GPU path, MoE support does not fix Clyde's prefill problem.
- **Conclusion on MoE:** it is feasible for chat-style use on CPU, but not for long agent prompts, and the GPU route that would fix that is unsafe or broken in this build. It is not a good reason to build the llama.cpp provider right now.

## Prior art checked: Velocity Local Services (VLS)
Source: `github.com/dea6cat/velocity-local-services`, read 2026-10-15. The repo holds only a README, a licence, a third-party notices file and images. There is no source code and no release assets visible there. Its README links point to `Veloresearch/velocity-local-services`, so this repo looks like a copy of that one.

What it is: a closed-source desktop app for Windows (x64, CUDA or Vulkan) and Linux (x64) that runs GGUF models through llama.cpp, with chat, voice, computer use, MCP plugins and an OpenAI-compatible API on `127.0.0.1:11500`. Free for personal use, a paid licence for companies. No macOS build.

What it confirms for this plan:
- **The architecture is the same one.** A router in front of a pinned `llama-server`, reached over the OpenAI-compatible API. Its notices file says the Linux package carries upstream llama.cpp's own published build, repacked and not rebuilt. So it has no turbo cache types, no channel scale and no KV compression at all.
- **Check the card before downloading.** It tells the user whether a model fits before the download starts. Clyde's `fit.py` already does this, so nothing to add.
- **Ship licence notices.** Its `THIRD-PARTY-NOTICES.txt` lists each bundled binary with its source, licence and files. The fork is MIT, which requires the licence text to travel with the binary, so Task 1 must do the same.
- **Benchmark claims need their conditions.** It reports speed and latency per answer on one laptop (RTX 3060 6 GB, a 4B Q4_K_M model, an 8K window). The speed benchmark above should state its machine and settings the same way.

What it does not give us:
- **No code to reuse**, and the licence forbids business use without a paid licence. Nothing is integrated.
- **Velocity Context** (up to 32M tokens, "not RAG") is a different problem: it reaches into stored material instead of shrinking the cache. The method is withheld, and the results (RULER and an own-ladder test on a 4B model) come from the vendor's own report, which I have not read or reproduced. It does not compete with or replace the cache work here. If Clyde wants long-range memory, that is a separate plan.
- **Platforms differ.** VLS targets Windows and Linux. This plan starts on macOS arm64, and the fork's release also has Windows and Linux assets if Clyde extends to them later.

## Phase 1: llamacpp provider (needs Gate 1)

### Task 1: fetch and verify the engine
- New `src/providers/llamacpp.py` with the pinned tag, SHA-256, download, extraction and signature check.
- Ship the engine's MIT licence text and a short notices entry (source, licence, files) beside the binaries.
- **Acceptance:** a tampered archive or bad signature raises `ProviderError` and nothing is executed. Tested with a fake archive. The extracted folder contains the licence text.

### Task 2: start the server and health probe
- Subclass `OpenAICompatProvider`. Start `llama-server -m <gguf> -c <ctx> -ngl 99 -ctk q8_0 -ctv turbo3 --port <free>`, wait until ready, then send one probe prompt and check for a non-empty, well-formed reply.
- **Acceptance:** probe failure stops the server and reports a fallback. Tested with a fake server.

### Task 3: register and fall back
- Register in `registry.py` as opt-in. On failure, fall back to Ollama or LM Studio.
- **Acceptance:** with the setting off the registry is unchanged. With it on and the engine missing, the fallback is used.

### Task 4: KV-aware sizing
- `_kv_bytes_per_token` and `KV_USE_FRACTION` in `ollama.py` assume f16. Scale by bits per value (turbo3 is 3.25, q8_0 is 8, f16 is 16) on the llama.cpp path only, so the context window Clyde picks matches the real cache.
- **Acceptance:** same model and RAM give a larger window with turbo3 than f16, and the Ollama path is unchanged.

### Task 5: GGUF discovery
- Reuse GGUFs already in the Ollama and LM Studio stores rather than downloading twice. Reuse the GGUF header reading in `fit.py` and `huggingface.py` where it already exists.

## Phase 2: MoE (needs Gate 2 and Phase 1)

### Task 6: MoE detection
- Read `expert_count` and `expert_used_count` from the GGUF header. **Acceptance:** a dense model and a MoE model are told apart in a fixture test.

### Task 7: MoE-aware rating
- Rate by shared layers plus active experts, not total file size, so `/models local` stops rejecting MoE models that would run.
- **Acceptance:** a 30B-A3B-sized fixture is rated as fitting where the size-only rule rejects it.

### Task 8: flag planner
- Choose `-ncmoe`, `--moe-cache` and `--load-mode` from detected VRAM and RAM. With no discrete GPU, use `mmap` only.
- **Acceptance:** table-driven tests over RAM and VRAM combinations.

### Task 9: speed warning
- Before loading a model that will page from disk, tell the user the expected speed. Strata's own README reports 7 to 8.5 tokens/s for a 4-bit model that streams, so this is a real cost.

## Risks
- Quality: proven only for one 4B model, perplexity only, Metal only. The scale also needs per-model calibration.
- Maintenance: the scale is a core-graph patch on a nightly fork, so every rebase can conflict with it.
- Probe scripts and the calibration file live in the session scratchpad, which will not last. Copy them somewhere durable before relying on them.
- Nightly fork: it rebases onto upstream, so API and behaviour can change. Mitigated by the pin.
- Supply chain: third-party binary. Mitigated by SHA-256, codesign check, opt-in.
- Platform: only Metal was benchmarked by the fork's authors. Other platforms stay on Ollama and LM Studio.
- Paging: slows agent loops, and this machine's disk is 91% full. Worse, an oversized model with GPU layers caused a kernel panic on this machine (see Gate 2 results).
- Unverified: I read the flags' help text in `common/arg.cpp`, not the engine code. `--moe-cache` and mmap paging behaviour are untested.

## Open questions
- Does the GGUF reach `llama-server` by file path from the Ollama blob store? Ollama stores blobs under hashed names, which still load as GGUF, but this needs checking.
- The pinned SHA-256 is computed from my own download (see Decisions), because GitHub publishes no digest. Re-verify it against a fresh download when the pin is committed.
- Where does the per-model scale file come from at run time: calibrated on the user's machine at first use, or shipped for a list of known models?
