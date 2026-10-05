"""Computes the README's $oc and $oq tables and writes docs/readme_numbers.json.

Run from the repo root: python -m docs.readme_numbers
Takes a few minutes. Timings depend on the machine, which is recorded too.
"""

import json
import platform
import time
from math import comb
from pathlib import Path

import numpy as np

from src.solver.board import N_CELLS, BoardState, Color, cell_name
from src.solver.ev import Solver
from src.solver.modes import oc, oq
from src.solver.oq_ev import HIDDEN, OqSolver

OUT = Path(__file__).parent / "readme_numbers.json"
# Used only to time the $oq search; the search does the same work for any table.
OQ_TIMING_PAY = {0: 20, 1: 33, 2: 51, 3: 70, 4: 90, oq.PURPLE: 14, oq.RED: 195}
RING = [i for i in range(N_CELLS) if i // 5 in (0, 4) or i % 5 in (0, 4)]


def solver_for(model: oc.RedModel, symmetries=oc.SYMMETRIES) -> Solver:
    return Solver(oc.LAYOUTS, oc.prior(model), oc.BASE_PAYOUT, oc.CLICKS, symmetries)


def play_exactly(policy: Solver, truth: Solver, greedy: bool) -> tuple[float, float]:
    """Exact expected spheres and P(red found) when `policy` picks every click
    and the boards really follow `truth`'s red model."""

    def pick(state: BoardState, idx: np.ndarray) -> int:
        if not greedy:
            return policy.analyze(state).best
        w = policy.weights[idx]
        immediate = (w @ policy.cell_pay[idx]) / w.sum()
        hidden = [c for c in range(N_CELLS) if state.revealed[c] is None]
        return max(hidden, key=lambda c: (immediate[c], -c))

    def go(state: BoardState, idx: np.ndarray) -> tuple[float, float]:
        if state.n_revealed == oc.CLICKS:
            return 0.0, 0.0
        cell = pick(state, idx)
        w = truth.weights[idx]
        column = truth.layouts[idx, cell]
        value = red = 0.0
        for k in np.unique(column):
            sub = idx[column == k]
            p = truth.weights[sub].sum() / w.sum()
            v, r = go(state.reveal(cell, Color(int(k))), sub)
            value += p * (truth.pay[k] + v)
            red += p * (1.0 if k == Color.RED else r)
        return value, red

    return go(BoardState(), np.arange(len(truth.layouts)))


def oc_numbers() -> dict:
    counts = np.bincount(oc.LAYOUT_RED, minlength=N_CELLS)
    for r in oc.RED_CELLS:
        sides, diagonals = len(oc.side_neighbors(r)), len(oc.diagonal_cells(r))
        line = len(oc.row_col_cells(r))
        assert counts[r] == comb(sides, 2) * comb(diagonals, 3) * comb(line - 2, 4)
    n = {"boards_per_red_cell": [int(x) for x in counts], "boards": int(counts.sum())}

    solvers = {model: solver_for(model) for model in oc.RedModel}
    for model, solver in solvers.items():
        red = np.bincount(oc.LAYOUT_RED, weights=solver.weights, minlength=N_CELLS)
        start = time.time()
        a = solver.analyze(BoardState())
        seconds = time.time() - start
        opt_value, opt_red = play_exactly(solver, solver, greedy=False)
        greedy_value, greedy_red = play_exactly(solver, solver, greedy=True)
        n[model.name] = {
            "red_on_outer_ring": float(red[RING].sum()),
            "best_first_click": cell_name(a.best),
            "first_click_value": [a.cell_value[c] for c in range(N_CELLS)],
            "optimal_value": opt_value,
            "optimal_red_found": opt_red,
            "greedy_value": greedy_value,
            "greedy_red_found": greedy_red,
            "seconds_empty_board": seconds,
        }
    cell, layout = (
        solvers[oc.RedModel.UNIFORM_CELL],
        solvers[oc.RedModel.UNIFORM_LAYOUT],
    )
    n["cell_strategy_on_layout_boards"], _ = play_exactly(cell, layout, greedy=False)
    n["layout_strategy_on_cell_boards"], _ = play_exactly(layout, cell, greedy=False)
    return n


def oq_numbers() -> dict:
    first_click = {}
    for name, cell in (("corner", 0), ("edge", 2), ("inner", 12)):
        m = len(oq.neighbors(cell))
        column = oq.LAYOUTS[:, cell]
        probs = [float((column == k).mean()) for k in range(5)]
        probs.append(float((column == oq.PURPLE).mean()))
        # P(k purples among m neighbours) = C(m,k) C(24-m, 4-k) / C(25,4).
        formula = [comb(m, k) * comb(24 - m, 4 - k) / comb(25, 4) for k in range(5)]
        assert np.allclose(probs, formula + [4 / 25])
        first_click[name] = {"neighbors": m, "probs": probs}

    rng = np.random.default_rng(0)
    layout = oq.LAYOUTS[rng.integers(len(oq.LAYOUTS))]
    order = list(rng.permutation([c for c in range(N_CELLS) if layout[c] != oq.PURPLE]))
    search = []
    for paid in (5, 4, 3):
        codes = [HIDDEN] * N_CELLS
        for c in order[:paid]:
            codes[c] = int(layout[c])
        state = tuple(codes)
        solver = OqSolver(oq.LAYOUTS, OQ_TIMING_PAY, symmetries=oc.SYMMETRIES)
        start = time.time()
        # analyze() would hand 4 paid clicks left to the early rule, so call the
        # exact search directly.
        solver._cell_values(state, solver.consistent(state))
        search.append(
            {
                "paid_clicks_left": oq.CLICKS - paid,
                "positions": len(solver._memo),
                "seconds": time.time() - start,
            }
        )
    return {"placements": len(oq.LAYOUTS), "first_click": first_click, "search": search}


def _cpu() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def main() -> None:
    numbers = {
        "machine": f"{_cpu()}, Python {platform.python_version()}",
        "oc": oc_numbers(),
        "oq": oq_numbers(),
    }
    OUT.write_text(json.dumps(numbers, indent=2))
    print(json.dumps(numbers, indent=1)[:3000])


if __name__ == "__main__":
    main()
