"""Draw the crew of the web station: seven people in 1930s clothes, each seen from eight directions, standing and walking.

Each person is a small model of boxes (head, hat, jacket, arms, legs, shoes). The script turns the model to face each direction,
lights it from the upper left, draws it from above and in front as the station does, and writes one PNG per frame:
`<person>-<idle|walk>-<direction>-<nn>.png`. The pictures are made here, so no outside art is involved. It needs Pillow, a
development tool only and not a Clyde dependency.

    python tools/make_crew.py src/agent/station_art
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

PITCH = math.radians(34)   # how far above the people the camera is
SC = 1.5                   # pixels per model unit
SS = 4                     # drawn this many times larger, then sampled down: crisp pixels
CANVAS = 96
BASE_Y = 0.88              # where the feet are, as a fraction of the picture's height
FRAMES = 8
OUTLINE = (22, 16, 24, 255)
DIRS = {"south": 0, "south-east": -45, "east": -90, "north-east": -135, "north": 180, "north-west": 135, "west": 90, "south-west": 45}
TOWARD = (0.0, math.cos(PITCH), math.sin(PITCH))   # from the scene to the camera
LIGHT = (-0.5, 0.55, 0.8)

# A box is (part, x0, x1, y0, y1, z0, z1, colour): x is the person's right, y is forward, z is up, feet at 0.
Box = tuple


def hexc(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def tone(c: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(v * f))) for v in c)  # type: ignore[return-value]


class Builder:
    def __init__(self) -> None:
        self.boxes: list[Box] = []

    def add(self, part: str, x0: float, x1: float, y0: float, y1: float, z0: float, z1: float, colour: str) -> None:
        self.boxes.append((part, x0, x1, y0, y1, z0, z1, hexc(colour)))

    def pair(self, part_l: str, part_r: str, x0: float, x1: float, y0: float, y1: float, z0: float, z1: float, colour: str) -> None:
        """The same box on both sides: x0 to x1 on the right, mirrored on the left."""
        self.add(part_l, -x1, -x0, y0, y1, z0, z1, colour)
        self.add(part_r, x0, x1, y0, y1, z0, z1, colour)


def hat_boxes(b: Builder, hat: str, colour: str) -> None:
    if hat == "fedora":
        b.add("hat", -3.6, 3.6, -3.8, 3.8, 37, 41, colour)
        b.add("hat", -3.7, 3.7, -3.9, 3.9, 37, 38.3, "#7a1f26")                 # the band
        b.add("hat", -6.4, 6.4, -6.4, 6.4, 36.6, 37.6, colour)                  # the brim
    elif hat == "cloche":
        b.add("hat", -4.9, 4.9, -5, 5.2, 33.5, 37.5, colour)                    # a bell that comes down over the ears
        b.add("hat", -4.3, 4.3, -4.4, 4.6, 37.5, 40.5, colour)
        b.add("hat", -2.8, 2.8, -2.9, 3.1, 40.5, 41.6, colour)
        b.add("hat", -5.1, 5.1, -5.2, 5.4, 35.4, 36.4, "#e9d9b4")
    elif hat == "flatcap":
        b.add("hat", -5, 5, -5, 5, 36.6, 39.4, colour)
        b.add("hat", -3.6, 3.6, 4.8, 8, 36.4, 37.4, "#2b2620")                  # the peak
    elif hat == "captain":
        b.add("hat", -4.8, 4.8, -4.8, 4.8, 37, 40.6, colour)
        b.add("hat", -4.9, 4.9, -4.9, 4.9, 37, 38.2, "#ece8dc")
        b.add("hat", -4.4, 4.4, -4.4, 4.4, 40.6, 41.2, "#ece8dc")
        b.add("hat", -3.8, 3.8, 4.8, 8.6, 36.6, 37.6, "#15161c")
        b.add("hat", -1.1, 1.1, 5, 5.4, 38.6, 40, "#d6b34a")
    elif hat == "bowler":
        b.add("hat", -4.2, 4.2, -4.4, 4.4, 37, 39.4, colour)
        b.add("hat", -3.2, 3.2, -3.4, 3.4, 39.4, 41.2, colour)
        b.add("hat", -5.8, 5.8, -5.8, 5.8, 36.6, 37.5, colour)


def person(skin: str, hair: str, jacket: str, shirt: str, trousers: str, shoes: str, hat: str, hat_colour: str, extra: str = "", build: float = 1.0) -> list[Box]:
    """The common body: shoes, legs, a jacket over a shirt, arms and hands, a head with eyes and hair, a hat, then the outfit's own details."""
    b = Builder()
    w = 5.5 * build
    b.pair("legL", "legR", 0.3, 4.4, -1.8, 3.8, 0, 3, shoes)                   # shoes, longer toward the front
    b.pair("legL", "legR", 0.5, 4.2, -2.0, 2.0, 3, 14.5, trousers)             # legs
    b.add("torso", -w, w, -3.2, 3.2, 14, 27, jacket)                           # the jacket
    b.add("torso", -1.9, 1.9, 3.2, 3.5, 18, 27, shirt)                         # the shirt showing at the front
    b.pair("armL", "armR", w, w + 3.3, -1.8, 1.8, 15.5, 26.5, jacket)          # sleeves
    b.pair("armL", "armR", w + 0.1, w + 3.1, -1.5, 1.5, 12.5, 15.8, skin)      # hands
    b.add("torso", -1.1, 1.1, -1, 1, 26.5, 28.5, skin)                         # neck
    b.add("head", -4.4, 4.4, -4, 4.4, 28, 37, skin)                            # head
    b.add("head", -2.9, -1.5, 4.4, 4.7, 32, 34.2, "#16131a")                   # eyes
    b.add("head", 1.5, 2.9, 4.4, 4.7, 32, 34.2, "#16131a")
    b.add("head", -4.6, 4.6, -4.4, 1.2, 33, 37.4, hair)                        # hair: the back and the top of the head
    b.add("head", -4.6, 4.6, -4.4, 4.6, 36, 37.4, hair)
    b.add("head", -4.8, -4.4, -3.4, 2.6, 31.5, 36.5, hair)
    b.add("head", 4.4, 4.8, -3.4, 2.6, 31.5, 36.5, hair)
    hat_boxes(b, hat, hat_colour)
    outfit(b, extra, w, jacket)
    return b.boxes


