# Fine-tuning dataset — built, validated, nothing trained yet

*Research note, 2026-10-12. Status as of that date: dataset and scorer exist; **no training has been run**. This note exists because the validation catches are the reusable knowledge.*

## The pipeline

24 Hugging Face datasets (1,793 files, 12 GB, no failed files) → cleaned to **7,090 sessions and ~313,000 tool calls** → **21,194 train / 558 valid / 1,080 test examples**, split by session (no leakage across splits). About 78% SWE bug-fixing, 22% Claude Code-style.

Two argument formats, because chat templates disagree: JSON-string arguments (DeepSeek template) and object arguments (Qwen3.5-style). 2,638 of 2,638 sampled examples rendered through the real installed templates with zero failures.

## Two label-poisoning defects the checks caught (both fixed, rebuilt)

1. **Truncation markers in targets.** 10% of examples (68% of Write targets) ended with a literal `...[truncated]` — a model trained on this would have *learned to write that marker into files*. After the fix: zero targets carry the marker.
2. **Targets failing Clyde's own tool schemas.** 9.3% of targets would have been invalid tool calls (e.g. Claude Code's Bash `description` field, which Clyde's schema rejects via `additionalProperties: false` — 1,969 of 7,400 Bash targets). After the fix: zero failures.

**The transferable lesson:** before training an agent on tool-call data, validate every target against *your* tool schemas, render everything through *the real templates*, and grep for truncation markers. Two quiet defects, one validation pass, zero trained-in habits.

## The scorer

`finetune-data/scripts/score_tool_calls.py check <data> <model>` is model-agnostic: chat-template test, tool-call rendering, parse, context window and sequence length — all from the tokenizer and config only. Verdicts on the two models at hand: DeepSeek-R1-0528-Qwen3 8B SUITABLE with JSON-string arguments; a 27B 2-bit model passes template checks with object arguments but is very likely untrainable on 18 GB.

## Why it is documented but not trained

Training on this machine is the limiting factor (see [local-models.md](local-models.md)). The dataset, the scorer, and the two validation catches are the durable output; the training run is a later, separate event.
