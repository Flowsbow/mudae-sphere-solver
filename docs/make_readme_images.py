"""Draws the README's $oc and $oq images in docs/images/.

Numbers come from docs/readme_numbers.json (python -m docs.readme_numbers) and
the finished $oq game in data/mudae/oq_finished.txt.

Run from the repo root: python -m docs.make_readme_images
"""

import json
import re
from pathlib import Path

from PIL import Image, ImageDraw

from docs.make_symmetry_images import HIDDEN, TEXT, TRANSPARENT, _font
from sim.compare_oq_heuristics import PAY
from src.render.board_image import GEM
from src.solver.board import N_CELLS, Color, cell_index, cell_name
from src.solver.modes import oq
from src.solver.oq_ev import HIDDEN as UNSEEN
from src.solver.oq_ev import OqSolver

HERE = Path(__file__).parent
OUT = HERE / "images"
NUMBERS = json.loads((HERE / "readme_numbers.json").read_text())
GAME = HERE.parent / "data" / "mudae" / "oq_finished.txt"
TILE, GAP, MARGIN = 58, 4, 40
GRID = 5 * TILE + 4 * GAP
TOP = 110
# Display colors, chosen 2026-10-04: Mudae's purple sphere, and a darker green
# that keeps white text readable.
PURPLE = (150, 85, 200)
DEEP_GREEN = (40, 140, 55)
COUNT_COLOR = [GEM[Color(k)] for k in range(5)]
EMOJI_CODE = {"spB": 0, "spT": 1, "spG": 2, "spY": 3, "spO": 4, "spP": oq.PURPLE}
# Three of the cells clicked in that game, shown as a mid-game position.
MIDGAME = ("C3", "B4", "A1")


def mix(a, b, t: float) -> tuple[int, ...]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))


def canvas(width: int, height: int, title: str, note: str):
    img = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(img)
    draw.text((20, 18), title, font=_font(24, bold=True), fill=TEXT)
    draw.text((20, 54), note, font=_font(19, bold=True), fill=TEXT)
    return img, draw


def grid(draw, x, y, fills, texts, outlined=(), size=17) -> None:
    for label, (dx, dy) in [(c, (i, -1)) for i, c in enumerate("12345")] + [
        (r, (-1, i)) for i, r in enumerate("ABCDE")
    ]:
        cx = x + dx * (TILE + GAP) + TILE / 2 + (8 if dx < 0 else 0)
        cy = y + dy * (TILE + GAP) + TILE / 2 + (12 if dy < 0 else 0)
        draw.text((cx, cy), label, font=_font(15, bold=True), fill=TEXT, anchor="mm")
    for i in range(N_CELLS):
        r, c = divmod(i, 5)
        x0, y0 = x + c * (TILE + GAP), y + r * (TILE + GAP)
        draw.rounded_rectangle([x0, y0, x0 + TILE, y0 + TILE], 7, fill=fills[i])
        center = (x0 + TILE / 2, y0 + TILE / 2)
        draw.text(center, texts[i], font=_font(size, True), fill="white", anchor="mm")
        if i in outlined:
            box = [x0 - 2, y0 - 2, x0 + TILE + 2, y0 + TILE + 2]
            draw.rounded_rectangle(box, 8, outline=TEXT, width=3)


def caption(draw, x, y, text) -> None:
    draw.multiline_text(
        (x + GRID / 2, y + GRID + 14),
        text,
        font=_font(19, bold=True),
        fill=TEXT,
        anchor="ma",
        align="center",
    )


