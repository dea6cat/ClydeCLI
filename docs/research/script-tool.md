# Script tool (code as a plan): a study, not a result

*Study note, 2026-10-27. Nothing described here is built, tested or measured yet. It records the idea, what it would have to beat, the measurement that decides whether to build it, and the rule for deciding, so the decision is made on numbers and not on how interesting the idea is.*

## The question

Does a Clyde session spend a real share of its model requests on chains of reads and searches, where each result is only used to choose the next call? If it does, a tool that lets the model write a short script (which calls Clyde's other tools and returns only what the model needs) could remove most of those requests. If it does not, the tool is complexity with nothing to save, and we drop it.

## The idea

Code Mode (Cloudflare's name; Pi ships the same thing as `codemode`) replaces many one-call-at-a-time tool requests with one request that carries a script:

- The model gets one tool whose input is a script. The script calls the other tools as functions, loops over results, filters, branches, and returns a value.
- Only what the script returns reaches the model. Intermediate results (ten files read to find one line) never enter the context.
- Tool definitions can be found on demand from inside the script (search, then describe) instead of being sent up front.

What the sources actually say, so this note does not claim more than they do:

- **Cloudflare's Code Mode page** describes the pattern and says when to prefer plain calls: "Simple tasks using a small, known tool set". It calls the feature **experimental** and warns of breaking changes. It reports no measurements.
- **Pi's `docs/codemode.md`** (Pi 1.4.0): the script runs as an async function body in a QuickJS sandbox with no Node APIs or file access; tools are `tools.<name>(args)`; a script's output is capped (10,000 tokens by default; longer output keeps its start and end and the full text goes to a temp file); there is an optional hard timeout; `store`/`load` keep small values between calls; tool search ranks tools by relevance. Calls a script makes run through the same tool pipeline as direct calls, with their own hooks, and are recorded on the result with limits (at most 256 calls, 8 KB of arguments per call, 32 KB in total).
- **The HarnessTax article** (Arena, 16 Sept 2026) did **not** test Code Mode. It measured four-tool Pi against Claude Code and Codex and found cost per task differing by up to 5× at similar success. It is evidence that the number of turns and the size of the context drive cost, not that scripts reduce them.

## What Clyde already has

A script tool has to beat these, not nothing:

- **Several calls in one turn.** The loop runs every tool call a model returns in one response, so a model can already batch reads and greps.
- **Tools found on demand.** `ToolSearch` and deferred tools mean a small local model is sent only the tools its prompt asks for, and a cloud model about 19 of 44 (measured 2026-10-27: roughly 0.8k tokens of system prompt and 2.3k of tool definitions before the user's words).
- **Long results clipped, with the whole saved.** Over-long tool output keeps its start and end, and `RetrieveContext` reads the saved text back and (since the harness-cost branch) searches it.
- **Several edits in one `Edit` call** (same branch).

So the saving this tool could add is narrow: chains of dependent reads and searches where the model cannot batch because the next call depends on the last result.

## What it could save, and what it costs

| | |
|---|---|
| Could save | Model requests in dependent chains (a chain of n requests becomes about 1); tokens of intermediate results the model never needed; wall time for round trips. |
| Costs | A sandbox (a new dependency or a new component); a permission and recording design that keeps scripts no more powerful than direct calls; the tool's own definition (a typed description of every callable tool is large); the model writing correct scripts, which small local models are unlikely to do reliably; harder debugging for the user, who sees one opaque call instead of a sequence. |

## The measurement

**Definition.** A *read chain* is a run of three or more consecutive model requests inside one user turn where every tool call is read-only (`Read`, `Grep`, `Glob`, a read-only `Bash` command) and nothing is written, edited or asked of the user in between. Three is the smallest run in which a script could replace at least two requests.

**Source.** Clyde's own traces, `~/.clyde/traces/*.jsonl`. They already record, in order, each `model_request` (model, message count, token usage including cache fields, duration) and each `tool_call` (tool name, duration, result size in characters, error flag), so no new instrumentation is needed. A request is joined to the tool calls that follow it in file order.

**Measure, per model and overall:**

1. The share of model requests that sit inside a read chain.
2. The distribution of chain lengths (median, 90th percentile, longest).
3. The share of billed input tokens spent on requests inside chains.
4. The total size of tool results inside chains (characters), as a rough upper bound on context that a script would have kept out of the conversation.
5. Wall time spent in chains.

**Limits to state with the result:** tracing may have been off for some sessions; traces on this machine so far come from two Mistral models only, which says nothing about cloud models and long agentic sessions; a model that already batches calls in one response will show shorter chains than one that does not; the size of tool results is not the same as the part of them the model needed.

**Sample.** Do not decide on fewer than 100 sessions covering at least three models, at least one of them a cloud model. If the traces on hand are not that, collect more (or run a fixed task set through the real loop on several models) before deciding.

## The decision rule (proposed; agree it before measuring)

Fixed in advance so the rule is not fitted to the data:

- **Build a prototype** only if, over the sample, read chains hold **at least 25% of model requests** and **at least 20% of billed input tokens**, and the requests a script would remove (chain length minus one, per chain) are **at least 15% of all requests**.
- **Drop it** if any of the three is clearly below its bar. Write the numbers into this note and stop.
- Between the bars: do not build; revisit if the traces change (for example, after Clyde is used with more cloud models).

## If it is built

The prototype answers one question, whether it lowers cost per task without lowering success, and is judged by an A/B on the same tasks (three runs each, with and without the tool, per model: cost, requests, success). It would be:

- **Opt-in and off by default**, behind a setting, and offered only to models that have shown they can write the scripts (not small local models).
- **No more powerful than direct calls.** Every call a script makes goes through the same permission and approval pipeline, the same hooks and the same limits as a direct call, including Clyde's rules that an untrusted result can never grant permission. A script cannot reach a file, a command or a host a direct call would be refused.
- **Honest in the record.** Each nested call is recorded with its own tool name and result, with caps like Pi's, so the station and the trace show what actually ran. The page must not show a script as a single harmless step.
- **Offline and shipped with Clyde.** No hosted runtime and no proprietary dependency, like everything Clyde ships. The sandbox is the open question: it must run offline on the platforms Clyde supports, and Python's own `exec` is not a sandbox.
- **Bounded.** A time limit, an output cap with the whole output saved (reusing the existing clipping and `RetrieveContext`), and a cap on nested calls.

## Risks

- **Injection travels into code.** Text from a web page or a file can end up inside a script the model writes. The injection check on outside results helps, but a script that acts on what it read has a larger blast radius than a model that reads a result and decides.
- **A second language in the loop.** The model must write correct script syntax and the typed descriptions of tools; a failed script wastes the requests it was meant to save.
- **Prompt cache.** A large, changing tool description can break the cache that makes the first call cheap; any description must stay byte-stable between turns.
- **Complexity that outlives the idea.** If it does not pay for itself it still has to be maintained and secured.

## What this note does not claim

- It does not claim a script tool saves anything for Clyde. That is exactly what the measurement is for.
- It does not claim that savings reported for Code Mode elsewhere carry over to Clyde's loop, tools or models.
- The thresholds above are a proposal, not a finding.

## Sources

- Cloudflare, *Code Mode* (Agents documentation, updated 2026-06-24), read from a copy pasted into the session.
- Pi 1.4.0, `docs/codemode.md` and `dist/core/nested-tool-calls.js` (the nested-call limits), read from the installed package.
- Arena, *HarnessTax: How Much Does the Harness Matter for Coding Agents?* (16 Sept 2026): cost and context differences between harnesses; Code Mode not tested.
- Clyde's own numbers above: first-request size measured 2026-10-27 with the default registry through a scripted provider, no project instructions.
