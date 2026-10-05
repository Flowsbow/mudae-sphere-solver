"""Plays full simulated $oq games with each early-game rule and compares scores.

Every rule hands over to the exact solver for the last ENDGAME paid clicks, and
every rule plays the same boards, so the differences come from the early game.

Run from the repo root: python -m sim.compare_oq_heuristics [games]

Result, 2000 games each on Flow's PC (Intel Core i9-10850K, 20 threads; 1424 s),
2026-09-30 (difference vs purple_first,
paired on the same boards, ± one standard error):
    purple_first     507.12 ± 1.42
    colblitz_mixed   -3.97 ± 1.19
    mixed_0.4        -3.60 ± 1.15
    info_first       -6.05 ± 1.20
colblitz_mixed is this file's reading of the formula on colblitz's quest page
(P + 0.1 x Gini), not colblitz's own code.
"""

import random
import sys
import time
from multiprocessing import Pool

import numpy as np

from sim.verify_oq import purple_count
from src.solver.modes.oq import CLICKS, LAYOUTS, PURPLE, RED, RED_SHOWN
from src.solver.oq_ev import HIDDEN, OqSolver

# Purple, blue, teal, green and red are the values in Flow's 2026-09-30 game log.
# They match base values with Flow's +6 / 25% sphere bonus (src/solver/payouts.py,
# checked 2026-10-03). Yellow and orange did not appear there; the 70 and 90 are
# placeholders for this comparison only.
PAY = {0: 20, 1: 33, 2: 51, 3: 70, 4: 90, PURPLE: 14, RED: 195}
ENDGAME = 3  # exact for the last 3 paid clicks, as in the bot
SEED = 7

EXACT = OqSolver(LAYOUTS, PAY)


def _probs(codes, idx):
    outcomes = np.stack([(LAYOUTS[idx] == k).mean(axis=0) for k in range(5)])
    purple = (LAYOUTS[idx] == PURPLE).mean(axis=0)
    hidden = [c for c in range(25) if codes[c] == HIDDEN]
    return outcomes, purple, hidden


def purple_first(codes, idx):
    """The bot's own early-game rule."""
    return EXACT.early_pick(codes, idx)


def colblitz_mixed(codes, idx):
    outcomes, purple, hidden = _probs(codes, idx)
    gini = 1 - (outcomes**2).sum(axis=0) - purple**2
    return max(hidden, key=lambda c: purple[c] + 0.1 * gini[c])


def _mixed(weight):
    def rule(codes, idx):
        outcomes, purple, hidden = _probs(codes, idx)
        gini = 1 - (outcomes**2).sum(axis=0) - purple**2
        return max(hidden, key=lambda c: purple[c] + weight * gini[c])

    return rule


def info_first(codes, idx):
    """Most informative click: largest expected drop in possible placements."""
    outcomes, purple, hidden = _probs(codes, idx)
    probs = np.vstack([outcomes, purple])
    left = (probs**2).sum(axis=0)
    return max(hidden, key=lambda c: (-left[c], purple[c]))


RULES = {
    "purple_first": purple_first,
    "colblitz_mixed": colblitz_mixed,
    "mixed_0.4": _mixed(0.4),
    "info_first": info_first,
}


def play(rule_name: str, purples: frozenset[int]) -> float:
    rule = RULES[rule_name]
    codes = [HIDDEN] * 25
    paid, score = 0, 0.0
    while paid < CLICKS:
        state = tuple(codes)
        if CLICKS - paid <= ENDGAME or RED_SHOWN in state:
            c = EXACT.analyze(state).best
        else:
            c = rule(state, EXACT.consistent(state))
        if codes[c] == RED_SHOWN:
            score += PAY[RED]
            codes[c] = RED
            paid += 1
        elif c in purples:
            score += PAY[PURPLE]
            codes[c] = PURPLE
            found = {i for i, x in enumerate(codes) if x == PURPLE}
            if len(found) == 3:
                (last,) = purples - found
                codes[last] = RED_SHOWN
        else:
            n = purple_count(c, purples)
            score += PAY[n]
            codes[c] = n
            paid += 1
        if len(EXACT._memo) > 2_000_000:
            EXACT._memo.clear()
    return score


def _job(args):
    rule_name, purples = args
    return rule_name, play(rule_name, purples)


def main() -> None:
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    rng = random.Random(SEED)
    boards = [frozenset(rng.sample(range(25), 4)) for _ in range(games)]
    jobs = [(name, b) for name in RULES for b in boards]
    start = time.time()
    with Pool() as pool:
        results = pool.map(_job, jobs, chunksize=20)
    scores = {name: [] for name in RULES}
    for name, s in results:
        scores[name].append(s)
    base = np.array(scores["purple_first"])
    print(f"{games} games each, {time.time() - start:.0f} s")
    for name, s in scores.items():
        s = np.array(s)
        diff = s - base
        print(
            f"{name:16s} mean {s.mean():7.2f} ± {s.std(ddof=1) / len(s) ** 0.5:5.2f}"
            f"   vs purple_first {diff.mean():+6.2f}"
            f" ± {diff.std(ddof=1) / len(s) ** 0.5:4.2f}"
        )


if __name__ == "__main__":
    main()