def oc_red_cells() -> Image.Image:
    counts = NUMBERS["oc"]["boards_per_red_cell"]
    total = sum(counts)
    by_cell = [1 / 24 if n else 0.0 for n in counts]
    by_board = [n / total for n in counts]
    top = max(by_board)
    panels = [
        (
            "legal boards with\nred in this cell",
            [f"{n:,}" for n in counts],
            [n / max(counts) for n in counts],
        ),
        (
            "chance red is here:\nthe solver's model",
            [f"{p:.1%}" for p in by_cell],
            [p / top for p in by_cell],
        ),
        (
            "chance red is here if every\nboard were equally likely",
            [f"{p:.1%}" for p in by_board],
            [p / top for p in by_board],
        ),
    ]
    width = 3 * (GRID + MARGIN + 20) + MARGIN
    img, draw = canvas(
        width,
        TOP + GRID + 120,
        "Where red can be in $oc",
        f"{total:,} legal boards. The model decides how likely each one is.",
    )
    for j, (label, texts, shade) in enumerate(panels):
        x = MARGIN + 20 + j * (GRID + MARGIN + 20)
        fills = [
            mix(HIDDEN, GEM[Color.RED], 0.15 + 0.85 * t) if t else HIDDEN for t in shade
        ]
        grid(draw, x, TOP, fills, texts, size=15)
        caption(draw, x, TOP, label)
    return img


def oc_first_click() -> Image.Image:
    model = NUMBERS["oc"]["UNIFORM_CELL"]
    values = model["first_click_value"]
    low, high = min(values), max(values)
    best = [i for i, v in enumerate(values) if v > high - 1e-6]
    fills = [
        mix(HIDDEN, DEEP_GREEN, 0.1 + 0.9 * (v - low) / (high - low)) for v in values
    ]
    img, draw = canvas(
        GRID + 2 * MARGIN + 380,
        TOP + GRID + 90,
        "Expected spheres for each first click",
        "Then perfect play. Base values, solver's model.",
    )
    x = MARGIN + 20
    grid(draw, x, TOP, fills, [f"{v:.1f}" for v in values], outlined=best, size=15)
    names = ", ".join(cell_name(i) for i in best)
    caption(draw, x, TOP, f"outlined = best ({names})")
    side = x + GRID + 40
    font = _font(19, True)
    for row, (name, value) in enumerate(
        (("best", high), ("center", values[12]), ("corners", values[0]))
    ):
        y = TOP + 10 + row * 30
        draw.text((side, y), name, font=font, fill=TEXT)
        draw.text((side + 190, y), f"{value:.2f}", font=font, fill=TEXT, anchor="ra")
    draw.multiline_text(
        (side, TOP + 120),
        f"Worst to best first click\ncosts {high - low:.1f} spheres a game.",
        font=font,
        fill=TEXT,
        spacing=10,
    )
    return img


def read_game() -> tuple[list[int], set[int]]:
    codes, clicked = [UNSEEN] * N_CELLS, set()
    pattern = re.compile(r"^(\d)\.(\d) .*style=(\w+) \| emoji=(\w+):")
    for line in GAME.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line)
        if m:
            cell = int(m[1]) * 5 + int(m[2])
            codes[cell] = EMOJI_CODE[m[4]]
            if m[3] == "primary":
                clicked.add(cell)
    return codes, clicked


def oq_fill(code: int) -> tuple[int, ...]:
    return PURPLE if code == oq.PURPLE else COUNT_COLOR[code]


def oq_board() -> Image.Image:
    codes, clicked = read_game()
    finished_texts = ["P" if x == oq.PURPLE else str(x) for x in codes]

    shown = [UNSEEN] * N_CELLS
    for name in MIDGAME:
        shown[cell_index(name)] = codes[cell_index(name)]
    analysis = OqSolver(oq.LAYOUTS, PAY).analyze(tuple(shown))
    top = max(analysis.purple_prob.values())
    fills, texts = [], []
    for i, x in enumerate(shown):
        if x == UNSEEN:
            p = analysis.purple_prob[i]
            fills.append(mix(HIDDEN, PURPLE, 0.85 * p / top))
            texts.append(f"{p:.1%}".replace(".0%", "%"))
        else:
            fills.append(oq_fill(x))
            texts.append(str(x))

    img, draw = canvas(
        2 * (GRID + MARGIN + 20) + MARGIN,
        TOP + GRID + 140,
        "$oq: each color counts the purples around it",
        "Blue 0, teal 1, green 2, yellow 3, orange 4 of the 8 tiles around.",
    )
    x1, x2 = MARGIN + 20, MARGIN + 20 + GRID + MARGIN + 20
    grid(draw, x1, TOP, [oq_fill(x) for x in codes], finished_texts, clicked)
    caption(draw, x1, TOP, "a real finished game\n(outlined = clicked)")
    grid(draw, x2, TOP, fills, texts, {analysis.best}, size=15)
    caption(
        draw,
        x2,
        TOP,
        f"after {', '.join(MIDGAME)}: chance\neach tile is purple\n"
        "(outlined = solver's pick)",
    )
    return img


