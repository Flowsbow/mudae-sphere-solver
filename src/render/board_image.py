import io
import math
import random
from collections.abc import Mapping

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.solver.board import (
    COL_NAMES,
    N_CELLS,
    ROW_NAMES,
    SIZE,
    BoardState,
    Color,
    cell_name,
)
from src.solver.ev import Analysis

# Look chosen by Flow from rendered mockups, 2026-09-28 ("design B").
SCALE = 2
TILE, GAP, PAD, LABEL, FOOTER = 64, 6, 16, 22, 48
BACKGROUND = (30, 31, 34)
TILE_COLOR = (43, 45, 49)
TEXT = (220, 221, 222)
DIM = (140, 142, 150)
HEAT = (250, 204, 21)
BEST_OUTLINE = (255, 255, 255)
GEM = {
    Color.BLUE: (70, 110, 240),
    Color.TEAL: (30, 190, 195),
    Color.GREEN: (50, 200, 70),
    Color.YELLOW: (240, 210, 40),
    Color.ORANGE: (250, 130, 30),
    Color.RED: (225, 25, 35),
}
GOLD_LIGHT, GOLD_MID, GOLD_DARK = (255, 222, 120), (214, 158, 48), (120, 74, 18)


def click_values(
    analysis: Analysis, payouts: Mapping[Color, float]
) -> dict[int, float]:
    return {
        cell: sum(p * payouts[color] for color, p in probs.items())
        for cell, probs in analysis.color_probs.items()
    }


def render(
    state: BoardState, analysis: Analysis, payouts: Mapping[Color, float]
) -> bytes:
    width = PAD * 2 + LABEL + SIZE * TILE + (SIZE - 1) * GAP
    height = width + FOOTER
    img = Image.new("RGB", (width * SCALE, height * SCALE), BACKGROUND)
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

    footer_y = _px(height - FOOTER + 16)
    if analysis.best is None:
        line = "No clicks left"
    else:
        line = (
            f"Click {cell_name(analysis.best)}  ·  {analysis.value:.1f} expected over "
            f"{analysis.clicks_left} click{'s' if analysis.clicks_left != 1 else ''}"
        )
    draw.text((_px(PAD), footer_y), line, fill=TEXT, font=_font(15))

    img = img.resize((width, height), Image.LANCZOS)
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
    ring = Image.new("RGB", img.size)
    px = ring.load()
    for y in range(max(0, cy - r), min(h, cy + r + 1)):
        for x in range(max(0, cx - r), min(w, cx + r + 1)):
            t = ((x - cx) + (y - cy)) / (2 * r) + 0.5
            if t > 0.45:
                px[x, y] = _mix(GOLD_LIGHT, GOLD_DARK, t)
            else:
                px[x, y] = _mix(GOLD_LIGHT, GOLD_MID, 1 - t / 0.45)
    img.paste(ring, mask=_disc(img.size, cx, cy, r))
    draw = ImageDraw.Draw(img)
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r], outline=(60, 36, 8), width=max(1, r // 12)
    )
    inner = int(r * 0.74)
    lip = inner + max(1, r // 14)
    draw.ellipse([cx - lip, cy - lip, cx + lip, cy + lip], fill=(70, 40, 10))

    core = _mix(color, (255, 255, 255), 0.22)
    edge = tuple(int(c * 0.22) for c in color)
    body = Image.new("RGB", img.size)
    bp = body.load()
    gx, gy, gr = cx - inner // 6, cy - inner // 6, int(inner * 1.15)
    for y in range(max(0, cy - inner), min(h, cy + inner + 1)):
        for x in range(max(0, cx - inner), min(w, cx + inner + 1)):
            bp[x, y] = _mix(core, edge, (math.hypot(x - gx, y - gy) / gr) ** 0.9)

    rng = random.Random(seed)
    sparkle = Image.new("L", img.size, 0)
    sd = ImageDraw.Draw(sparkle)
    for _ in range(int(inner * 1.2)):
        angle = rng.uniform(0, 2 * math.pi)
        dist = inner * rng.random() ** 0.6
        sx, sy = cx + dist * math.cos(angle), cy + dist * math.sin(angle)
        s = rng.uniform(0.5, 1.6) * r / 18
        sd.ellipse([sx - s, sy - s, sx + s, sy + s], fill=rng.randint(25, 70))
    body.paste(
        _mix(color, (255, 255, 255), 0.35),
        mask=sparkle.filter(ImageFilter.GaussianBlur(r / 30)),
    )
    img.paste(body, mask=_disc(img.size, cx, cy, inner))

    shine = Image.new("L", img.size, 0)
    hr = int(inner * 0.30)
    hx, hy = cx - int(inner * 0.38), cy - int(inner * 0.40)
    ImageDraw.Draw(shine).ellipse(
        [hx - hr, hy - int(hr * 0.65), hx + hr, hy + int(hr * 0.65)], fill=170
    )
    img.paste((255, 255, 255), mask=shine.filter(ImageFilter.GaussianBlur(r * 0.07)))
