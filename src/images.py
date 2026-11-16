"""Images pasted into the prompt: from the clipboard (Ctrl+V) or as a copied file path (Cmd+V)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

# What every provider accepts, and Anthropic's per-image cap.
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def shrink(data: bytes) -> bytes | None:
    """The image re-encoded as JPEG, longest side 2048 px, when that brings it under MAX_IMAGE_BYTES;
    None when it can't be shrunk here. Uses macOS's built-in `sips`; other systems get None."""
    if sys.platform != "darwin" or not shutil.which("sips"):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "in", Path(tmp) / "out.jpg"
        src.write_bytes(data)
        done = subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "80", "-Z", "2048", str(src),
                               "--out", str(out)], capture_output=True)
        small = out.read_bytes() if done.returncode == 0 and out.exists() else b""
    return small if 0 < len(small) <= MAX_IMAGE_BYTES else None


def clipboard_image() -> bytes | None:
    """PNG bytes of the image on the clipboard, or None when it holds no image."""
    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "clip.png"
            script = (f'set f to open for access POSIX file "{out}" with write permission',
                      "write (the clipboard as «class PNGf») to f", "close access f")
            done = subprocess.run(["osascript", *(a for line in script for a in ("-e", line))], capture_output=True)
            return (out.read_bytes() or None) if done.returncode == 0 and out.exists() else None
    for cmd in (["wl-paste", "--type", "image/png"], ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"]):
        if shutil.which(cmd[0]):
            done = subprocess.run(cmd, capture_output=True)
            if done.returncode == 0 and done.stdout:
                return done.stdout
    return None


def image_path(text: str) -> Path | None:
    """The image file a pasted string names (quoted, backslash-escaped or file:// as terminals copy it), else None."""
    raw = text.strip()
    if not raw or "\n" in raw:
        return None
    if len(raw) > 1 and raw[0] == raw[-1] and raw[0] in "'\"":
        raw = raw[1:-1]
    if raw.startswith("file://"):
        raw = unquote(raw[len("file://"):])
    path = Path(raw.replace("\\ ", " ")).expanduser()
    return path if path.suffix.lower() in IMAGE_TYPES and path.is_file() else None