def outfit(b: Builder, kind: str, w: float, jacket: str) -> None:
    if kind == "suit":           # a necktie, a pocket square, two rows of buttons: a double-breasted suit
        b.add("torso", -0.7, 0.7, 3.4, 3.8, 15, 26.4, "#8a2230")
        b.add("torso", w * 0.45, w * 0.45 + 1.8, 3.2, 3.6, 22.8, 23.6, "#ece8dc")
        for z in (16.5, 19.5, 22.5):
            b.add("torso", -3.4, -2.6, 3.2, 3.7, z, z + 0.8, "#c9a548")
            b.add("torso", 2.6, 3.4, 3.2, 3.7, z, z + 0.8, "#c9a548")
    elif kind == "coat":         # a naval coat: gold buttons down the front, gold cuffs and a grey beard
        for z in (16.5, 19, 21.5, 24):
            b.add("torso", -3, -2.2, 3.2, 3.7, z, z + 0.8, "#d6b34a")
            b.add("torso", 2.2, 3, 3.2, 3.7, z, z + 0.8, "#d6b34a")
        b.pair("armL", "armR", w - 0.1, w + 3.4, -1.9, 1.9, 15.5, 16.8, "#d6b34a")
        b.add("head", -3.4, 3.4, 2.4, 4.8, 28, 31.4, "#c9c6c0")
    elif kind == "tweed":        # a waistcoat, a bow tie and round glasses
        b.add("torso", -2.6, 2.6, 3.2, 3.6, 15, 24, "#6b4a2e")
        b.add("torso", -1.7, 1.7, 3.6, 3.9, 24.6, 26, "#7a1f26")
        b.add("head", -3.4, -1.4, 4.5, 4.9, 31.6, 34.6, "#2a2420")
        b.add("head", 1.4, 3.4, 4.5, 4.9, 31.6, 34.6, "#2a2420")
    elif kind == "dress":        # a dress: a skirt to the knee, a white collar, pearls
        b.add("skirt", -7.2, 7.2, -4.6, 4.6, 8.5, 15.5, jacket)
        b.add("skirt", -7.4, 7.4, -4.8, 4.8, 8.5, 9.6, "#e9d9b4")
        b.add("torso", -3.4, 3.4, 3.2, 3.7, 25, 27, "#f2ece0")
        for x in (-2.4, -1.2, 0, 1.2, 2.4):
            b.add("torso", x - 0.45, x + 0.45, 3.6, 4.1, 23.8 + abs(x) * 0.25, 24.8 + abs(x) * 0.25, "#f2ece0")
    elif kind == "braces":       # shirt sleeves, braces over a shirt, a neckerchief
        b.pair("torso", "torso", 2.4, 3.4, 3.2, 3.7, 15, 27, "#3a2a1e")
        b.add("torso", -1.6, 1.6, 3.4, 3.8, 24.5, 26.5, "#b33a3a")
    elif kind == "overalls":     # a work apron with a pocket and a red rag
        b.add("torso", -4, 4, 3.2, 3.7, 15, 22, jacket)
        b.add("torso", -2, 2, 3.7, 4, 18, 21, "#2b4a78")
        b.add("torso", 2.6, 3.8, 3.8, 4.1, 21, 23.5, "#b33a3a")
    elif kind == "clerk":        # a waistcoat, sleeve garters and a green eyeshade
        b.add("torso", -3.4, 3.4, 3.2, 3.7, 15, 24, "#1f1d22")
        b.add("torso", -1.1, 1.1, 3.7, 4, 17, 26, "#1f1d22")
        b.pair("armL", "armR", 5.4, 8.9, -1.9, 1.9, 20, 21.2, "#8a2230")
        b.add("hat", -4.9, 4.9, 0.4, 6.4, 35.2, 36.1, "#2e7d4f")
        b.add("hat", -4.6, 4.6, -4.4, 0.4, 36, 37, "#2e7d4f")


