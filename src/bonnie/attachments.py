"""Files attached to a message in Bonnie.

Uploads are held in memory until the message that names them is queued (nothing is written to disk by the upload itself).
Images go to the model as image blocks through the REPL's existing [Image #N] markers, so the size cap, the shrink step and the
"this model can't read images" check are the terminal's own. Text and code files are put into the message as labelled blocks,
which the page hides from the bubble and shows as chips instead. Anything else is refused with a reason.
"""
from __future__ import annotations

import base64
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.agent.conversation import ImageContentBlock
from src.bonnie.theme import sniff_image
from src.repl.images import MAX_IMAGE_BYTES, shrink

MAX_FILE = 12_000_000      # the most one upload may be
MAX_TEXT_FILE = 200_000    # the most of a text file that goes into a message
MAX_FILES = 6              # attachments on one message
MAX_STORED = 24            # uploads waiting for a message; the oldest go first
TTL_SECONDS = 3600
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
_BLOCK = re.compile(r'\n*<attached_file name="([^"\n]*)">\n(.*?)\n</attached_file>', re.DOTALL)
_MARKER = re.compile(r"\s*\[Image #\d+\]")


@dataclass
class Attachment:
    name: str
    kind: str                 # "image" or "text"
    media_type: str
    data: bytes
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    note: str = ""
    at: float = field(default_factory=time.monotonic)

    @property
    def size(self) -> int:
        return len(self.data)

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "kind": self.kind, "size": self.size, "note": self.note}


def clean_name(name: str) -> str:
    """A file name safe to put in a label: one line, no quotes or path, at most 80 characters."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = " ".join(name.replace('"', "'").split())
    return (name or "file")[:80]


def classify(name: str, data: bytes) -> Attachment:
    """The attachment for these bytes, or ValueError saying why it can't be used."""
    name = clean_name(name)
    if not data:
        raise ValueError(f"{name} is empty")
    kind = sniff_image(data)
    if kind in IMAGE_TYPES:
        if len(data) > MAX_IMAGE_BYTES:
            small = shrink(data)
            if small is None:
                raise ValueError(f"{name} is over {MAX_IMAGE_BYTES // 2**20} MB and couldn't be made smaller")
            return Attachment(name, "image", "image/jpeg", small, note=f"Shrunk from {len(data) / 2**20:.1f} MB to {len(small) / 2**20:.1f} MB.")
        return Attachment(name, "image", IMAGE_TYPES[kind], data)
    if len(data) > MAX_TEXT_FILE:
        raise ValueError(f"{name} is over {MAX_TEXT_FILE // 1000} KB, which is too much to put in a message. Attach a smaller piece")
    if b"\x00" in data[:8192]:
        raise ValueError(f"Bonnie can't read {name} yet. Images and text files work")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"Bonnie can't read {name} yet. Images and text files work") from None
    return Attachment(name, "text", "text/plain", data)


class Store:
    """Uploads waiting for the message that will use them."""

    def __init__(self) -> None:
        self._items: dict[str, Attachment] = {}
        self._lock = threading.Lock()

    def add(self, name: str, data: bytes) -> Attachment:
        item = classify(name, data)
        with self._lock:
            self._purge()
            self._items[item.id] = item
            for old in sorted(self._items.values(), key=lambda a: a.at)[:max(0, len(self._items) - MAX_STORED)]:
                del self._items[old.id]
        return item

    def take(self, ids: list[str]) -> list[Attachment]:
        """The named uploads, removed from the store; ValueError when one is unknown, repeated or has expired."""
        if len(ids) > MAX_FILES:
            raise ValueError(f"attach at most {MAX_FILES} files to a message")
        with self._lock:
            self._purge()
            if len(set(ids)) != len(ids) or any(i not in self._items for i in ids):
                raise ValueError("an attachment has expired or was already sent; attach it again")
            return [self._items.pop(i) for i in ids]

    def _purge(self) -> None:
        cutoff = time.monotonic() - TTL_SECONDS
        for old in [a.id for a in self._items.values() if a.at < cutoff]:
            del self._items[old]


def apply_to_turn(repl: Any, text: str, files: list[Attachment]) -> tuple[str, int]:
    """The message to send and how many images it carries. Images are kept on the REPL under the next [Image #N] numbers
    (the terminal's mechanism); text files follow the message as labelled blocks."""
    parts, markers, images = [text.strip()], [], 0
    for item in files:
        if item.kind == "image":
            number = len(repl._pastes) + 1
            repl._pastes[number] = ImageContentBlock(media_type=item.media_type, data=base64.b64encode(item.data).decode("ascii"))
            markers.append(f"[Image #{number}]")
            images += 1
    if markers:
        parts[0] = (parts[0] + " " + " ".join(markers)).strip()
    for item in files:
        if item.kind == "text":
            body = item.data.decode("utf-8").replace("</attached_file", "<\\/attached_file")
            parts.append(f'<attached_file name="{item.name}">\n{body}\n</attached_file>')
    return "\n\n".join(p for p in parts if p), images


def split(text: str) -> tuple[str, list[str]]:
    """(what the user typed, the names of the text files that came with it): the page shows the files as chips."""
    names = [m.group(1) for m in _BLOCK.finditer(text)]
    visible = _MARKER.sub("", _BLOCK.sub("", text)).strip()
    return visible, names
