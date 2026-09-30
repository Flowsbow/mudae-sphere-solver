import io
from collections.abc import Mapping

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.solver.board import (
    COL_NAMES,
    N_CELLS,
    ROW_NAMES,
    SIZE,
    BoardState,
    Color,
)
from src.solver.ev import Analysis

# Look chosen by Flow from rendered mockups, 2026-09-28 ("design B").
SCALE = 2
TILE, GAP, PAD, LABEL = 64, 6, 16, 22
BACKGROUND = (30, 31, 34)
TILE_COLOR = (43, 45, 49)
TEXT = (220, 221, 222)
DIM = (140, 142, 150)
HEAT = (250, 204, 21)
BEST_OUTLINE = (255, 255, 255)
GEM = {
    Color.BLUE: (40, 120, 230),
    Color.TEAL: (0, 185, 195),
    Color.GREEN: (60, 190, 70),
    Color.YELLOW: (250, 200, 40),
    Color.ORANGE: (250, 140, 20),
    Color.RED: (230, 40, 45),
}
LETTER = {color: color.name[0] for color in Color}
# Darkened so white letters stay readable on yellow and teal blocks.
BLOCK_DARKEN = 0.25
GOLD_MID, GOLD_DARK = (222, 172, 58), (140, 96, 28)


def click_values(
    analysis: Analysis, payouts: Mapping[Color, float]
) -> dict[int, float]:
    return {
        cell: sum(p * payouts[color] for color, p in probs.items())
        for cell, probs in analysis.color_probs.items()
    }


def render(
    state: BoardState,
    analysis: Analysis,
    payouts: Mapping[Color, float],
    letters: bool = False,
) -> bytes:
    size = PAD * 2 + LABEL + SIZE * TILE + (SIZE - 1) * GAP
    img = Image.new("RGB", (size * SCALE, size * SCALE), BACKGROUND)
    draw = ImageDraw.Draw(img)

    for i in range(SIZE):
        middle = _px(PAD + LABEL + i * (TILE + GAP) + TILE // 2)
        edge = _px(PAD + LABEL // 2)
        draw.text((middle, edge), COL_NAMES[i], fill=DIM, font=_font(14), anchor="mm")
        draw.text((edge, middle), ROW_NAMES[i], fill=DIM, font=_font(14), anchor="mm")

    plus = click_values(analysis, payouts)
    totals = analysis.cell_value
    low, high = (min(totals.values()), max(totals.values())) if totals else (0, 0)

    for cell in range(N_CELLS):
        x0, y0, x1, y1 = _tile_box(cell)
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        color = state.revealed[cell]
        if color is not None:
            if letters:
                block = _mix(GEM[color], (0, 0, 0), BLOCK_DARKEN)
                draw.rounded_rectangle([x0, y0, x1, y1], radius=_px(8), fill=block)
                draw.text(
                    (cx, cy),
                    LETTER[color],
                    fill=(255, 255, 255),
                    font=_font(30),
                    anchor="mm",
                    stroke_width=_px(1),
                    stroke_fill=(255, 255, 255),
                )
            else:
                draw.rounded_rectangle([x0, y0, x1, y1], radius=_px(8), fill=TILE_COLOR)
                _gem(img, cx, cy, _px(20), GEM[color], seed=cell)
            continue
        heat = (
            (totals[cell] - low) / (high - low) if high > low and cell in totals else 0
        )
        fill = _mix(TILE_COLOR, HEAT, heat * 0.85)
        best = cell == analysis.best
        draw.rounded_rectangle(
            [x0, y0, x1, y1],
            radius=_px(8),
            fill=fill,
            outline=BEST_OUTLINE if best else None,
            width=_px(3),
        )
        ink = BACKGROUND if heat > 0.55 else TEXT
        draw.text((cx, cy), f"+{plus[cell]:.0f}", fill=ink, font=_font(17), anchor="mm")

    img = img.resize((size, size), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _px(v: float) -> int:
    return int(v * SCALE)


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size * SCALE)


def _tile_box(cell: int) -> tuple[int, int, int, int]:
    r, c = divmod(cell, SIZE)
    x0 = PAD + LABEL + c * (TILE + GAP)
    y0 = PAD + LABEL + r * (TILE + GAP)
    return _px(x0), _px(y0), _px(x0 + TILE), _px(y0 + TILE)


def _mix(a: tuple[int, ...], b: tuple[int, ...], t: float) -> tuple[int, ...]:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3))


def _disc(size: tuple[int, int], cx: int, cy: int, r: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return mask


def _gem(img: Image.Image, cx: int, cy: int, r: int, color: tuple[int, ...], seed: int):
    w, h = img.size
    draw = ImageDraw.Draw(img)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GOLD_DARK)
    ring = int(r * 0.93)
    draw.ellipse([cx - ring, cy - ring, cx + ring, cy + ring], fill=GOLD_MID)

    inner = int(r * 0.78)
    top = _mix(color, (255, 255, 255), 0.18)
    bottom = _mix(color, (0, 0, 0), 0.28)
    body = Image.new("RGB", img.size)
    bp = body.load()
    for y in range(max(0, cy - inner), min(h, cy + inner + 1)):
        t = (y - (cy - inner)) / (2 * inner)
        row = _mix(top, bottom, t)
        for x in range(max(0, cx - inner), min(w, cx + inner + 1)):
            bp[x, y] = row
    img.paste(body, mask=_disc(img.size, cx, cy, inner))

    shine = Image.new("L", img.size, 0)
    sw, sh = int(inner * 0.62), int(inner * 0.34)
    sy = cy - int(inner * 0.50)
    ImageDraw.Draw(shine).ellipse([cx - sw, sy - sh, cx + sw, sy + sh], fill=140)
    img.paste((255, 255, 255), mask=shine.filter(ImageFilter.GaussianBlur(r * 0.08)))
