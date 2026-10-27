# Research notes

Every claim ClydeCLI makes about local models, small-model behavior, and security rests on a measurement recorded here. The notes are self-published, written as the work happened, and dated. Where a result came from a specific machine, the machine is named. If you reproduce a number and get a different one, that is a bug in these notes — please open an issue.

| Note | What it establishes |
|---|---|
| [Local models on an 18 GB Mac](local-models.md) | What actually runs: dense ≤8B yes, ~12 GB MoE no. Measured, not estimated. |
| [Small-model behavior](small-models.md) | The routing fix, cloud-review triggers, why Laya's fit score was dropped as a trigger, and the deferred-tool evidence. |
| [oMLX on an 18 GB Mac](omlx.md) | Its SSD cache restores a 3.5k-token prompt after a server restart as fast as a warm repeat (0.96 s vs 7.56 s cold); why Clyde starts it with the `balanced` memory guard. One run, no cross-engine comparison. |
| [`clyde tune` measurements](tune.md) | Per-model quality gates for Ollama settings; why the same setting passes one model and fails another. |
| [Security review, October 2026](security-review-2026-10.md) | Three real vulnerabilities found by manual review with working exploits, and their fixes. |
| [Script tool (study)](script-tool.md) | A proposal, not a result: whether a tool that lets the model write a short script would save requests in Clyde's sessions, the measurement that would decide it, and the rule for deciding, fixed in advance. Nothing built or measured. |
| [Fine-tuning dataset](fine-tuning-data.md) | 313K tool calls → 22.8K examples; two label-poisoning defects caught by validation before training. Nothing has been trained. |

**Method and limits.** Measurements run on one machine (Apple M3 Pro, 18 GB), dates are on each note, and sample sizes are stated honestly — including when they are small. These are engineering measurements, not benchmarks; where a public benchmark would serve better, we say so.
