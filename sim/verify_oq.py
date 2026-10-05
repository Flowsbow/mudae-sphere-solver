"""Monte Carlo check of the exact $oq endgame in src/solver/oq_ev.py.

Plays the solver's own picks against purple placements drawn by an independent
generator, and checks the average score against the solver's predicted value.

Run from the repo root: python -m sim.verify_oq
"""

import random
import statistics

from src.solver.modes.oq import LAYOUTS, PURPLE, RED, RED_SHOWN
from src.solver.oq_ev import HIDDEN, OqSolver

# Test values only, chosen so every color pays differently; the check holds for
# any payout table.
TEST_PAY = {0: 20, 1: 33, 2: 51, 3: 70, 4: 90, PURPLE: 14, RED: 195}
CLICKS = 7
GAMES = 4000
SEED = 2026


def purple_count(cell: int, purples: set[int]) -> int:
    r, c = divmod(cell, 5)
    return sum(
        1
        for dr in (-1, 0, 1)
        for dc in (-1, 0, 1)
        if (dr or dc)
        and 0 <= r + dr < 5
        and 0 <= c + dc < 5
        and (r + dr) * 5 + (c + dc) in purples
    )


def random_board(rng: random.Random, start: tuple[int, ...]) -> set[int]:
    """Uniform placement of 4 purples that agrees with the cells shown in `start`."""
    while True:
        purples = set(rng.sample(range(25), 4))
        if all(
            x == HIDDEN
            or (x in (PURPLE, RED, RED_SHOWN)) == (c in purples)
            and (x not in range(5) or purple_count(c, purples) == x)
            for c, x in enumerate(start)
        ):
            return purples


def play(solver: OqSolver, start: tuple[int, ...], purples: set[int]) -> float:
    codes = list(start)
    paid = sum(1 for x in codes if 0 <= x <= RED)
    score = 0.0
    while paid < CLICKS:
        c = solver.analyze(tuple(codes)).best
        if codes[c] == RED_SHOWN:
            score += TEST_PAY[RED]
            codes[c] = RED
            paid += 1
        elif c in purples:
            score += TEST_PAY[PURPLE]
            codes[c] = PURPLE
            found = {i for i, x in enumerate(codes) if x == PURPLE}
            if len(found) == 3:
                (last,) = purples - found
                codes[last] = RED_SHOWN
        else:
            n = purple_count(c, purples)
            score += TEST_PAY[n]
            codes[c] = n
            paid += 1
    return score


def start_from(
    rng: random.Random, solver: OqSolver, n_paid: int, n_purple: int
) -> tuple[int, ...]:
    """A random mid-game board where at least 20 placements are still possible."""
    while True:
        codes = _random_start(rng, n_paid, n_purple)
        if len(solver.consistent(codes)) >= 20:
            return codes


def _random_start(rng: random.Random, n_paid: int, n_purple: int) -> tuple[int, ...]:
    purples = set(rng.sample(range(25), 4))
    codes = [HIDDEN] * 25
    for c in rng.sample(sorted(purples), n_purple):
        codes[c] = PURPLE
    others = [c for c in range(25) if c not in purples]
    for c in rng.sample(others, n_paid):
        codes[c] = purple_count(c, purples)
    return tuple(codes)


def run_cases(solver: OqSolver) -> list[dict]:
    """Predicted vs simulated value on three fixed mid-game positions."""
    rng = random.Random(SEED)
    cases = [
        ("2 clicks left", start_from(rng, solver, 5, 0)),
        ("2 clicks left, 2 purples found", start_from(rng, solver, 5, 2)),
        ("3 clicks left, 1 purple found", start_from(rng, solver, 4, 1)),
    ]
    results = []
    for name, start in cases:
        predicted = solver.analyze(start).value
        scores = [play(solver, start, random_board(rng, start)) for _ in range(GAMES)]
        mean = statistics.fmean(scores)
        se = statistics.stdev(scores) / len(scores) ** 0.5
        results.append({"name": name, "predicted": predicted, "mean": mean, "se": se})
    return results


def main() -> None:
    all_ok = True
    for r in run_cases(OqSolver(LAYOUTS, TEST_PAY)):
        ok = abs(r["mean"] - r["predicted"]) <= 3 * r["se"]
        all_ok &= ok
        print(
            f"{r['name']:32s} predicted {r['predicted']:8.3f}"
            f"  simulated {r['mean']:8.3f} ± {r['se']:.3f}  {'PASS' if ok else 'FAIL'}"
        )
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