def motion(part: str, anim: str, frame: int) -> tuple[float, float]:
    """How far a part is moved from where it stands in this frame: forward, and up."""
    p = 2 * math.pi * frame / FRAMES
    if anim == "idle":
        return (0.0, 0.0) if part in ("legL", "legR", "skirt") else (0.0, 0.45 * (0.5 - 0.5 * math.cos(p)))
    s, c = math.sin(p), math.cos(p)
    if part == "legL":
        return 3.4 * s, 1.6 * max(0.0, c)
    if part == "legR":
        return -3.4 * s, 1.6 * max(0.0, -c)
    if part == "armL":
        return -3.0 * s, 0.9 * abs(c)
    if part == "armR":
        return 3.0 * s, 0.9 * abs(c)
    if part == "skirt":
        return 0.5 * s, 0.0
    return 0.0, 0.9 * abs(c)   # the body bobs as the feet land


def render(boxes: list[Box], yaw_deg: float, anim: str, frame: int) -> Image.Image:
    yaw = math.radians(yaw_deg)
    cos_y, sin_y = math.cos(yaw), math.sin(yaw)
    size = CANVAS * SS
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, base = size / 2, size * BASE_Y
    norm = math.sqrt(sum(v * v for v in LIGHT))
    light = tuple(v / norm for v in LIGHT)

    def turn(x: float, y: float, z: float) -> tuple[float, float, float]:
        return x * cos_y - y * sin_y, x * sin_y + y * cos_y, z

    def screen(x: float, y: float, z: float) -> tuple[float, float]:
        return cx + x * SC * SS, base + (y * math.sin(PITCH) - z * math.cos(PITCH)) * SC * SS

    def toward(v: tuple[float, float, float]) -> float:
        return v[0] * TOWARD[0] + v[1] * TOWARD[1] + v[2] * TOWARD[2]

    placed = []
    for part, x0, x1, y0, y1, z0, z1, colour in boxes:
        forward, up = motion(part, anim, frame)
        y0, y1, z0, z1 = y0 + forward, y1 + forward, z0 + up, z1 + up
        placed.append((toward(turn((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)), (x0, x1, y0, y1, z0, z1), colour))
    for _, (x0, x1, y0, y1, z0, z1), colour in sorted(placed, key=lambda t: t[0]):   # far boxes first
        quads = [
            ((0, 0, 1), [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]),
            ((0, 1, 0), [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)]),
            ((0, -1, 0), [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]),
            ((1, 0, 0), [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]),
            ((-1, 0, 0), [(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)]),
        ]
        for normal, corners in quads:
            n = turn(*normal)
            if toward(n) <= 1e-6:
                continue   # a face turned away from the camera
            lit = 0.52 + 0.62 * max(0.0, n[0] * light[0] + n[1] * light[1] + n[2] * light[2])
            draw.polygon([screen(*turn(*c)) for c in corners], fill=tone(colour, lit) + (255,))
    small = img.resize((CANVAS, CANVAS), Image.NEAREST)
    alpha = small.getchannel("A").point(lambda v: 255 if v > 127 else 0)
    out = Image.new("RGBA", small.size, (0, 0, 0, 0))
    out.paste(Image.new("RGBA", small.size, OUTLINE), (0, 0), alpha.filter(ImageFilter.MaxFilter(3)))   # a one pixel outline
    out.paste(small, (0, 0), alpha)
    return out


CREW = {
    "clyde": person("#d9a273", "#241a14", "#3a3d46", "#f2ece0", "#34363f", "#17141a", "fedora", "#2b2d35", "suit"),
    "bonnie": person("#f0c8a0", "#a3302b", "#27345a", "#27345a", "#c9a07a", "#1b1620", "cloche", "#27345a", "dress", 0.92),
    "master": person("#e0b48a", "#c9c6c0", "#1f2a4a", "#f2ece0", "#1c2238", "#15131a", "captain", "#1f2a4a", "coat", 1.08),
    "advisor": person("#c68a5c", "#bdbab4", "#7a5a3a", "#f2ece0", "#4a3f36", "#2a1f18", "bowler", "#3a3028", "tweed"),
    "newsboy": person("#f0c8a0", "#6b4a2e", "#e6dcc4", "#e6dcc4", "#8a7658", "#3a2a1e", "flatcap", "#7a6a50", "braces", 0.95),
    "mechanic": person("#8d5a3b", "#1a1512", "#2b4a78", "#2b4a78", "#2b4a78", "#2a2420", "flatcap", "#2c3340", "overalls"),
    "clerk": person("#e2b58a", "#3a2a1e", "#efe9dc", "#efe9dc", "#1f1d22", "#16131a", "", "", "clerk"),
}


def main(target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for name, boxes in CREW.items():
        for direction, yaw in DIRS.items():
            for anim in ("idle", "walk"):
                for frame in range(FRAMES):
                    render(boxes, yaw, anim, frame).save(target / f"{name}-{anim}-{direction}-{frame:02d}.png", optimize=True)
                    count += 1
    print(f"{count} frames written to {target}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(Path(sys.argv[1])))
