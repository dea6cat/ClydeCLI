"""Cut the generated environment sheets into the named pictures the station page uses (dev-only: Pillow, numpy, scipy).

    python tools/build_env_art.py <folder with the sheets> <output folder>

The sheets (file names as they came from the generator):
  furniture  "Isometric Pixel-Art Furniture Asset Sheet.png"   20 pieces of furniture, each in an unlit and a lit version
  tiles      "Art Deco Isometric Tileset Collection.png"       floors, walls, rails, pictures, a clock, an awning, a neon sign, lights
  scenery    "Isometric Fantasy City Asset Sheet.png"          moon, clouds, trees, hedge, lamp post, stars
  backs      "Isometric Pixel-Art Furniture Back Views.jpeg"   16 pieces seen from behind (optional); only the plain back panels are used
"""
from __future__ import annotations

# pylint: disable=import-error,wrong-import-position

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).parent))
from slice_env import blobs, load, reading_order  # noqa: E402

FURNITURE = ["file-cabinet", "writer-desk", "safe", "radio", "switchboard", "cupboard", "signing-desk", "cash-register", "report-desk", "planning-table",
             "mail-cabinet", "bar", "sofa", "small-table", "floor-lamp", "water-cooler", "coat-rack", "bookcase", "fern", "ficus"]   # reading order, each twice: unlit, lit
TILES = {0: "floor-parquet", 4: "wall-brick-a", 5: "wall-brick-b", 6: "wall-glass-a", 7: "wall-glass-b", 8: "wall-window-a", 9: "wall-window-b", 10: "door-a", 11: "door-b",
         14: "balustrade-a", 15: "balustrade-b", 20: "tower-a", 21: "tower-b", 24: "gatepost-a", 25: "gatepost-b", 26: "clock-a", 27: "clock-b",
         28: "picture-city", 29: "picture-hills-a", 30: "picture-hills-b", 31: "picture-leaf", 32: "awning-a", 33: "awning-b", 34: "neon-a", 35: "neon-b",
         36: "lights-a", 37: "lights-b"}
BACKS = {0: "file-cabinet", 1: "writer-desk", 2: "safe", 3: "radio", 4: "switchboard", 5: "cupboard", 6: "signing-desk", 7: "cash-register", 8: "report-desk",
         10: "mail-cabinet", 11: "bar", 15: "bookcase"}   # by their place on the back-views sheet; 9, 12, 13 are spare plain panels and 14 a curved counter
GRASS, ROCK = (180, 64, 262, 94), (125, 205, 235, 275)   # boxes in the island picture: grass, and the cliff face
SPLIT = {2: ("floor-runner", "floor-checker"), 3: ("floor-stone", "floor-water")}   # two tiles that came out as one piece
SCENERY = {0: "island", 12: "car-black", 13: "car-red", 14: "car-green", 1: "moon", 2: "stars", 3: "cloud-1", 4: "cloud-2", 5: "cloud-3", 6: "cloud-4", 7: "cloud-5", 8: "tree-blossom", 9: "tree-pine", 10: "hedge", 11: "lamppost"}


def crop(rgba: np.ndarray, box: tuple[int, int, int, int], largest: bool = True) -> Image.Image:
    x0, y0, x1, y1 = box
    piece = rgba[y0:y1, x0:x1].copy()
    if largest:   # a neighbour's fringe or a speck that rode along: keep only the biggest blob
        labels, count = ndimage.label(ndimage.binary_dilation(piece[:, :, 3] > 0, iterations=2))
        if count > 1:
            keep = np.argmax(ndimage.sum(piece[:, :, 3] > 0, labels, range(1, count + 1))) + 1
            piece[(labels != keep) & (piece[:, :, 3] > 0)] = 0
    piece[piece[:, :, 3] == 0] = 0
    ys, xs = np.nonzero(piece[:, :, 3])
    return Image.fromarray(piece[ys.min():ys.max() + 1, xs.min():xs.max() + 1])


def pieces(sheet: Path, kind: str, grow: int) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    rgba = load(sheet, kind)
    return rgba, reading_order(blobs(rgba[:, :, 3], grow=grow))


def main(src: Path, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    rgba, boxes = pieces(src / "Isometric Pixel-Art Furniture Asset Sheet.png", "checker", 4)
    assert len(boxes) == 40, f"furniture sheet: {len(boxes)} pieces, expected 40"
    for i, name in enumerate(FURNITURE):
        for j, state in enumerate(("off", "on")):
            crop(rgba, boxes[i * 2 + j]).save(dest / f"furn-{name}-{state}.png")
    rgba, boxes = pieces(src / "Art Deco Isometric Tileset Collection.png", "alpha", 4)
    assert len(boxes) == 38, f"tile sheet: {len(boxes)} pieces, expected 38"
    for i, name in TILES.items():
        crop(rgba, boxes[i]).save(dest / f"tile-{name}.png")
    for i, names in SPLIT.items():
        part = np.asarray(crop(rgba, boxes[i], largest=False))
        halves = reading_order(blobs(part[:, :, 3], min_area=200, grow=1))
        assert len(halves) == 2, f"tile piece {i}: {len(halves)} parts"
        for name, box in zip(names, halves):
            crop(part, box, largest=False).save(dest / f"tile-{name}.png")
    rgba, boxes = pieces(src / "Isometric Fantasy City Asset Sheet.png", "checker", 1)
    assert len(boxes) == 17, f"scenery sheet: {len(boxes)} pieces, expected 17"
    for i, name in SCENERY.items():
        crop(rgba, boxes[i]).save(dest / f"scene-{name}.png")
    back_sheet = src / "Isometric Pixel-Art Furniture Back Views.jpeg"
    if back_sheet.exists():
        rgba, boxes = pieces(back_sheet, "checker", 4)
        assert len(boxes) == 16, f"back-views sheet: {len(boxes)} pieces, expected 16"
        for i, name in BACKS.items():
            crop(rgba, boxes[i]).save(dest / f"furn-{name}-back.png")
    island = Image.open(dest / "scene-island.png")   # its grass and its cliff face tile as the island's surface and the rock under it
    patch = island.crop(GRASS).convert("RGBA")   # mirrored on both axes, so its edges meet their own copies and no seam shows when it repeats
    grass = Image.new("RGBA", (patch.width * 2, patch.height * 2))
    for i, flip in enumerate([(False, False), (True, False), (False, True), (True, True)]):
        part = patch.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if flip[0] else patch
        part = part.transpose(Image.Transpose.FLIP_TOP_BOTTOM) if flip[1] else part
        grass.paste(part, ((i % 2) * patch.width, (i // 2) * patch.height))
    grass.save(dest / "scene-grass.png")
    island.crop(ROCK).save(dest / "scene-rock.png")
    print(len(FURNITURE) * 2 + len(TILES) + 4 + len(SCENERY) + 2 + (len(BACKS) if back_sheet.exists() else 0), "pictures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
