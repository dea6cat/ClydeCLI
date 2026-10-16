# Does clearing old tool results cost Clyde its prefix cache on local models?

Date: 2026-10-16. Branch: `research/context-clearing-cache-cost`. Status: closed, no code change.

## Question

On local models, Clyde clears old tool results once the conversation passes 50% of the window (`trim_old_tool_results`, `src/context_system/microcompact.py:199`, called each turn from `src/agent/agent_loop.py:332`). Ollama reuses its cache only up to the first changed token, so clearing a result in the middle of the history could force a re-read of everything after it. The hypothesis was that Clyde clears one more result on every turn, so it pays that cost on every turn, and that clearing in batches would fix it.

## Verdict

The hypothesis is wrong, and nothing needs fixing. The function clears every old long result except the newest four in one pass. Afterwards the conversation sits at about a third of the window, so the next clearing happens only after several more turns. The current behaviour is already a batch. Measured, it is indistinguishable from an explicit batch strategy, and it did not cost more total prefill time than never clearing in a 12-turn test.

## Method

- Ollama 0.35.1, CPU only (`num_gpu` 0), `Qwen2.5-Coder-3B-Instruct` Q8_0, `num_ctx` 8192, `num_predict` 4, temperature 0.
- A scripted session of 12 turns. Each turn adds a short assistant line and a tool result of about 430 tokens. The window used for the 50% rule was 6144 tokens.
- Three strategies, each in a fresh run with a unique salt in the system prompt so runs could not reuse each other's cache: `none` (never clear), `per_turn` (a copy of the current rule), `batch` (past 50%, clear the oldest results down to 25%, then wait for 50% again).
- The metric is Ollama's `prompt_eval_duration` for each turn.

## Results

| Turn | `none` (est. tokens, prefill ms) | `per_turn` (current rule) | `batch` |
|---|---|---|---|
| 0 | 445, 4868 | 446, 5493 | 446, 4806 |
| 3 | 1723, 9529 | 1724, 8956 | 1724, 9343 |
| 6 | 3002, 14322 | 3002, 13621 | 3002, 14189 |
| 7 | 3428, 15888 | 1779, 29205 | 1779, 30181 |
| 8 | 3855, 17477 | 2205, 10880 | 2205, 11282 |
| 10 | 4727, 23700 | 1839, 31191 | 1839, 32334 |
| 11 | 5172, 25758 | 2284, 13039 | 2284, 13545 |
| Total over 12 turns | 168,696 ms | 160,937 ms | 165,939 ms |

- `per_turn` and `batch` cleared on the same turns (7 and 10) and cost almost exactly the same. Their totals differ by 3%, which is within the noise I would expect from CPU timing.
- A turn that clears costs about 29 to 32 seconds, because everything after the first cleared result is read again. An ordinary turn after clearing costs 11 to 13 seconds. In `none`, ordinary turns grow from about 5 to about 26 seconds as the context grows.

## Cache behaviour, checked directly

A separate probe sent a conversation, repeated it, then grew it by one turn (cold means a fresh salt, so nothing is cached):

| Request | Prefill |
|---|---|
| 6 turns, cold | 37,329 ms |
| Same 6 turns again | 38 ms |
| 7 turns, grown from the cached 6 | 10,418 ms |
| 7 turns, cold | 48,589 ms |
| 8 turns, grown from the cached 7 | 11,938 ms |
| 8 turns, cold | 61,091 ms |

So Ollama does reuse the prefix when a conversation only grows, and a full re-read is about four to five times slower than a one-turn increment. This is why a clearing event is expensive, and why clearing rarely matters more than the number of clearing events.

One early run of mine was contaminated, because Ollama also keeps several earlier prompts in cache. Exact repeats from an earlier run showed up as 31 to 37 ms turns. I discarded those numbers and repeated every run with a unique salt.

## Online corroboration

- A secondhand write-up of Claude Code says it clears old tool results either when the cache is already cold or by editing the cache in place, which supports the idea that clearing has a cache cost and that timing matters. <https://medium.com/@pbellapu09/how-claude-code-manages-infinite-sessions-without-blowing-the-context-window-8bccb35387fe>
- A terminal-agent paper describes staged context pressure (70%, 80%, 85%, 90%, 99%) in which older tool results are replaced by short pointers first and summarizing comes last. Clyde's order (clear at 50%, summarize at 80%) matches that shape. <https://arxiv.org/pdf/2603.05344>
- Anthropic's cookbook separates tool-result clearing from compaction, notes and sub-agents, and treats clearing as the lightest option. <https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools>
- On long-context quality, the original "Lost in the Middle" paper reports recall dropping for information in the middle of long inputs. RULER and a practitioner post suggest effective context is about 50% to 65% of the advertised length. I found no 2026 measurements for Qwen or Gemma. <https://arxiv.org/pdf/2307.03172>

I found no source that measures prefix-cache cost of clearing on Ollama or llama.cpp.

## Limits

- One small model, CPU only, one synthetic session of 12 turns, one run per strategy. A GPU would shrink all the times, though the ratios between a cold and a grown prompt should be similar.
- The results are synthetic text of equal length. Real tool results vary, so real clearing events will not line up like these.
- The test measures speed only. Whether clearing hurts the quality of the model's answers was not tested.
- Clyde already pins `num_ctx` to its `context_window` on local models (`src/providers/ollama.py:175`), so the 50% rule is measured against the window actually loaded. I read this comment but did not run a test on it.

## Decision

No change. The 50% to about 30% pattern already amortizes the cost of clearing. The one untested idea left is to raise the trigger or lower the target to make clearing events rarer, which would trade quality for speed in a way this test cannot judge.
