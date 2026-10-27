"""Cut an environment sheet (furniture, floors, walls, scenery) into one transparent PNG per item (dev-only: Pillow, numpy, scipy).

Items are found as separate blobs and named in reading order: rows top to bottom, left to right within a row.

    python tools/slice_env.py <sheet.png> <checker|alpha> <output folder> [name1,name2,...] [grow]

`checker`: the picture has a light checkerboard (or flat magenta) baked in; `alpha`: it has real transparency (faint, stray pixels are dropped).
`grow` (default 4) is how many pixels apart two pieces may be and still count as one item; lower it when neighbours get merged.
Without names, or when the count does not match, the pieces are saved as piece-00, piece-01, ... to be named by eye.
"""
from __future__ import annotations

# pylint: disable=import-error,wrong-import-position

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).parent))
from slice_crew import cutout  # noqa: E402


def load(path: Path, kind: str) -> np.ndarray:
    if kind == "checker":
        return cutout(Image.open(path))
    rgba = np.asarray(Image.open(path).convert("RGBA")).copy()
    rgba[:, :, 3] = np.where(rgba[:, :, 3] > 170, 255, 0)
    return rgba


def blobs(alpha: np.ndarray, min_area: int = 500, grow: int = 4) -> list[tuple[int, int, int, int]]:
    """Boxes (x0, y0, x1, y1) of the items: pieces closer than a few pixels are one item, specks are dropped."""
    near = ndimage.binary_dilation(alpha > 0, iterations=grow)
    labels, _ = ndimage.label(near)
    boxes = []
    for index, sl in enumerate(ndimage.find_objects(labels), start=1):
        mask = (labels[sl] == index) & (alpha[sl] > 0)
        ys, xs = np.nonzero(mask)
        if mask.sum() >= min_area:
            boxes.append((sl[1].start + xs.min(), sl[0].start + ys.min(), sl[1].start + xs.max() + 1, sl[0].start + ys.max() + 1))
    return boxes


def reading_order(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    rows: list[list[tuple[int, int, int, int]]] = []
    for box in sorted(boxes, key=lambda b: b[1]):
        centre = (box[1] + box[3]) / 2
        for row in rows:
            if min(b[1] for b in row) <= centre <= max(b[3] for b in row):
                row.append(box)
                break
        else:
            rows.append([box])
    return [b for row in rows for b in sorted(row)]


def main(sheet: Path, kind: str, dest: Path, names: list[str], grow: int = 4) -> int:
    rgba = load(sheet, kind)
    boxes = reading_order(blobs(rgba[:, :, 3], grow=grow))
    dest.mkdir(parents=True, exist_ok=True)
    if names and len(names) != len(boxes):
        print(f"found {len(boxes)} items, {len(names)} names: saving as numbered pieces instead", file=sys.stderr)
        names = []
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        crop = rgba[y0:y1, x0:x1].copy()
        crop[crop[:, :, 3] == 0] = 0   # nothing of the old background rides along under the cut edge
        Image.fromarray(crop).save(dest / f"{names[i] if names else f'piece-{i:02d}'}.png")
    print(f"{len(boxes)} items from {sheet.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] else [], int(sys.argv[5]) if len(sys.argv) > 5 else 4))
