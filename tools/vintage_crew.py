"""Give the crew sprites a 1930s look: a period colour grade and a hat on every head.

Reads the original frames (named `<pack>-<idle|walk>-<direction>-<nn>.png`, from the elie automata packs) from a folder and
writes the changed frames to another. Run it once when the art changes; the changed frames are what ships in
`src/agent/station_art/`. It needs Pillow, which is a development tool only and not a Clyde dependency.

    python tools/vintage_crew.py ORIGINALS_DIR src/agent/station_art
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

# pack -> (hat style, crown colour, band colour): a different hat for each person so the crew read apart
HATS = {
    "rogue": ("fedora", (38, 38, 44), (120, 30, 36)),
    "paladin": ("fedora", (104, 86, 62), (30, 28, 26)),
    "reaper": ("flatcap", (92, 80, 64), (60, 52, 42)),
    "hunter": ("cloche", (44, 58, 92), (226, 204, 160)),
    "admiral": ("captain", (28, 38, 66), (236, 232, 220)),
}
FRAME = re.compile(r"(?P<pack>[a-z]+)-(?P<anim>idle|walk)-(?P<dir>[a-z\-]+)-(?P<n>\d+)\.png")
OUTLINE = (14, 12, 18, 255)


def grade(img: Image.Image) -> Image.Image:
    """Fade the colour, warm it toward sepia and lift the shadows a little, as an old print would."""
    rgb, alpha = img.convert("RGB"), img.getchannel("A")
    rgb = ImageEnhance.Color(rgb).enhance(0.55)
    rgb = ImageEnhance.Contrast(rgb).enhance(0.94)
    rgb = Image.blend(rgb, Image.new("RGB", rgb.size, (150, 112, 70)), 0.16)
    rgb = ImageEnhance.Brightness(rgb).enhance(1.04)
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def figure(img: Image.Image) -> tuple[int, int, int, int] | None:
    return img.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()


def head(img: Image.Image, box: tuple[int, int, int, int]) -> tuple[float, int]:
    """The horizontal centre of the head and the row its top is on: the middle of the figure's topmost rows."""
    x0, y0, x1, y1 = box
    rows = max(2, int((y1 - y0) * 0.1))
    alpha = img.getchannel("A").crop((x0, y0, x1, y0 + rows))
    xs = [x0 + x for x in range(alpha.width) for y in range(alpha.height) if alpha.getpixel((x, y)) > 40]
    return (sum(xs) / len(xs) if xs else (x0 + x1) / 2), y0


def hat(img: Image.Image, pack: str, direction: str) -> Image.Image:
    box = figure(img)
    if box is None:
        return img
    height = box[3] - box[1]
    cx, top = head(img, box)
    style, crown, band = HATS[pack]
    side = {"east": 1, "north-east": 1, "south-east": 1, "west": -1, "north-west": -1, "south-west": -1}.get(direction, 0)
    cx += height * 0.03 * side   # a hat sits a little to the side the face turns
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c, b = crown + (255,), band + (255,)
    shade = tuple(max(0, v - 28) for v in crown) + (255,)
    lift = tuple(min(255, v + 30) for v in crown) + (255,)

    def ell(x0, y0, x1, y1, fill):
        d.ellipse((cx + x0 * height, top + y0 * height, cx + x1 * height, top + y1 * height), fill=fill, outline=OUTLINE)

    def rect(x0, y0, x1, y1, fill):
        d.rectangle((cx + x0 * height, top + y0 * height, cx + x1 * height, top + y1 * height), fill=fill)

    drop = 0.03   # the hat comes down over the top of the head, so a hood or hair does not show above it
    if style == "fedora":
        ell(-0.27, 0.12 + drop, 0.27, 0.24 + drop, shade)     # the brim
        rect(-0.15, -0.03 + drop, 0.15, 0.17 + drop, c)       # the crown
        ell(-0.15, -0.07 + drop, 0.15, 0.03 + drop, c)
        rect(-0.15, 0.11 + drop, 0.15, 0.16 + drop, b)        # the band
        rect(-0.03, -0.05 + drop, 0.03, -0.01 + drop, shade)  # the pinch
        rect(-0.15, 0.00 + drop, -0.12, 0.10 + drop, lift)
    elif style == "cloche":
        ell(-0.20, -0.05 + drop, 0.20, 0.23 + drop, c)        # a dome that comes down over the ears
        ell(-0.22, 0.15 + drop, 0.22, 0.24 + drop, shade)     # the narrow brim
        rect(-0.19, 0.13 + drop, 0.19, 0.16 + drop, b)
        ell(-0.16, -0.02 + drop, -0.05, 0.06 + drop, lift)
    elif style == "flatcap":
        ell(-0.22, 0.01 + drop, 0.22, 0.17 + drop, c)         # a soft, flat crown
        ell(-0.17, -0.02 + drop, 0.17, 0.09 + drop, lift)
        if direction.startswith("south"):
            ell(-0.15, 0.12 + drop, 0.15, 0.20 + drop, shade)  # the peak, turned to the viewer
        else:
            rect(-0.20, 0.13 + drop, 0.20, 0.16 + drop, shade)
    else:  # a captain's cap
        ell(-0.24, 0.13 + drop, 0.24, 0.22 + drop, shade)     # the peak
        rect(-0.20, -0.02 + drop, 0.20, 0.16 + drop, c)       # the crown
        ell(-0.20, -0.06 + drop, 0.20, 0.05 + drop, lift)
        rect(-0.20, 0.11 + drop, 0.20, 0.15 + drop, b)        # a white band
    out = img.copy()
    out.alpha_composite(layer)
    return out


def main(source: Path, target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for file in sorted(source.glob("*.png")):
        m = FRAME.fullmatch(file.name)
        if not m or m["pack"] not in HATS:
            continue
        out = hat(grade(Image.open(file).convert("RGBA")), m["pack"], m["dir"])
        out.save(target / file.name, optimize=True)
        count += 1
    print(f"{count} frames written to {target}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
