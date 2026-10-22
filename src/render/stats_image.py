"""The /global-stats and /my-stats image: a scoreboard across the top, then where
the $oc red was and which spheres were clicked. Layout chosen by Flow from
mockups, 2026-10-15 (the scoreboard of "design 4" over "design 3")."""

import io

from PIL import Image, ImageDraw

from src.bot.totals import Running, Totals
from src.render.board_image import (
    BACKGROUND,
    DIM,
    GEM,
    GOLD_MID,
    OH_COLOR,
    PURPLE_GEM,
    RAINBOW,
    TEXT,
    TILE_COLOR,
    _font,
    _mix,
)
from src.solver.board import COL_NAMES, ROW_NAMES, SIZE, Color
from src.solver.modes.oc import CENTER as CENTER_CELL

SCALE = 2
WIDTH = 640
# Within 2 standard errors of the prediction: green; further: amber. Chosen
# 2026-10-15 (about a 95% band).
AGREES, DISAGREES = (120, 220, 130), (250, 180, 60)
LABEL_COLOR = {
    **{color.name: GEM[color] for color in Color},
    "PURPLE": PURPLE_GEM,
    "DARK": OH_COLOR["D"],
    "LIGHT": OH_COLOR["L"],
    "PRIZE": GOLD_MID,
}
LABEL_NAME = {"PRIZE": "$oc game"}
COLUMNS = (16, 96, 190, 340, 500)
HEADS = (
    "",
    "Games",
    "Score vs\npredicted",
    "Red found /\nhindsight share",
    "Picks\nfollowed",
)


def _signed(running: Running, fmt: str = "+.1f") -> tuple[str, tuple[int, int, int]]:
    if running.n == 0:
        return "-", DIM
    error = running.standard_error
    if error is None:
        return f"{running.mean:{fmt}}", TEXT
    color = AGREES if abs(running.mean) <= 2 * error else DISAGREES
    return f"{running.mean:{fmt}} ± {error:{fmt.lstrip('+')}}", color


def _share(running: Running) -> str:
    if running.n == 0:
        return "-"
    error = running.standard_error
    return f"{running.mean:.1%}" + ("" if error is None else f" ± {error:.1%}")


def _rows(totals: Totals) -> list[tuple]:
    rows = []
    oc, oq, oh = totals.oc, totals.oq, totals.oh
    if oc.games:
        luck = oc.followed_luck
        found = f"{oc.followed_red_found:,} / {luck.n:,}" if luck.n else "-"
        rows.append(("$oc", oc, _signed(luck), found))
    if oq.games:
        rows.append(("$oq", oq, _signed(oq.followed_luck), _share(oq.followed_share)))
    if oh.games:
        rows.append(("$oh", oh, ("-", DIM), "-"))
    return rows


