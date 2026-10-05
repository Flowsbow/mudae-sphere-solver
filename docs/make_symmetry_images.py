"""Draws the two README images in docs/images/ from the real solver.

Run from the repo root: python -m docs.make_symmetry_images
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.render.board_image import GEM
from src.solver.board import COLOR_LETTERS, SIZE, BoardState, Color
from src.solver.ev import Solver
from src.solver.modes.oc import BASE_PAYOUT, CLICKS, LAYOUTS, SYMMETRIES, prior

OUT = Path(__file__).parent / "images"
LETTER = {color: letter for letter, color in COLOR_LETTERS.items()}
TRANSPARENT = (0, 0, 0, 0)
# Chosen 2026-10-03: the gray with equal contrast (4.35:1) on GitHub's light page
# (#ffffff) and dark page (#0d1117), so the images read in either theme.
TEXT = (121, 121, 121)
HIDDEN = (70, 72, 80)
TILE, GAP, MARGIN = 34, 3, 40
BOARD = SIZE * TILE + (SIZE - 1) * GAP
NAMES = [
    "original",
    "turned 90°",
    "turned 180°",
    "turned 270°",
    "mirrored",
    "turned 90°,\nthen mirrored",
    "turned 180°,\nthen mirrored",
    "turned 270°,\nthen mirrored",
]
TOP = 92
# 4 clicks, one of them (D3) on the middle cross; the two oranges pin red to D4.
FOUR_CLICKS = "A1Y D3O D5O E2B"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = ["DejaVuSans-Bold.ttf", "arialbd.ttf"] if bold else []
    names += ["DejaVuSans.ttf", "arial.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def _star(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float) -> None:
    points = []
    for k in range(10):
        radius = r if k % 2 == 0 else r * 0.45
        angle = math.pi / 2 + k * math.pi / 5
        points.append((cx + radius * math.cos(angle), cy - radius * math.sin(angle)))
    draw.polygon(points, fill="white")


def _board(draw, x, y, cells, star=None) -> None:
    letter = _font(18, bold=True)
    for i, color in enumerate(cells):
        r, c = divmod(i, SIZE)
        x0, y0 = x + c * (TILE + GAP), y + r * (TILE + GAP)
        fill = HIDDEN if color is None else GEM[Color(color)]
        draw.rounded_rectangle([x0, y0, x0 + TILE, y0 + TILE], 6, fill=fill)
        if color is not None:
            draw.text(
                (x0 + TILE / 2, y0 + TILE / 2),
                LETTER[Color(color)],
                font=letter,
                fill="white",
                anchor="mm",
            )
        if i == star:
            box = [x0 - 2, y0 - 2, x0 + TILE + 2, y0 + TILE + 2]
            draw.rounded_rectangle(box, 7, outline=TEXT, width=3)
            _star(draw, x0 + TILE / 2, y0 + TILE / 2, TILE * 0.3)


def _canvas(title: str, rows: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    width = 4 * (BOARD + MARGIN) + MARGIN
    img = Image.new("RGBA", (width, rows * (BOARD + 70) + TOP + 20), TRANSPARENT)
    draw = ImageDraw.Draw(img)
    draw.text((20, 18), title, font=_font(24, bold=True), fill=TEXT)
    note = "All turns are counterclockwise."
    draw.text((20, 54), note, font=_font(19, bold=True), fill=TEXT)
    return img, draw


def _place(draw, j: int, label: str) -> tuple[int, int]:
    x = MARGIN + (j % 4) * (BOARD + MARGIN)
    y = TOP + (j // 4) * (BOARD + 70)
    draw.multiline_text(
        (x + BOARD / 2, y + BOARD + 12),
        label,
        font=_font(19, bold=True),
        fill=TEXT,
        anchor="ma",
        align="center",
    )
    return x, y


def rules_image() -> Image.Image:
    layout = next(lay for lay in LAYOUTS if lay[6] == 5)  # red at B2
    img, draw = _canvas(
        "Spin or mirror a real board, and it still follows every rule", 1
    )
    for j, k in enumerate([0, 1, 4, 5]):
        x, y = _place(draw, j, NAMES[k])
        _board(draw, x, y, [int(layout[src]) for src in SYMMETRIES[k]])
    return img


def same_puzzle_image() -> Image.Image:
    state = BoardState.parse(FOUR_CLICKS)
    best = Solver(LAYOUTS, prior(), BASE_PAYOUT, CLICKS).analyze(state).best
    img, draw = _canvas("Same puzzle, 8 ways   (outlined = the solver's pick)", 2)
    for j, perm in enumerate(SYMMETRIES):
        x, y = _place(draw, j, NAMES[j])
        _board(draw, x, y, [state.revealed[src] for src in perm], perm.index(best))
    return img


def main() -> None:
    OUT.mkdir(exist_ok=True)
    rules_image().save(OUT / "symmetry_rules.png")
    same_puzzle_image().save(OUT / "symmetry_same_puzzle.png")


if __name__ == "__main__":
    main()
