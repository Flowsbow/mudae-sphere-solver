"""Time the exact $oq search against how many purple placements still fit.

Plays random boards to a given number of paid clicks left, either by the bot's
early-game rule or by random clicks, then times one exact search from a cold
cache. The results set EXACT_MAX_PLACEMENTS in src/solver/oq_ev.py.

    python -m sim.time_oq_search --policy random --left 3 --boards 10
"""

import argparse
import time

import numpy as np

from src.solver.modes.oc import SYMMETRIES
from src.solver.modes.oq import (
    BASE_PAYOUT,
    CLICKS,
    LAYOUTS,
    PURPLE,
    PURPLES_FOR_RED,
    RED,
    RED_SHOWN,
)
from src.solver.oq_ev import HIDDEN, OqSolver, clicks_used


def reveal(codes: tuple[int, ...], cell: int, layout: np.ndarray) -> tuple[int, ...]:
    new = list(codes)
    if new[cell] == RED_SHOWN:
        new[cell] = RED
    elif layout[cell] == PURPLE:
        new[cell] = PURPLE
        if new.count(PURPLE) == PURPLES_FOR_RED:
            last = next(
                c for c in range(25) if layout[c] == PURPLE and new[c] == HIDDEN
            )
            new[last] = RED_SHOWN
    else:
        new[cell] = int(layout[cell])
    return tuple(new)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", choices=["rule", "random"], default="random")
    parser.add_argument("--left", type=int, default=3, help="paid clicks left")
    parser.add_argument("--boards", type=int, default=10)
    parser.add_argument("--seed", type=int, default=2)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    rule = OqSolver(LAYOUTS, BASE_PAYOUT, symmetries=SYMMETRIES)
    for _ in range(args.boards):
        layout = LAYOUTS[rng.integers(len(LAYOUTS))]
        codes = (HIDDEN,) * 25
        while CLICKS - clicks_used(codes) > args.left:
            if RED_SHOWN in codes:
                cell = codes.index(RED_SHOWN)
            elif args.policy == "rule":
                cell = rule.early_pick(codes, rule.consistent(codes))
            else:
                hidden = [c for c in range(25) if codes[c] == HIDDEN]
                cell = int(rng.choice(hidden))
            codes = reveal(codes, cell, layout)
        fits = len(rule.consistent(codes))
        solver = OqSolver(
            LAYOUTS, BASE_PAYOUT, symmetries=SYMMETRIES, max_placements=None
        )
        start = time.time()
        solver.analyze(codes)
        print(
            f"{args.policy} play, {args.left} left: {fits:5d} placements fit, "
            f"{time.time() - start:6.2f} s, {len(solver._memo):,} positions"
        )


if __name__ == "__main__":
    main()
