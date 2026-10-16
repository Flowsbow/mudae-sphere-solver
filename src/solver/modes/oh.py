"""$oh (harvest) rules and numbers.

Rules come from Mudae's $oh text and Flow's dumps of one real game, 2026-10-08
(data/mudae/oh_fresh.txt, oh_midgame.txt, oh_finished.txt), plus
oh_finished_dark_prize.txt from a second game the same day.
"""

from src.solver.board import Color
from src.solver.modes.oc import BASE_PAYOUT as OC_PAYOUT
from src.solver.modes.oq import BASE_PAYOUT as OQ_PAYOUT
from src.solver.modes.oq import PURPLE as OQ_PURPLE
from src.solver.modes.oq import RAINBOW as OQ_RAINBOW

CLICKS = 5  # rules text: "You can click **5** times"
# Rules text: "Blue spheres unveil 3 buttons, teal unveil 1." The midgame dump
# matches it: 1 tile shown at the start, then 4 clicks (1 teal, 3 blues) left 15
# tiles uncovered = 1 + 4 + 1 + 3 * 3.
UNVEILS = {"T": 1, "B": 3}

# Sphere letters. W is the rainbow, D dark, L light (Flow, 2026-10-05 and
# 2026-10-08). C is the free $oc game hidden under a covered tile.
COLORS = "BTGYORWDLP"
PRIZE = "C"
PURPLE = "P"
DARK = "D"

# Spheres per color with no bonus. Plain colors pay what they pay in $oc and $oq
# (src/solver/modes/oc.py, oq.py). Purple is free in $oh too: "(Free) **+5**" in
# data/mudae/oh_rewards_midgame.txt.
_PLAIN = {
    "B": OC_PAYOUT[Color.BLUE],
    "T": OC_PAYOUT[Color.TEAL],
    "G": OC_PAYOUT[Color.GREEN],
    "Y": OC_PAYOUT[Color.YELLOW],
    "O": OC_PAYOUT[Color.ORANGE],
    "R": OC_PAYOUT[Color.RED],
    "W": OQ_RAINBOW,
    "P": OQ_PAYOUT[OQ_PURPLE],
}
# Dark turns into a random sphere when clicked and light breaks into several, so
# each is valued at its average: colblitz's $oh page, as copied by Flow on
# 2026-10-08 ("Direct EV" column). Not checked against our own data.
BASE_PAYOUT = {**_PLAIN, "D": 104, "L": 76}

# Chance that a covered tile holds each sphere: colblitz's $oh page, as copied by
# Flow on 2026-10-08 ("Rate" column). They add up to 98%; the missing 2% matches
# the $oc prize below (50% spread over 25 tiles).
RATES = {
    "W": 0.0004,
    "R": 0.0022,
    "D": 0.0146,
    "O": 0.0097,
    "L": 0.0296,
    "Y": 0.0257,
    "G": 0.0788,
    "T": 0.2348,
    "B": 0.5449,
    "P": 0.0393,
}

# Half of all boards hide one free $oc game under a covered tile, and blue and teal
# never unveil it (Flow, 2026-10-08). oh_finished_dark_prize.txt shows it at game
# end as the one tile still covered (E1).
PRIZE_CHANCE = 0.5

# Expected spheres from a fresh $oc game played the solver's way, base values:
# docs/readme_numbers.json, oc.UNIFORM_CELL.optimal_value.
OC_GAME_VALUE = 344.7285879629629
