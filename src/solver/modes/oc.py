from enum import Enum
from itertools import combinations

import numpy as np

from src.solver.board import N_CELLS, SIZE, Color

# Rule sources: Mudae's $oc rules text (Flow's screenshot, 2026-09-26) and Flow's
# answers the same day.
CLICKS = 5  # Flow, observed
CENTER = 12  # C3; rules text: red is "never at the center"
N_ORANGE = 2  # rules text; touching red on a side, never diagonal: Flow, observed
N_YELLOW = 3  # rules text; any distance along red's diagonals: Flow, observed
N_GREEN = 4  # rules text; may touch red: D3 in the 2026-09-26 screenshot

RED_CELLS = [i for i in range(N_CELLS) if i != CENTER]

# Flow's stated base values, 2026-09-26. Multipliers apply to every color alike
# (Flow, 2026-09-27), so they never change the best move.
BASE_PAYOUT = {
    Color.BLUE: 10,
    Color.TEAL: 20,
    Color.GREEN: 35,
    Color.YELLOW: 55,
    Color.ORANGE: 90,
    Color.RED: 150,
}


def side_neighbors(i: int) -> list[int]:
    r, c = divmod(i, SIZE)
    return [
        rr * SIZE + cc
        for rr, cc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))
        if 0 <= rr < SIZE and 0 <= cc < SIZE
    ]


def row_col_cells(i: int) -> list[int]:
    r, c = divmod(i, SIZE)
    return [j for j in range(N_CELLS) if j != i and (j // SIZE == r or j % SIZE == c)]


def diagonal_cells(i: int) -> list[int]:
    r, c = divmod(i, SIZE)
    return [
        j for j in range(N_CELLS) if j != i and abs(j // SIZE - r) == abs(j % SIZE - c)
    ]


def _enumerate_layouts() -> tuple[np.ndarray, np.ndarray]:
    layouts = []
    red_of_layout = []
    for red in RED_CELLS:
        # Teal on every remaining line cell, blue off the lines: inferred from the
        # rules text, matches the 2026-09-26 screenshot exactly; not directly confirmed.
        line = row_col_cells(red) + diagonal_cells(red)
        for oranges in combinations(side_neighbors(red), N_ORANGE):
            green_options = [j for j in row_col_cells(red) if j not in oranges]
            for yellows in combinations(diagonal_cells(red), N_YELLOW):
                for greens in combinations(green_options, N_GREEN):
                    layout = [Color.BLUE] * N_CELLS
                    for j in line:
                        layout[j] = Color.TEAL
                    for j in oranges:
                        layout[j] = Color.ORANGE
                    for j in yellows:
                        layout[j] = Color.YELLOW
                    for j in greens:
                        layout[j] = Color.GREEN
                    layout[red] = Color.RED
                    layouts.append(layout)
                    red_of_layout.append(red)
    return np.array(layouts, dtype=np.int8), np.array(red_of_layout, dtype=np.int8)


LAYOUTS, LAYOUT_RED = _enumerate_layouts()
LAYOUTS.flags.writeable = False
LAYOUT_RED.flags.writeable = False


def _symmetries() -> tuple[tuple[int, ...], ...]:
    grid = np.arange(N_CELLS).reshape(SIZE, SIZE)
    turns = [np.rot90(grid, k) for k in range(4)]
    return tuple(
        tuple(int(i) for i in g.flatten())
        for g in turns + [np.fliplr(t) for t in turns]
    )


# The 4 rotations and 4 mirror images of the board. Every $oc rule (side-adjacent,
# diagonal, same row or column, not the center) is unchanged by them, so a position
# and its rotated or mirrored copy have the same value. Checked in test_oc_rules.py.
SYMMETRIES = _symmetries()


class RedModel(Enum):
    UNIFORM_CELL = "red's cell uniform over the 24 allowed; the rest uniform given red"
    UNIFORM_LAYOUT = "every legal layout equally likely"


# ASSUMPTION, not observed. No game data is collected (decided 2026-09-26), so this
# is unverified. See README, "Model assumption".
DEFAULT_RED_MODEL = RedModel.UNIFORM_CELL


def prior(model: RedModel = DEFAULT_RED_MODEL) -> np.ndarray:
    if model is RedModel.UNIFORM_LAYOUT:
        return np.full(len(LAYOUTS), 1 / len(LAYOUTS))
    layouts_per_red_cell = np.bincount(LAYOUT_RED, minlength=N_CELLS)
    return 1 / (len(RED_CELLS) * layouts_per_red_cell[LAYOUT_RED])