def oq_first_click() -> Image.Image:
    first = NUMBERS["oq"]["first_click"]
    rows = [
        ("corner", "corner (3 around)"),
        ("edge", "edge (5 around)"),
        ("inner", "inner (8 around)"),
    ]
    label_w, bar_w, bar_h = 210, 640, 46
    colors = COUNT_COLOR + [PURPLE]
    img, draw = canvas(
        label_w + bar_w + 2 * MARGIN,
        TOP + 3 * (bar_h + 18) + 90,
        "What your first $oq click shows",
        "Chance of each color, by where you click. Purple is 16% anywhere.",
    )
    for j, (key, label) in enumerate(rows):
        y = TOP + j * (bar_h + 18)
        draw.text(
            (MARGIN, y + bar_h / 2), label, font=_font(19, True), fill=TEXT, anchor="lm"
        )
        x = MARGIN + label_w
        for color, p in zip(colors, first[key]["probs"], strict=True):
            w = bar_w * p
            if w >= 1:
                draw.rectangle([x, y, x + w, y + bar_h], fill=color)
            if w >= 44:
                draw.text(
                    (x + w / 2, y + bar_h / 2),
                    f"{p:.0%}",
                    font=_font(17, True),
                    fill="white",
                    anchor="mm",
                )
            x += w
    y = TOP + 3 * (bar_h + 18) + 12
    x = MARGIN + label_w
    for color, name in zip(colors, ["0", "1", "2", "3", "4", "purple"], strict=True):
        draw.rounded_rectangle([x, y, x + 22, y + 22], 4, fill=color)
        draw.text((x + 30, y + 11), name, font=_font(17, True), fill=TEXT, anchor="lm")
        x += 70 if name != "purple" else 0
    return img


def oq_strategy() -> Image.Image:
    box, gap = 64, 10
    img, draw = canvas(
        7 * (box + gap) + 2 * MARGIN + 40,
        TOP + box + 150,
        "How the $oq solver picks a click",
        "Purple clicks are free, so only paid clicks count down.",
    )
    x0 = MARGIN + 20
    for k in range(7):
        left = 7 - k
        exact = left <= 3
        x = x0 + k * (box + gap) + (24 if exact else 0)
        fill = DEEP_GREEN if exact else HIDDEN
        draw.rounded_rectangle([x, TOP, x + box, TOP + box], 8, fill=fill)
        draw.text(
            (x + box / 2, TOP + box / 2),
            str(left),
            font=_font(22, True),
            fill="white",
            anchor="mm",
        )
    draw.text((x0, TOP - 26), "paid clicks left", font=_font(17, True), fill=TEXT)
    early_mid = x0 + 2 * (box + gap) - gap / 2
    exact_mid = x0 + 24 + 5 * (box + gap) + box / 2
    for mid, text in (
        (early_mid, "early rule:\nclick the tile most\nlikely to be purple"),
        (exact_mid, "exact search over\nevery placement\nthat still fits"),
    ):
        draw.multiline_text(
            (mid, TOP + box + 16),
            text,
            font=_font(18, True),
            fill=TEXT,
            anchor="ma",
            align="center",
        )
    return img


def main() -> None:
    OUT.mkdir(exist_ok=True)
    oc_red_cells().save(OUT / "oc_red_cells.png")
    oc_first_click().save(OUT / "oc_first_click.png")
    oq_board().save(OUT / "oq_board.png")
    oq_first_click().save(OUT / "oq_first_click.png")
    oq_strategy().save(OUT / "oq_strategy.png")


if __name__ == "__main__":
    main()
