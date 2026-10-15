"""Hugging Face MLX repos as a source of local models for Apple Silicon. An MLX repo usually holds
one quantization (`…-4bit`), so its size is the sum of its safetensors files: exact. LM Studio
downloads and runs them (`lms get <url> --mlx`). Every entry point returns [] on any failure.
"""
from __future__ import annotations

import re

from .fit import Offer, rate
from .huggingface import files, offers, original

_BITS = re.compile(r"(\d+)[-_]?bits?\b", re.I)
_TAG = re.compile(r"(?:^|[-_])(o?q\d+\w*|bf16|f16|fp\d+|mxfp\d+|optiq\w*)(?=[-_.]|$)", re.I)   # a quantization named in the repo


def weights_bytes(listing: list[dict]) -> int:
    """Total size of the safetensors weights at a repo's root."""
    return sum(f["size"] for f in listing if f.get("type") == "file" and isinstance(f.get("size"), int)
               and str(f.get("path", "")).endswith(".safetensors"))


def search(query: str, budget: int) -> list[Offer]:
    """MLX repos matching `query` (the most downloaded when empty) that fit `budget` bytes."""
    def offer(repo: dict) -> Offer | None:
        repo_id = repo.get("id", "")
        size = weights_bytes(files(repo_id))
        rating = rate(size, budget) if size else None
        if rating is None:
            return None
        bits = _BITS.search(repo_id)
        tag = _TAG.search(repo_id.rsplit("/", 1)[-1])   # a repo without a bit count may still name its quantization: oQ6e, q8, bf16
        return Offer(repo_id, f"https://huggingface.co/{repo_id}", size, rating, int(repo.get("downloads") or 0),
                     f"MLX {bits.group(1)}-bit" if bits else f"MLX {tag.group(1)}" if tag else "MLX", "mlx", model=original(repo))
    return offers("mlx", query, offer)
