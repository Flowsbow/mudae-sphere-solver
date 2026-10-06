import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.solver.board import BoardState, Color  # noqa: E402
from src.solver.ev import Solver  # noqa: E402
from src.solver.modes.oc import (  # noqa: E402
    BASE_PAYOUT,
    CLICKS,
    LAYOUTS,
    SYMMETRIES,
    prior,
)
from src.solver.payouts import with_bonus  # noqa: E402

SIZE = 5
CENTER = (2, 2)


def random_board(rng: np.random.Generator) -> list[Color]:
    cells = [(r, c) for r in range(SIZE) for c in range(SIZE)]
    red = cells[rng.choice([i for i, rc in enumerate(cells) if rc != CENTER])]
    rr, rc = red
    sides = [(r, c) for r, c in cells if abs(r - rr) + abs(c - rc) == 1]
    row_col = [(r, c) for r, c in cells if (r == rr) != (c == rc)]
    diagonal = [(r, c) for r, c in cells if abs(r - rr) == abs(c - rc) != 0]

    oranges = [sides[i] for i in rng.choice(len(sides), 2, replace=False)]
    yellows = [diagonal[i] for i in rng.choice(len(diagonal), 3, replace=False)]
    green_pool = [rc_ for rc_ in row_col if rc_ not in oranges]
    greens = [green_pool[i] for i in rng.choice(len(green_pool), 4, replace=False)]

    board = {}
    for cell in cells:
        on_line = cell in row_col or cell in diagonal
        board[cell] = Color.TEAL if on_line else Color.BLUE
    for group, color in (
        (oranges, Color.ORANGE),
        (yellows, Color.YELLOW),
        (greens, Color.GREEN),
        ([red], Color.RED),
    ):
        for cell in group:
            board[cell] = color
    return [board[cell] for cell in cells]


def play(solver: Solver, board: list[Color], best_cache: dict, payouts: dict) -> float:
    state = BoardState()
    total = 0.0
    for _ in range(CLICKS):
        if state not in best_cache:
            best_cache[state] = solver.analyze(state).best
        cell = best_cache[state]
        state = state.reveal(cell, board[cell])
        total += payouts[board[cell]]
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--flat", type=int, default=0, help="sphere bonus, +N")
    parser.add_argument("--percent", type=int, default=0, help="sphere bonus, %%")
    args = parser.parse_args()
    if args.games < 2:
        parser.error("--games must be at least 2 to estimate a standard error")

    payouts = with_bonus(BASE_PAYOUT, args.flat, args.percent)
    solver = Solver(LAYOUTS, prior(), payouts, CLICKS, SYMMETRIES)
    start = time.time()
    predicted = solver.analyze(BoardState()).value
    print(f"ev.py prediction: {predicted:.3f}  ({time.time() - start:.0f} s)")

    rng = np.random.default_rng(args.seed)
    best_cache: dict = {}
    scores = np.array(
        [
            play(solver, random_board(rng), best_cache, payouts)
            for _ in range(args.games)
        ]
    )
    mean = scores.mean()
    se = scores.std(ddof=1) / np.sqrt(args.games)
    z = (mean - predicted) / se
    print(f"simulated mean:   {mean:.3f} ± {se:.3f} (1 SE, {args.games} games)")
    print(f"difference:       {mean - predicted:+.3f} = {z:+.2f} SE")

    # A correct solver lands within 3 SE of its prediction 99.7% of the time.
    if not np.isfinite(z) or abs(z) > 3:
        print("FAIL: simulation disagrees with ev.py")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
