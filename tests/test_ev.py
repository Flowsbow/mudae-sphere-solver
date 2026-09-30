import numpy as np
import pytest

from src.solver.board import N_CELLS, BoardState, Color, cell_index
from src.solver.ev import InconsistentBoardError, Solver
from src.solver.modes.oc import BASE_PAYOUT, CENTER, CLICKS, LAYOUTS, prior


@pytest.fixture(scope="module")
def solver():
    return Solver(LAYOUTS, prior(), BASE_PAYOUT, CLICKS)


def _naive_value(state: BoardState, clicks_left: int) -> float:
    mask = np.ones(len(LAYOUTS), dtype=bool)
    for c, color in enumerate(state.revealed):
        if color is not None:
            mask &= LAYOUTS[:, c] == color
    w = prior()[mask]
    boards = LAYOUTS[mask]
    if clicks_left == 0:
        return 0.0
    best = -1.0
    for c in range(N_CELLS):
        if state.revealed[c] is not None:
            continue
        v = 0.0
        for k in set(boards[:, c].tolist()):
            p = w[boards[:, c] == k].sum() / w.sum()
            child = state.reveal(c, Color(k))
            v += p * (BASE_PAYOUT[Color(k)] + _naive_value(child, clicks_left - 1))
        best = max(best, v)
    return best


def test_known_red_corner_with_two_clicks_takes_both_oranges(solver):
    # Red at A1 forces orange on A2 and B1; C2 and B3 are off red's lines.
    a = solver.analyze(BoardState.parse("A1R C2B B3B"))
    assert a.clicks_left == 2
    assert a.value == pytest.approx(180)
    assert a.best in (cell_index("A2"), cell_index("B1"))


def test_known_red_corner_with_three_clicks(solver):
    # 90 + 90 for the oranges, then a diagonal cell: 3/4 yellow, 1/4 teal.
    a = solver.analyze(BoardState.parse("A1R B3B"))
    assert a.value == pytest.approx(180 + 0.75 * 55 + 0.25 * 20)


@pytest.mark.parametrize("text", ["D4R B2T", "A1R B3B C2B", "C3G E5B A4Y"])
def test_matches_naive_search(solver, text):
    state = BoardState.parse(text)
    assert solver.analyze(state).value == pytest.approx(
        _naive_value(state, CLICKS - state.n_revealed)
    )


def test_color_probs_sum_to_one_per_cell(solver):
    a = solver.analyze(BoardState.parse("E5B"))
    assert a.color_probs[CENTER][Color.RED] == 0
    for probs in a.color_probs.values():
        assert sum(probs.values()) == pytest.approx(1)


def test_red_is_one_24th_everywhere_but_center_before_any_click():
    s = Solver(LAYOUTS, prior(), BASE_PAYOUT, clicks=1)
    a = s.analyze(BoardState())
    for c in range(N_CELLS):
        expected = 0 if c == CENTER else 1 / 24
        assert a.color_probs[c][Color.RED] == pytest.approx(expected)


def test_ties_go_to_the_lowest_cell(solver):
    a = solver.analyze(BoardState.parse("A1R B3B"))
    top = max(a.cell_value.values())
    tied = [c for c, v in a.cell_value.items() if v == pytest.approx(top)]
    assert a.best == min(tied)


@pytest.mark.parametrize(
    "text", ["A1R B1R", "A1R C3O", "C3R", "A1B B2B C3B D4B E5B A2B"]
)
def test_rejects_impossible_boards(solver, text):
    with pytest.raises(InconsistentBoardError):
        solver.analyze(BoardState.parse(text))


@pytest.mark.parametrize("text", ["A1B", "D4R B2T", "C3G E5B", "B2Y D1T"])
def test_symmetry_cache_gives_identical_answers(solver, text):
    from src.solver.modes.oc import SYMMETRIES

    fast = Solver(LAYOUTS, prior(), BASE_PAYOUT, CLICKS, SYMMETRIES)
    state = BoardState.parse(text)
    plain = solver.analyze(state)
    sym = fast.analyze(state)
    assert sym.value == pytest.approx(plain.value)
    assert sym.best == plain.best
    for c, v in plain.cell_value.items():
        assert sym.cell_value[c] == pytest.approx(v)


def test_rotated_positions_have_equal_values():
    from src.solver.modes.oc import SYMMETRIES

    fast = Solver(LAYOUTS, prior(), BASE_PAYOUT, CLICKS, SYMMETRIES)
    state = BoardState.parse("A2T D5B")
    values = set()
    for perm in SYMMETRIES:
        moved = BoardState(tuple(state.revealed[i] for i in perm))
        values.add(round(fast.analyze(moved).value, 9))
    assert len(values) == 1
