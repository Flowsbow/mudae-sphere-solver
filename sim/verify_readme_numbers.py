"""Checks the README's extra $oc expected values by independent simulation.

The predictions are the exact values in docs/readme_numbers.json. Boards come
from sim/verify_oc.py's generator, which builds them from the rules without the
solver's enumeration. For the every-board-equally-likely model those boards are
thinned by rejection, keeping red at r with probability proportional to the
number of boards with red at r, counted from the board geometry.

Run from the repo root: python -m sim.verify_readme_numbers
"""

import json
from math import comb
from pathlib import Path

import numpy as np

from sim.verify_oc import random_board
from src.solver.board import BoardState, Color, cell_index
from src.solver.ev import Solver
from src.solver.modes import oc

NUMBERS = json.loads(
    (Path(__file__).parent.parent / "docs" / "readme_numbers.json").read_text()
)["oc"]
GAMES = 20_000
SEED = 1
MOST_BOARDS = comb(4, 2) * comb(6, 3)  # most boards for any one red cell


def boards_with_red_at(cell: int) -> int:
    r, c = divmod(cell, 5)
    others = [(rr, cc) for rr in range(5) for cc in range(5) if (rr, cc) != (r, c)]
    sides = sum(abs(rr - r) + abs(cc - c) == 1 for rr, cc in others)
    diagonals = sum(abs(rr - r) == abs(cc - c) for rr, cc in others)
    return comb(sides, 2) * comb(diagonals, 3)


def layout_board(rng: np.random.Generator) -> list[Color]:
    while True:
        board = random_board(rng)
        if rng.random() < boards_with_red_at(board.index(Color.RED)) / MOST_BOARDS:
            return board


def policy(solver: Solver, greedy: bool = False, first: int | None = None):
    cache: dict = {}

    def choose(state: BoardState) -> int:
        if first is not None and state.n_revealed == 0:
            return first
        if state not in cache:
            analysis = solver.analyze(state)
            if greedy:
                immediate = {
                    c: sum(p * solver.pay[k] for k, p in probs.items())
                    for c, probs in analysis.color_probs.items()
                }
                cache[state] = max(sorted(immediate), key=immediate.get)
            else:
                cache[state] = analysis.best
        return cache[state]

    return choose


def simulate(choose, draw) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(SEED)
    scores, reds = np.zeros(GAMES), np.zeros(GAMES)
    for g in range(GAMES):
        board = draw(rng)
        state = BoardState()
        for _ in range(oc.CLICKS):
            cell = choose(state)
            state = state.reveal(cell, board[cell])
            scores[g] += oc.BASE_PAYOUT[board[cell]]
            reds[g] += board[cell] == Color.RED
    return scores, reds


def check(name: str, predicted: float, values: np.ndarray) -> bool:
    mean = values.mean()
    se = values.std(ddof=1) / np.sqrt(len(values))
    z = (mean - predicted) / se
    ok = abs(z) <= 3
    print(
        f"{name:46s} predicted {predicted:9.3f}  simulated {mean:9.3f} ± {se:.3f}"
        f"  {z:+.2f} SE  {'PASS' if ok else 'FAIL'}"
    )
    return ok


def main() -> int:
    cell_model = Solver(
        oc.LAYOUTS,
        oc.prior(oc.RedModel.UNIFORM_CELL),
        oc.BASE_PAYOUT,
        oc.CLICKS,
        oc.SYMMETRIES,
    )
    layout_model = Solver(
        oc.LAYOUTS,
        oc.prior(oc.RedModel.UNIFORM_LAYOUT),
        oc.BASE_PAYOUT,
        oc.CLICKS,
        oc.SYMMETRIES,
    )
    cell, layout = NUMBERS["UNIFORM_CELL"], NUMBERS["UNIFORM_LAYOUT"]
    ok = True

    scores, reds = simulate(policy(cell_model), random_board)
    ok &= check("solver's model, optimal", cell["optimal_value"], scores)
    ok &= check("  P(red found)", cell["optimal_red_found"], reds)
    scores, reds = simulate(policy(cell_model, greedy=True), random_board)
    ok &= check("solver's model, greedy", cell["greedy_value"], scores)
    ok &= check("  P(red found)", cell["greedy_red_found"], reds)
    for name in ("A1", "A2", "A3", "B3", "C3"):
        i = cell_index(name)
        scores, _ = simulate(policy(cell_model, first=i), random_board)
        ok &= check(
            f"first click {name}, then optimal", cell["first_click_value"][i], scores
        )
    scores, _ = simulate(policy(layout_model), layout_board)
    ok &= check("every board equally likely, optimal", layout["optimal_value"], scores)
    scores, _ = simulate(policy(layout_model, greedy=True), layout_board)
    ok &= check("every board equally likely, greedy", layout["greedy_value"], scores)
    scores, _ = simulate(policy(cell_model), layout_board)
    ok &= check(
        "solver's strategy, every board equally likely",
        NUMBERS["cell_strategy_on_layout_boards"],
        scores,
    )
    scores, _ = simulate(policy(layout_model), random_board)
    ok &= check(
        "other model's strategy, solver's boards",
        NUMBERS["layout_strategy_on_cell_boards"],
        scores,
    )
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
