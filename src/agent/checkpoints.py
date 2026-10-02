"""Edit checkpoints, for /rewind: the files the model changed, as they were before each message.

Each message you send opens a checkpoint. The first time Write, Edit or NotebookEdit touches a file
during that turn, the file's current bytes are saved (or a note that it didn't exist yet). Rewinding
to a checkpoint puts every file changed since then back as it was before that message (deleting files
the model created), and drops the later checkpoints. Changes made by shell commands aren't captured:
there's no reliable way to know what a command touches.

Stored per session under ~/.clyde/checkpoints/<session_id>/<n>/ (meta.json plus the saved files), so
they survive /resume. The newest 20 sessions' checkpoints are kept.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

KEEP_SESSIONS = 20
MAX_FILE_BYTES = 10 * 1024 * 1024   # ponytail: bigger files aren't snapshotted (rewind says so); raise if it bites


@dataclass
class Checkpoint:
    number: int
    prompt: str
    at: str
    message_index: int                     # conversation length before the message: where a rewind cuts
    files: list[dict] = field(default_factory=list)   # {"path", "existed", "blob"} or {"path", "skipped": reason}


def root() -> Path:
    return Path.home() / ".clyde" / "checkpoints"


class Checkpoints:
    def __init__(self, session_id: str) -> None:
        self.dir = root() / str(session_id)
        self._current: Checkpoint | None = None

    def _folder(self, number: int) -> Path:
        return self.dir / f"{number:05d}"

    def _save(self, cp: Checkpoint) -> None:
        folder = self._folder(cp.number)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "meta.json").write_text(json.dumps(cp.__dict__, indent=1), encoding="utf-8")

    def list(self) -> list[Checkpoint]:
        """Checkpoints, oldest first."""
        out = []
        for meta in sorted(self.dir.glob("*/meta.json")):
            try:
                out.append(Checkpoint(**json.loads(meta.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError):
                continue
        return out

    def begin(self, prompt: str, message_index: int) -> None:
        """Open the checkpoint for a new message."""
        existing = self.list()
        number = existing[-1].number + 1 if existing else 1
        self._current = Checkpoint(number, prompt[:200], datetime.now().isoformat(timespec="seconds"), message_index)
        self._save(self._current)
        _prune(self.dir)

    def snapshot(self, path: Path) -> None:
        """Save `path` as it is now, the first time this turn is about to change it."""
        cp = self._current
        if cp is None:
            return
        path = Path(path).resolve()
        if any(f["path"] == str(path) for f in cp.files):
            return
        entry: dict = {"path": str(path), "existed": path.exists()}
        if path.is_file():
            if path.stat().st_size > MAX_FILE_BYTES:
                entry = {"path": str(path), "skipped": f"over {MAX_FILE_BYTES // 2**20} MB"}
            else:
                blob = f"{len(cp.files):04d}"
                shutil.copy2(path, self._folder(cp.number) / blob)
                entry["blob"] = blob
        cp.files.append(entry)
        self._save(cp)

    def restore(self, number: int) -> tuple[list[str], list[str]]:
        """Put files back as they were before checkpoint `number` and drop it and every later one.
        Returns (restored paths, paths that couldn't be restored, with why)."""
        later = [cp for cp in self.list() if cp.number >= number]
        earliest: dict[str, tuple[Checkpoint, dict]] = {}
        for cp in later:                         # oldest first: the first snapshot is the state to go back to
            for f in cp.files:
                earliest.setdefault(f["path"], (cp, f))
        restored, problems = [], []
        for path_str, (cp, f) in earliest.items():
            path = Path(path_str)
            try:
                if f.get("skipped"):
                    problems.append(f"{path} ({f['skipped']}, not saved)")
                    continue
                if not f.get("existed"):
                    if path.is_file():
                        path.unlink()
                    restored.append(f"{path} (removed: the model created it)")
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self._folder(cp.number) / f["blob"], path)
                restored.append(str(path))
            except OSError as e:
                problems.append(f"{path} ({e})")
        for cp in later:
            shutil.rmtree(self._folder(cp.number), ignore_errors=True)
        self._current = None
        return restored, problems


def _prune(current: Path) -> None:
    """Keep the newest KEEP_SESSIONS sessions' checkpoints."""
    try:
        sessions = sorted((d for d in root().iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in sessions[KEEP_SESSIONS:]:
        if old != current:
            shutil.rmtree(old, ignore_errors=True)
