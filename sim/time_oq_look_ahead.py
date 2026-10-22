"""Time the $oq look-ahead (OqService._look_ahead) and check it changes no answer.

Plays random boards by the early-game rule to 4 paid clicks left, the board
before the exact search starts. For each, it searches the boards the suggested
click can lead to, likeliest first, as the bot does while the player clicks.
Then, for the board the click really led to, it times the reply from that cache
against a cold search and checks both give the same analysis.

    python sim/time_oq_look_ahead.py --boards 20
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sim.time_oq_search import reveal  # noqa: E402
from src.solver.modes.oc import SYMMETRIES  # noqa: E402
from src.solver.modes.oq import BASE_PAYOUT, CLICKS, LAYOUTS, RED_SHOWN  # noqa: E402
from src.solver.oq_ev import EXACT_CLICKS, HIDDEN, OqSolver, clicks_used  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--boards", type=int, default=20)
    parser.add_argument("--seed", type=int, default=3)
    args = parser.parse_args()
    rng = np.random.default_rng(args.seed)
    rule = OqSolver(LAYOUTS, BASE_PAYOUT, symmetries=SYMMETRIES)
    rows = []
    while len(rows) < args.boards:
        layout = LAYOUTS[rng.integers(len(LAYOUTS))]
        codes = (HIDDEN,) * 25
        while CLICKS - clicks_used(codes) > EXACT_CLICKS + 1:
            if RED_SHOWN in codes:
                cell = codes.index(RED_SHOWN)
            else:
                cell = rule.early_pick(codes, rule.consistent(codes))
            codes = reveal(codes, cell, layout)
        ahead = OqSolver(LAYOUTS, BASE_PAYOUT, symmetries=SYMMETRIES)
        best = ahead.analyze(codes).best
        boards = ahead.next_exact_positions(codes, best)
        actual = reveal(codes, best, layout)
        if actual not in boards:
            continue  # a purple, or few enough placements to need no search
        started = time.perf_counter()
        first_done = None
        for board in boards:
            ahead.analyze(board)
            if board == actual:
                first_done = time.perf_counter() - started
        all_done = time.perf_counter() - started
        started = time.perf_counter()
        warm = ahead.analyze(actual)
        warm_s = time.perf_counter() - started
        cold_solver = OqSolver(LAYOUTS, BASE_PAYOUT, symmetries=SYMMETRIES)
        started = time.perf_counter()
        cold = cold_solver.analyze(actual)
        cold_s = time.perf_counter() - started
        assert warm == cold, (codes, actual)
        rank = boards.index(actual) + 1
        rows.append((cold_s, warm_s, first_done, all_done, rank))
        print(
            f"cold {cold_s:5.2f}s | from look-ahead {warm_s:5.3f}s | real board "
            f"ready after {first_done:5.2f}s (#{rank} of {len(boards)}) | all "
            f"{all_done:5.2f}s"
        )
    cold, warm, ready, _, rank = map(np.array, zip(*rows, strict=True))
    print(
        f"\n{len(rows)} boards, all answers identical. Median: cold "
        f"{np.median(cold):.2f}s, from look-ahead {np.median(warm):.3f}s, real "
        f"board ready after {np.median(ready):.2f}s; it was the likeliest one "
        f"{np.mean(rank == 1):.0%} of the time."
    )


if __name__ == "__main__":
    main()
