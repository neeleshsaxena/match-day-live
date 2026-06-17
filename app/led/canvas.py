from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

WIDTH = 64
HEIGHT = 64

BLACK = (0, 0, 0)
WHITE = (240, 240, 240)
GRAY = (96, 96, 96)
DIM = (48, 48, 48)
RED = (255, 64, 32)
GREEN = (32, 224, 96)
YELLOW = (255, 200, 32)
ORANGE = (255, 140, 32)
BLUE = (96, 128, 255)
ACCENT = ORANGE

_font_cache: dict[str, ImageFont.ImageFont] = {}


def font_small() -> ImageFont.ImageFont:
    if "small" not in _font_cache:
        _font_cache["small"] = ImageFont.load_default()
    return _font_cache["small"]


def new_canvas(bg: tuple[int, int, int] = BLACK) -> Image.Image:
    return Image.new("RGB", (WIDTH, HEIGHT), bg)


def text_width(draw: ImageDraw.ImageDraw, text: str, font=None) -> int:
    bbox = draw.textbbox((0, 0), text, font=font or font_small())
    return bbox[2] - bbox[0]


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    fill: tuple[int, int, int] = WHITE,
    font=None,
) -> None:
    draw.text(xy, text, fill=fill, font=font or font_small())


def draw_centered(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    fill: tuple[int, int, int] = WHITE,
    font=None,
) -> None:
    f = font or font_small()
    w = text_width(draw, text, f)
    draw.text(((WIDTH - w) // 2, y), text, fill=fill, font=f)


def draw_hline(
    draw: ImageDraw.ImageDraw,
    y: int,
    fill: tuple[int, int, int] = DIM,
    x0: int = 0,
    x1: int = WIDTH,
) -> None:
    draw.line([(x0, y), (x1 - 1, y)], fill=fill)


def filled_rect(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    fill: tuple[int, int, int],
) -> None:
    draw.rectangle([x0, y0, x1, y1], fill=fill)


# ─── color helpers ───────────────────────────────────────────────────────────


def scale_color(c: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    """Multiply each channel by `factor`, clamped to 0-255."""
    return (
        max(0, min(255, int(c[0] * factor))),
        max(0, min(255, int(c[1] * factor))),
        max(0, min(255, int(c[2] * factor))),
    )


def lerp_color(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """Linearly interpolate between c1 and c2; t in [0, 1]."""
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def pulse_color(
    base: tuple[int, int, int],
    tick: float,
    period: float = 1.2,
    min_factor: float = 0.45,
    max_factor: float = 1.0,
) -> tuple[int, int, int]:
    """Modulate `base` brightness over time. tick = monotonic seconds."""
    import math
    phase = (math.sin(tick / period * math.tau) + 1) / 2  # 0..1
    factor = min_factor + (max_factor - min_factor) * phase
    return scale_color(base, factor)


# ─── 5x7 pixel digits for "big score" rendering ──────────────────────────────
# Width 5, height 7. '#' = on, '.' = off.

_GLYPHS_5x7 = {
    # Digits
    "0": [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
    "1": ["..#..", ".##..", "#.#..", "..#..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
    "3": [".###.", "#...#", "....#", "..##.", "....#", "#...#", ".###."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    "5": ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
    "6": [".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."],
    # Uppercase letters
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "B": ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    "C": [".####", "#....", "#....", "#....", "#....", "#....", ".####"],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "F": ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
    "G": [".###.", "#...#", "#....", "#..##", "#...#", "#...#", ".###."],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "I": [".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "J": ["..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."],
    "K": ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "M": ["#...#", "##.##", "#.#.#", "#...#", "#...#", "#...#", "#...#"],
    "N": ["#...#", "##..#", "#.#.#", "#.#.#", "#..##", "#...#", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "Q": [".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "V": ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "W": ["#...#", "#...#", "#...#", "#...#", "#.#.#", "##.##", "#...#"],
    "X": ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
    "Y": ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    "Z": ["#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"],
    # Punctuation / symbols
    "-": [".....", ".....", ".....", ".###.", ".....", ".....", "....."],
    ":": [".....", ".....", "..#..", ".....", "..#..", ".....", "....."],
    ".": [".....", ".....", ".....", ".....", ".....", ".....", ".##.."],
    " ": [".....", ".....", ".....", ".....", ".....", ".....", "....."],
    "'": [".#...", ".#...", "#....", ".....", ".....", ".....", "....."],
    "+": [".....", ".....", "..#..", ".###.", "..#..", ".....", "....."],
}

GLYPH_W = 5
GLYPH_H = 7


def big_text_width(text: str, scale: int = 1, spacing: int = 1) -> int:
    if not text:
        return 0
    return len(text) * (GLYPH_W * scale + spacing) - spacing


def draw_big(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    fill: tuple[int, int, int] = WHITE,
    scale: int = 2,
    spacing: int = 1,
) -> None:
    """Render `text` using 5x7 pixel glyphs scaled up by `scale`."""
    x0, y0 = xy
    for ch in text:
        glyph = _GLYPHS_5x7.get(ch) or _GLYPHS_5x7[" "]
        for ry, row in enumerate(glyph):
            for cx, pixel in enumerate(row):
                if pixel == "#":
                    px = x0 + cx * scale
                    py = y0 + ry * scale
                    if scale == 1:
                        draw.point((px, py), fill=fill)
                    else:
                        draw.rectangle([px, py, px + scale - 1, py + scale - 1], fill=fill)
        x0 += GLYPH_W * scale + spacing


def draw_big_centered(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    fill: tuple[int, int, int] = WHITE,
    scale: int = 2,
    spacing: int = 1,
) -> None:
    w = big_text_width(text, scale, spacing)
    x = (WIDTH - w) // 2
    draw_big(draw, (x, y), text, fill=fill, scale=scale, spacing=spacing)
