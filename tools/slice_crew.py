"""Cut the generated crew sheets into the frames the station page reads (dev-only: needs Pillow, numpy and scipy).

Each sheet has eight columns (the facings, as a turntable) and rows of frames in blocks labelled IDLE, WALK and TYPE. The picture has a
light checkerboard baked in instead of transparency, so the background is removed first: light, colourless pixels that connect to the
border. The frames land on a 96 x 96 canvas, feet (or the keyboard's bottom edge) on the same line, centred on the figure.

    python tools/slice_crew.py <folder with the sheets> <output folder>
"""
from __future__ import annotations

# pylint: disable=import-error,too-many-locals,cell-var-from-loop,unnecessary-lambda-assignment

import glob
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

SHEETS = {"clyde": "clyde - *", "bonnie": "bonnie - *", "master": "master - *", "advisor": "advisor - *",
          "newsboy": "newsboy - *", "mechanic": "mecanic - *", "clerk": "clerk - *"}
DIRS = ["south-west", "west", "south", "south-east", "east", "north-east", "north", "north-west"]   # the turntable's order, left to right: front-left, left, front, front-right, then the backs (it has no clean profiles)
TYPING_DIRS = ["south-west", "south", "south-east"]
CELL, FOOT = 96, 90   # the frame is square; the figure's bottom edge sits on this row


def cutout(image: Image.Image) -> np.ndarray:
    """RGBA array with the background made transparent: a flat magenta one is keyed out, a baked-in light checkerboard is flood-removed."""
    rgb = np.asarray(image.convert("RGB")).astype(int)
    if rgb[2, 2, 0] > 200 and rgb[2, 2, 2] > 200 and rgb[2, 2, 1] < 80:
        magenta = (rgb[:, :, 0] - rgb[:, :, 1] > 70) & (rgb[:, :, 2] - rgb[:, :, 1] > 70)   # also the pinkish fringe of an edge
        alpha = (~magenta).astype(np.uint8) * 255
        alpha[ndimage.binary_opening(alpha > 0, iterations=1) == 0] = 0
        return np.dstack([rgb.astype(np.uint8), alpha])
    light = (rgb.min(axis=2) >= 214) & (rgb.max(axis=2) - rgb.min(axis=2) <= 18)
    regions, _ = ndimage.label(light)
    edge = set(np.unique(np.concatenate([regions[0], regions[-1], regions[:, 0], regions[:, -1]]))) - {0}
    background = np.isin(regions, list(edge))
    alpha = (~background).astype(np.uint8) * 255
    alpha[ndimage.binary_opening(alpha > 0, iterations=1) == 0] = 0   # lone specks of the checkerboard
    lum, chroma = rgb.mean(axis=2), rgb.max(axis=2) - rgb.min(axis=2)
    for _ in range(2):   # the light fringe the cut leaves round an edge: pale, colourless pixels touching the background
        clear = alpha == 0
        edge = ndimage.binary_dilation(clear) & ~clear
        alpha[edge & (lum > 165) & (chroma < 45)] = 0
    return np.dstack([rgb.astype(np.uint8), alpha])


def groups(alpha: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Bounding boxes (x0, y0, x1, y1) of the figures: pixels within a couple of columns of each other are one figure."""
    near = ndimage.binary_dilation(alpha > 0, structure=np.array([[0, 0, 0], [1, 1, 1], [0, 0, 0]]), iterations=2)   # sideways only: the rows of frames nearly touch
    labels, _ = ndimage.label(near)
    boxes = []
    for index, sl in enumerate(ndimage.find_objects(labels), start=1):
        mask = (labels[sl] == index) & (alpha[sl] > 0)
        ys, xs = np.nonzero(mask)
        if len(ys):
            boxes.append((sl[1].start + xs.min(), sl[0].start + ys.min(), sl[1].start + xs.max() + 1, sl[0].start + ys.max() + 1))
    return boxes


def split_tall(boxes: list[tuple[int, int, int, int]], alpha: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Frames whose hat touches the feet above them come out as one tall figure: cut each at the thinnest row."""
    heights = sorted(b[3] - b[1] for b in boxes if b[3] - b[1] >= 30)
    usual = heights[len(heights) // 2]
    out = []
    for x0, y0, x1, y1 in boxes:
        parts = round((y1 - y0) / usual) if y1 - y0 >= 30 else 1
        cuts = [y0]
        for k in range(1, parts):
            guess = y0 + (y1 - y0) * k // parts
            window = range(max(y0 + 10, guess - 10), min(y1 - 10, guess + 10))
            cuts.append(min(window, key=lambda y: int((alpha[y, x0:x1] > 0).sum())))
        cuts.append(y1)
        for a, b in zip(cuts, cuts[1:]):
            ys, xs = np.nonzero(alpha[a:b, x0:x1] > 0)
            if len(ys):
                out.append((x0 + xs.min(), a + ys.min(), x0 + xs.max() + 1, a + ys.max() + 1))
    return out


def layout(boxes: list[tuple[int, int, int, int]]) -> tuple[list[list[tuple[int, int, int, int]]], list[int]]:
    """Figures grouped into rows (top to bottom, left to right), and the y of each label (IDLE, WALK, TYPE)."""
    figures = [b for b in boxes if b[3] - b[1] >= 30]
    found = sorted(b[1] for b in boxes if b[3] - b[1] < 30 and b[2] - b[0] > 40)
    labels = [y for i, y in enumerate(found) if not i or y - found[i - 1] > 40]   # a label is its text and its underline: one entry
    figures.sort(key=lambda b: (b[1] + b[3]) / 2)
    rows: list[list[tuple[int, int, int, int]]] = []
    for box in figures:
        if rows and abs((box[1] + box[3]) / 2 - np.mean([(b[1] + b[3]) / 2 for b in rows[-1]])) < 42:
            rows[-1].append(box)
        else:
            rows.append([box])
    return [sorted(r) for r in rows], labels


def frame(rgba: np.ndarray, box: tuple[int, int, int, int], centre: float) -> Image.Image:
    """The figure on a square canvas. It sits where it sat in its column of the sheet (`centre` is the column's usual middle), not
    centred on itself, so a swinging arm or leg does not shake the body from frame to frame."""
    x0, y0, x1, y1 = box
    crop = Image.fromarray(rgba[y0:y1, x0:x1])
    scale = min(1.0, (FOOT - 2) / crop.height, (CELL - 2) / crop.width)
    if scale < 1:
        crop = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))), Image.Resampling.NEAREST)
    out = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
    out.paste(crop, (round(CELL / 2 + (x0 - centre) * scale), FOOT - crop.height))
    return out


