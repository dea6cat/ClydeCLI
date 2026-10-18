# Small-model behavior — the measurements behind the design

*Research note, 2026-10-12 unless noted. All tests through Clyde's real loop; prompts made up for the tests, nothing from real work sent anywhere.*

## The routing fix (small models not getting Write/Bash)

A bug caused small local models to answer a change request with only Read/Glob/Grep. Fix on vs off, 3 runs each, Qwen3 4B Instruct 2507:

| Task | With fix | Without fix |
|---|---|---|
| "create greeting.txt" | **3/3** (Write used) | 0/3 (only Read, Glob, Grep) |
| "run hello.py" | no discrimination (model reads the one-line script) | same |

## Cloud review triggers — what a weak local reply actually looks like

The cloud-review feature ("a second opinion on weak replies") is triggered by plain-text checks, not a model score. The measurements that got us there:

- **DeepSeek-R1-0528-Qwen3 8B** (not trained for tool use): 8/8 plain factual and code questions correct. Both tool tasks failed — it *claimed it could not reach files that existed* instead of calling the tool. Worst reply time 456 s under swap. This is exactly the refusal pattern the trigger matches.
- **Qwen3 4B Instruct 2507** (2.89 GB): 12/12 correct, 0–19 s per reply, used Read, Bash and Write as asked. `/eval` tool-call round trip: 18 s.

## Why Laya's fit score was dropped as a weak-reply trigger

The README says the fit score "was tried as a trigger and dropped, because it flagged correct answers and passed wrong ones." The numbers behind that sentence:

| Reply | Fit score |
|---|---|
| Correct, terse ("391") | **0.08** |
| Wrong but plausible | 2.4–2.5 |
| Tool refusal ("I cannot reach files") | 2.1–2.5 |

A trigger that scores a correct answer 0.08 and a wrong one 2.4 is worse than no trigger. Dropped; plain-text checks shipped instead.

## Deferred tools — the evidence so far

56 tool definitions were about 9.5k tokens, most of it for tools a single turn never touches; that measurement is why `ToolSearch` deferral exists (small models see a core set; the rest loads on request, and a tool called without loading still runs).

The intent regexes that pick a local model's core set were tuned on **about 70 trials across two models** — specifically, models never asked `ToolSearch` for a tool whose job the prompt already named (edit, run, web…), so those tools are now sent directly. Honest limit: 70 trials on two models is a hypothesis, not a result. More models and trials would either confirm or refine the regexes.