class _Canvas:
    def __init__(self, height: int) -> None:
        self.img = Image.new("RGB", (WIDTH * SCALE, height * SCALE), BACKGROUND)
        self.draw = ImageDraw.Draw(self.img)

    def box(self, x, y, w, h, fill, radius=8) -> None:
        self.draw.rounded_rectangle(
            [x * SCALE, y * SCALE, (x + w) * SCALE, (y + h) * SCALE],
            radius=radius * SCALE,
            fill=fill,
        )

    def text(self, x, y, text, size=13, fill=TEXT, anchor="la") -> None:
        self.draw.text(
            (x * SCALE, y * SCALE), text, fill=fill, font=_font(size), anchor=anchor
        )

    def rainbow(self, x, y, w, h) -> None:
        band = h / len(RAINBOW)
        for k, color in enumerate(RAINBOW):
            self.draw.rectangle(
                [
                    x * SCALE,
                    (y + k * band) * SCALE,
                    (x + w) * SCALE,
                    (y + (k + 1) * band) * SCALE,
                ],
                fill=color,
            )

    def swatch(self, x, y, w, h, label) -> None:
        if label == "RAINBOW":
            self.rainbow(x, y, w, h)
        else:
            self.draw.rectangle(
                [x * SCALE, y * SCALE, (x + w) * SCALE, (y + h) * SCALE],
                fill=LABEL_COLOR[label],
            )

    def png(self) -> bytes:
        out = io.BytesIO()
        width, height = self.img.size
        self.img.resize((width // SCALE, height // SCALE), Image.LANCZOS).save(
            out, format="PNG"
        )
        return out.getvalue()


def _scoreboard(c: _Canvas, rows: list[tuple], y: int) -> int:
    for x, head in zip(COLUMNS, HEADS, strict=True):
        for k, line in enumerate(head.split("\n")):
            c.text(x, y + k * 14, line, 11, DIM)
    y += 36
    for name, totals, (score, score_color), found in rows:
        c.box(8, y, WIDTH - 16, 42, TILE_COLOR)
        middle = y + 21
        c.text(COLUMNS[0] + 6, middle, name, 18, anchor="lm")
        c.text(COLUMNS[1], middle, f"{totals.games:,}", 17, anchor="lm")
        c.text(COLUMNS[2], middle, score, 15, score_color, "lm")
        c.text(COLUMNS[3], middle, found, 15, DIM if found == "-" else TEXT, "lm")
        picks = f"{totals.picks_followed:,} / {totals.picks:,}" if totals.picks else "-"
        c.text(COLUMNS[4], middle, picks, 13, anchor="lm")
        y += 48
    return y


def _heatmap(c: _Canvas, red_cells: list[int], x: int, y: int) -> None:
    cell, gap = 30, 4
    c.text(x, y, "$oc: where red was", 12, DIM)
    y += 20
    top = max(red_cells) or 1
    for i in range(SIZE):
        c.text(x + 22 + i * (cell + gap) + cell / 2, y, COL_NAMES[i], 11, DIM, "mt")
        c.text(x + 8, y + 16 + i * (cell + gap) + cell / 2, ROW_NAMES[i], 11, DIM, "mm")
    for index, count in enumerate(red_cells):
        r, k = divmod(index, SIZE)
        px, py = x + 22 + k * (cell + gap), y + 16 + r * (cell + gap)
        if index == CENTER_CELL:
            c.box(px, py, cell, cell, TILE_COLOR, 6)
            c.text(px + cell / 2, py + cell / 2, "-", 12, DIM, "mm")
            continue
        fill = _mix(TILE_COLOR, GEM[Color.RED], 0.2 + 0.8 * count / top)
        c.box(px, py, cell, cell, fill, 6)
        c.text(px + cell / 2, py + cell / 2, f"{count:,}", 12, (255, 255, 255), "mm")


def _clicked(
    c: _Canvas,
    title: str,
    counts: dict[str, int],
    x: int,
    y: int,
    w: int,
    per_row: int = 3,
) -> int:
    c.text(x, y, title, 12, DIM)
    y += 20
    total = sum(counts.values())
    left = x
    for label, count in counts.items():
        if total and count:
            width = w * count / total
            c.swatch(left, y, width, 16, label)
            left += width
    if not total:
        c.box(x, y, w, 16, TILE_COLOR, 3)
    y += 26
    column = w / per_row
    for k, (label, count) in enumerate(counts.items()):
        lx, ly = x + (k % per_row) * column, y + (k // per_row) * 22
        c.swatch(lx, ly, 10, 10, label)
        name = LABEL_NAME.get(label, label.title())
        c.text(lx + 15, ly + 5, f"{name} {count:,}", 11, anchor="lm")
    return y + _legend_rows(counts, per_row) * 22 + 10


def _legend_rows(counts: dict[str, int], per_row: int) -> int:
    return -(-len(counts) // per_row)


def _clicked_height(counts: dict[str, int], per_row: int = 3) -> int:
    return 20 + 26 + _legend_rows(counts, per_row) * 22 + 10


HEATMAP_WIDTH = 214
HEATMAP_HEIGHT = 20 + 16 + 5 * 34 + 10
# $oh has 11 colors, too many for the column beside the heatmap: it gets a
# full-width row below, 6 per legend row.
OH_PER_ROW = 6


def _beside_heatmap(totals: Totals) -> list[tuple[str, dict[str, int]]]:
    return [
        (name, part.clicked)
        for name, part in (("$oc", totals.oc), ("$oq", totals.oq))
        if part.games
    ]


def _body_height(totals: Totals) -> int:
    beside = sum(_clicked_height(counts) for _, counts in _beside_heatmap(totals))
    heat = HEATMAP_HEIGHT if totals.oc.games else 0
    below = _clicked_height(totals.oh.clicked, OH_PER_ROW) if totals.oh.games else 0
    return max(beside, heat) + below


def render_stats(totals: Totals) -> bytes | None:
    """None when there are no games yet."""
    rows = _rows(totals)
    if not rows:
        return None
    height = 16 + 36 + 48 * len(rows) + 12 + _body_height(totals) + 8
    c = _Canvas(height)
    top = _scoreboard(c, rows, 16) + 12
    x = 16
    if totals.oc.games:
        _heatmap(c, totals.oc.red_cells, 10, top)
        x = 16 + HEATMAP_WIDTH
    y = top
    for name, counts in _beside_heatmap(totals):
        y = _clicked(c, f"{name}: spheres clicked", counts, x, y, WIDTH - x - 16)
    if totals.oc.games:
        y = max(y, top + HEATMAP_HEIGHT)
    if totals.oh.games:
        title = "$oh: spheres clicked"
        _clicked(c, title, totals.oh.clicked, 16, y, WIDTH - 32, OH_PER_ROW)
    return c.png()
