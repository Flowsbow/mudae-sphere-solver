"""Check that one base-payout $oc solver can serve players with a sphere bonus.

A bonus pays round((base + flat) x (1 + percent/100)) per sphere. Without the
rounding that is base x a + b for every color, and every $oc click collects
exactly one sphere, so a game's total would be a x (base total) + b x clicks and
the base solver's pick would be exactly right. The rounding breaks that slightly.
This script measures by how much, for each bonus, by walking the whole game tree
the base solver's picks lead to, weighted by how likely each board is:

- how often the base pick differs from a solver built for the bonus payouts,
- the spheres per game that costs a bonus player, and
- how far the bot's shown value (Analysis.for_payouts: the next click exact, the
  rest converted with the fitted a and b) is from the true expected total of the
  base picks under the bonus payouts.

    python sim/verify_oc_bonus.py
"""

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.solver.board import N_CELLS, BoardState, Color  # noqa: E402
from src.solver.ev import TIE_TOLERANCE, Solver  # noqa: E402
from src.solver.modes.oc import (  # noqa: E402
    BASE_PAYOUT,
    CLICKS,
    LAYOUTS,
    SYMMETRIES,
    prior,
)
from src.solver.payouts import with_bonus  # noqa: E402

# Flow's (6, 25%) and the bonus that pays 199 for red (9, 25%) were seen on the
# bot, 2026-10-22; the rest spread out around them.
BONUSES = [
    (6, 25),
    (9, 25),
    (0, 10),
    (1, 0),
    (3, 15),
    (5, 0),
    (10, 50),
    (20, 25),
    (2, 100),
]


def walk(base: Solver, bonus: Solver, payouts) -> dict:
    """Expected totals over every board, following the base solver's picks."""
    weights = base.weights
    pay = np.array([payouts[Color(k)] for k in range(len(Color))], dtype=float)
    out = {"differ": 0.0, "decisions": 0.0, "loss": 0.0, "worst_shown_error": 0.0}

    def node(state: BoardState, idx: np.ndarray, reach: float) -> float:
        """Expected bonus spheres from here on, following the base picks."""
        clicks_left = CLICKS - state.n_revealed
        if clicks_left == 0:
            return 0.0
        mine = base.analyze(state)
        theirs = bonus.analyze(state)
        cell = mine.best
        out["decisions"] += reach
        if theirs.cell_value[cell] < theirs.value - TIE_TOLERANCE:
            out["differ"] += reach
        total = weights[idx].sum()
        column = LAYOUTS[idx, cell]
        value = 0.0
        for k in np.unique(column):
            sub = idx[column == k]
            p = weights[sub].sum() / total
            child = state.reveal(int(cell), Color(int(k)))
            value += p * (pay[k] + node(child, sub, reach * p))
        shown = mine.for_payouts(BASE_PAYOUT, payouts).value
        out["worst_shown_error"] = max(out["worst_shown_error"], abs(shown - value))
        return value

    start = BoardState()
    followed = node(start, np.arange(len(LAYOUTS)), 1.0)
    best = bonus.analyze(start).value
    out["loss"] = best - followed
    out["best"] = best
    out["shown_at_start"] = base.analyze(start).for_payouts(BASE_PAYOUT, payouts).value
    out["followed"] = followed
    return out


def main() -> None:
    weights = prior()
    base = Solver(LAYOUTS, weights, BASE_PAYOUT, CLICKS, SYMMETRIES)
    base.analyze(BoardState())
    print(f"{N_CELLS}-cell $oc, {len(LAYOUTS):,} boards, {CLICKS} clicks\n")
    print(
        "bonus      | picks differ | spheres lost/game | true total | shown at "
        "start | worst shown error"
    )
    for flat, percent in BONUSES:
        started = time.perf_counter()
        payouts = with_bonus(BASE_PAYOUT, flat, percent)
        bonus = Solver(LAYOUTS, weights, payouts, CLICKS, SYMMETRIES)
        r = walk(base, bonus, payouts)
        share = r["differ"] / r["decisions"]
        print(
            f"+{flat:<2} {percent:>3}%   | {share:11.3%}  | {r['loss']:17.4f} | "
            f"{r['followed']:10.2f} | {r['shown_at_start']:14.2f} | "
            f"{r['worst_shown_error']:8.3f}   ({time.perf_counter() - started:.0f}s)"
        )


if __name__ == "__main__":
    main()
