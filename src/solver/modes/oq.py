from itertools import combinations

import numpy as np

from src.solver.board import N_CELLS, SIZE

# Rule sources: Mudae's $oq rules text and a finished game, both in Flow's
# 2026-09-30 screenshot, plus Flow's description the same day.
CLICKS = 7  # rules text: "You can click 7 times"
N_PURPLE = 4  # rules text: "Find 3 purple spheres (out of 4)"
PURPLES_FOR_RED = 3  # rules text: 3 found turns "the 4th purple into a red sphere"
# Rules text: "(8 tiles around)"; all 21 non-purple cells of the screenshot's
# finished board match this count, with the red counted as a purple.
# Purple clicks cost nothing: "(Free)" on every purple in the screenshot's log.
# The red costs a click: the log has 10 clicks, 3 of them free purples.

# Cell codes. 0-4 are the purple counts and equal Color.BLUE..Color.ORANGE.
RED = 5  # the 4th purple, once collected
PURPLE = 6
RED_SHOWN = 7  # the 4th purple after 3 are found: visible, not yet clicked


def neighbors(i: int) -> list[int]:
    r, c = divmod(i, SIZE)
    return [
        rr * SIZE + cc
        for rr in range(r - 1, r + 2)
        for cc in range(c - 1, c + 2)
        if (rr, cc) != (r, c) and 0 <= rr < SIZE and 0 <= cc < SIZE
    ]


def _enumerate_layouts() -> np.ndarray:
    adjacency = np.zeros((N_CELLS, N_CELLS), dtype=np.int8)
    for i in range(N_CELLS):
        adjacency[i, neighbors(i)] = 1
    purples = np.array(list(combinations(range(N_CELLS), N_PURPLE)))
    is_purple = np.zeros((len(purples), N_CELLS), dtype=np.int8)
    np.put_along_axis(is_purple, purples, 1, axis=1)
    layouts = is_purple @ adjacency
    layouts[is_purple == 1] = PURPLE
    return layouts.astype(np.int8)


# Every placement of the 4 purples. Treating them as equally likely is an
# assumption (also made by colblitz's quest solver), not confirmed from the game.
LAYOUTS = _enumerate_layouts()
LAYOUTS.flags.writeable = False

# Spheres per code with no bonus. Purple 5, blue 10, teal 20, green 35: Flow's $oq
# game on the server with no bonus (reported 2026-10-03). Red 150: Flow saw 195 at
# +6 / 25%, which with_bonus (src/solver/payouts.py) gives only for base 150, and
# 150 with no bonus in data/mudae/oq_rewards_finished.txt (2026-10-05). Yellow 55:
# the same rewards message. Orange 90: Flow, 2026-10-05.
BASE_PAYOUT = {0: 10, 1: 20, 2: 35, 3: 55, 4: 90, PURPLE: 5, RED: 150}
# Sometimes the 4th purple turns rainbow instead of red (Flow, 2026-10-05). It pays
# 500 with no bonus (Flow, 2026-10-05). How often it happens isn't known, so the
# solver plans for red until a rainbow actually appears.
RAINBOW = 500