def slice_sheet(person: str, path: str, dest: Path, take: set[str], has_typing: bool) -> dict[str, int]:
    rgba = cutout(Image.open(path))
    alpha = rgba[:, :, 3]
    rows, _ = layout(split_tall(groups(alpha), alpha))
    width = lambda r: float(np.median([b[2] - b[0] for b in r[:4]]))
    wide = lambda r: width(r) >= 1.2 * width(rows[0])
    # Rows are told apart by what is in them: the first three are idle, a row whose front-facing figures are wide (a keyboard in front of
    # them) starts the typing block, and what lies between is walking.
    typing = next((i for i, r in enumerate(rows) if has_typing and i >= 3 and wide(r)), len(rows))
    rows = [(r, "type" if i >= typing else "idle" if i < 3 else "walk") for i, r in enumerate(rows)]
    rows = [(r, b) for r, b in rows if len(r) == 8]
    middles = [float(np.median([(r[c][0] + r[c][2]) / 2 for r, _ in rows])) for c in range(8)]
    counts = {"idle": 0, "walk": 0, "type": 0}
    for row, block in rows:
        if block in take:
            for col, box in enumerate(row):
                frame(rgba, box, middles[col]).save(dest / f"{person}-{block}-{DIRS[col]}-{counts[block]:02d}.png")
            counts[block] += 1
    return counts


def slice_typing(person: str, path: str, dest: Path) -> int:
    """A typing sheet: 3 columns (south-west, south, south-east) and a row per frame, the person standing with the hands up at waist height."""
    rgba = cutout(Image.open(path))
    alpha = rgba[:, :, 3]
    rows, _ = layout(split_tall(groups(alpha), alpha))
    rows = [r for r in rows if len(r) == 3]
    middles = [float(np.median([(r[c][0] + r[c][2]) / 2 for r in rows])) for c in range(3)]
    for n, row in enumerate(rows):
        for col, box in enumerate(row):
            frame(rgba, box, middles[col]).save(dest / f"{person}-type-{TYPING_DIRS[col]}-{n:02d}.png")
    return len(rows)


def main(src: Path, dest: Path) -> int:
    """A person's newest sheets: `<person>-sheet1-gen.png` (idle and walking) and `<person>-sheet2-gen.png` (typing), flat magenta background,
    no labels. Without them the older labelled sheet is used; without a typing sheet a person has no typing frames."""
    dest.mkdir(parents=True, exist_ok=True)
    figure = {}
    for person, pattern in SHEETS.items():
        new = src / f"{person}-sheet1-gen.png"
        typing = src / f"{person}-sheet2-gen.png"
        old = glob.glob(str(src / f"{pattern}.png"))
        counts = {}
        if new.exists():
            counts |= slice_sheet(person, str(new), dest, {"idle", "walk"}, False)
        elif old:
            counts = slice_sheet(person, old[0], dest, {"idle", "walk"}, True)
        else:
            print(f"{person}: no sheet", file=sys.stderr)
            continue
        if typing.exists():
            counts["type"] = slice_typing(person, str(typing), dest)
        print(person, counts)
        south = Image.open(dest / f"{person}-idle-south-00.png")
        figure[person] = south.getbbox()
    print("FIGURE:", {k: [CELL, CELL, *v] for k, v in figure.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
