# Local models on an 18 GB Mac — what actually runs

*Research note, 2026-10-12. Machine: Apple M3 Pro, 18 GB. Runtime versions as of that date. Measured, not estimated.*

## The headline

A Mixture-of-Experts model of about 12 GB does **not** run in about 5 GB of usable memory at a usable speed on this class of machine. A dense 8B does.

## Measurements

| Model | Runtime | Resident | Speed | Verdict |
|---|---|---|---|---|
| gpt-oss-20b MXFP4 (12.1 GB GGUF) | LM Studio | 10.9 GB, swap 1.9 → 5.3 GB | 3.0 then **0.7 tok/s** | unusable |
| same file, `llama-server --cpu-moe --load-mode mmap` | llama.cpp | 9.8 GB physical (11.4 GB mapped) | 1–2 tok/s prompt processing, **no reply in 10+ min** | unusable |
| deepseek-r1-0528-qwen3-8b-mlx (dense, 4.3 GiB) | LM Studio | as loaded | **26–27 tok/s** | good |

Why mmap saved nothing: with MoE, every token routes through different experts, so lazy loading defeats itself — the whole mapped file gets touched.

Arithmetic, not measured: 3-bit of a 20B is about 9 GB; 2-bit about 5 GB.

## What this implies for a 16 GB machine

The 16 GB class (e.g. a MacBook Air) has a smaller budget than the 18 GB machine above, so the usable class is dense models of **8B and below**, ideally at 4-bit or 8-bit. `/models local` encodes this as its memory budget (about two thirds of RAM up to 36 GB, three quarters above or elsewhere, minus what's in use) and its relax / balance / hard ratings; this note is the measurement behind the "hard" rating meaning what it says.

Rejected alternatives for this machine: `ds4` (96 GB+ Macs), vLLM (GPU servers, no real Apple GPU path).
