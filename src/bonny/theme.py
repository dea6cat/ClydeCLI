"""Bonny's look, chosen by the user: a preset, colour overrides, a background image, corner shape, font, a greeting and
free-form CSS. Saved in ~/.clyde/bonny/theme.json (the image next to it), so it survives restarts and changes of port.

Everything here is validated before it is kept: colours are #rrggbb, numbers are clamped, choices come from fixed lists,
and the image is identified by its first bytes, never by what the browser claimed. SVG is refused because it can carry
script. Only the custom CSS is free text, and it is the user's own page.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.config import clyde_home

MAX_IMAGE = 8_000_000
MAX_CSS = 20_000
MAX_GREETING = 80
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
COLOR_KEYS = ("bg", "tint", "text", "dim", "line", "link", "spade")
PRESETS: dict[str, dict[str, str]] = {   # "auto" has none: the page follows the system light or dark, as the site does
    "paper": {"bg": "#e8e5dd", "tint": "#dfdbd0", "text": "#16231b", "dim": "#566058", "line": "#c6c1b4", "link": "#1d6a36", "spade": "#d0202f"},
    "night": {"bg": "#0f1a14", "tint": "#13241a", "text": "#e3dfd6", "dim": "#9aa39c", "line": "#24382b", "link": "#6cc985", "spade": "#d0202f"},
    "felt": {"bg": "#0b2a1c", "tint": "#0f3524", "text": "#ece6d6", "dim": "#8fb09a", "line": "#1f5538", "link": "#f0c040", "spade": "#ff5a5f"},
    "slate": {"bg": "#12141c", "tint": "#181b26", "text": "#e6e8f0", "dim": "#8b90a5", "line": "#2a2f45", "link": "#8ab4ff", "spade": "#ff6b81"},
}
FITS = {"cover": ("cover", "no-repeat"), "contain": ("contain", "no-repeat"), "tile": ("auto", "repeat"), "center": ("auto", "no-repeat")}
FONTS = {
    "site": '"Bricolage Grotesque", -apple-system, "Segoe UI", sans-serif',
    "system": 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
    "serif": 'Georgia, "Times New Roman", serif',
    "mono": '"JetBrains Mono", ui-monospace, Menlo, monospace',
}
SHAPES = ("cut", "round", "square")
_SIGNATURES = (("png", b"\x89PNG\r\n\x1a\n"), ("jpg", b"\xff\xd8\xff"), ("gif", b"GIF87a"), ("gif", b"GIF89a"))
CONTENT_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}

DEFAULT: dict[str, Any] = {"preset": "auto", "colors": {}, "dim": 0.4, "blur": 0, "fit": "cover", "glass": 0.0,
                           "shape": "cut", "font": "site", "greeting": "", "css": ""}


def folder() -> Path:
    return clyde_home() / "bonny"


def _clamp(value: Any, low: float, high: float, fallback: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    return max(low, min(high, float(value)))


def clean(raw: Any) -> dict[str, Any]:
    """A theme built only from valid parts of `raw`; anything missing or invalid falls back to the default."""
    raw = raw if isinstance(raw, dict) else {}
    colors = raw.get("colors") if isinstance(raw.get("colors"), dict) else {}
    return {
        "preset": raw.get("preset") if raw.get("preset") in ("auto", *PRESETS) else DEFAULT["preset"],
        "colors": {k: colors[k].lower() for k in COLOR_KEYS if isinstance(colors.get(k), str) and _HEX.match(colors[k])},
        "dim": round(_clamp(raw.get("dim"), 0, 0.9, DEFAULT["dim"]), 2),
        "blur": int(_clamp(raw.get("blur"), 0, 24, DEFAULT["blur"])),
        "fit": raw.get("fit") if raw.get("fit") in FITS else DEFAULT["fit"],
        "glass": round(_clamp(raw.get("glass"), 0, 0.9, DEFAULT["glass"]), 2),
        "shape": raw.get("shape") if raw.get("shape") in SHAPES else DEFAULT["shape"],
        "font": raw.get("font") if raw.get("font") in FONTS else DEFAULT["font"],
        "greeting": " ".join(raw["greeting"].split())[:MAX_GREETING] if isinstance(raw.get("greeting"), str) else "",
        "css": raw["css"][:MAX_CSS] if isinstance(raw.get("css"), str) else "",
    }


def sniff_image(data: bytes) -> str | None:
    """png, jpg, gif or webp from the file's first bytes; None for anything else (SVG included)."""
    for kind, magic in _SIGNATURES:
        if data.startswith(magic):
            return kind
    return "webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else None


def image_path() -> Path | None:
    for ext in CONTENT_TYPES:
        path = folder() / f"background.{ext}"
        if path.is_file():
            return path
    return None


def save_image(data: bytes) -> str:
    """Keep `data` as the background and return its type; ValueError when it is not a supported image or is too big."""
    if len(data) > MAX_IMAGE:
        raise ValueError(f"the image is over {MAX_IMAGE // 1_000_000} MB")
    kind = sniff_image(data)
    if kind is None:
        raise ValueError("use a PNG, JPEG, GIF or WebP image")
    remove_image()
    folder().mkdir(parents=True, exist_ok=True)
    (folder() / f"background.{kind}").write_bytes(data)
    return kind


def remove_image() -> None:
    for ext in CONTENT_TYPES:
        (folder() / f"background.{ext}").unlink(missing_ok=True)


def load() -> dict[str, Any]:
    try:
        return clean(json.loads((folder() / "theme.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return clean({})


def save(theme: Any) -> dict[str, Any]:
    kept = clean(theme)
    folder().mkdir(parents=True, exist_ok=True)
    (folder() / "theme.json").write_text(json.dumps(kept, indent=2), encoding="utf-8")
    return kept


def css_vars(theme: dict[str, Any], image_url: str | None) -> dict[str, str]:
    """The CSS custom properties that carry a theme, for both the first paint and live updates. A preset or colour override
    sets only the colours it names; the rest come from the page's own light and dark defaults."""
    colors = {**PRESETS.get(theme["preset"], {}), **theme["colors"]}
    size, repeat = FITS[theme["fit"]]
    return {
        **{f"--{k}": v for k, v in colors.items()},
        "--bg-image": f'url("{image_url}")' if image_url else "none",
        "--img-dim": str(theme["dim"]), "--img-blur": f'{theme["blur"]}px', "--img-size": size, "--img-repeat": repeat,
        "--panel-alpha": str(round(1 - theme["glass"], 2) if image_url else 1),
        "--font-body": FONTS[theme["font"]],
    }


def root_block(variables: dict[str, str]) -> str:
    """The theme's variables as a :root rule, for the page's first paint."""
    return ":root{" + ";".join(f"{k}:{v}" for k, v in variables.items()) + "}"


def safe_css(css: str) -> str:
    """The user's CSS for a <style> element: `</style` is broken up so the CSS can't end the element and add markup."""
    return re.sub(r"</(style)", r"<\\/\1", css, flags=re.IGNORECASE)
