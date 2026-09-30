import numpy as np
import pytest

from src.solver.board import COLOR_LETTERS, N_CELLS, SIZE, Color, cell_name
from src.solver.modes.oc import CENTER, LAYOUT_RED, LAYOUTS, RedModel, prior

# Flow's $oc screenshot, 2026-09-26, rows A to E.
SCREENSHOT_BOARD = ["TBBGB", "BTBTB", "BBTTY", "GGGRO", "BBYOY"]

# Derived by hand: C(side neighbors, 2) * C(diagonal cells, 3) * C(6, 4).
EXPECTED_LAYOUTS_PER_RED_CELL = {
    "corner": 1 * 4 * 15,
    "edge": 3 * 4 * 15,
    "inner": 6 * 20 * 15,
}


def _kind(i: int) -> str:
    r, c = divmod(i, SIZE)
    on_edge_row = r in (0, SIZE - 1)
    on_edge_col = c in (0, SIZE - 1)
    if on_edge_row and on_edge_col:
        return "corner"
    if on_edge_row or on_edge_col:
        return "edge"
    return "inner"


def test_layout_count_per_red_cell_matches_hand_count():
    counts = np.bincount(LAYOUT_RED, minlength=N_CELLS)
    for i in range(N_CELLS):
        expected = 0 if i == CENTER else EXPECTED_LAYOUTS_PER_RED_CELL[_kind(i)]
        assert counts[i] == expected, cell_name(i)
    assert counts.sum() == 16_800


def test_layouts_are_distinct():
    assert len(np.unique(LAYOUTS, axis=0)) == len(LAYOUTS)


def test_every_layout_obeys_the_rules():
    rows, cols = np.divmod(np.arange(N_CELLS), SIZE)
    red_rows, red_cols = np.divmod(LAYOUT_RED.astype(int), SIZE)
    dr = rows[None, :] - red_rows[:, None]
    dc = cols[None, :] - red_cols[:, None]
    is_red = (dr == 0) & (dc == 0)
    touches_side = np.abs(dr) + np.abs(dc) == 1
    same_row_or_col = ((dr == 0) | (dc == 0)) & ~is_red
    on_diagonal = (np.abs(dr) == np.abs(dc)) & ~is_red
    on_line = same_row_or_col | on_diagonal

    def where(color: Color) -> np.ndarray:
        return LAYOUTS == color

    assert (where(Color.RED) == is_red).all()
    assert not is_red[:, CENTER].any()
    # Counts 2, 3, 4 from Mudae's rules text.
    assert (where(Color.ORANGE).sum(axis=1) == 2).all()
    assert (where(Color.YELLOW).sum(axis=1) == 3).all()
    assert (where(Color.GREEN).sum(axis=1) == 4).all()
    assert not (where(Color.ORANGE) & ~touches_side).any()
    assert not (where(Color.YELLOW) & ~on_diagonal).any()
    assert not (where(Color.GREEN) & ~same_row_or_col).any()
    assert not (where(Color.TEAL) & ~on_line).any()
    assert (where(Color.BLUE) == (~on_line & ~is_red)).all()


def test_screenshot_board_is_exactly_one_layout():
    board = np.array([COLOR_LETTERS[ch] for row in SCREENSHOT_BOARD for ch in row])
    assert (LAYOUTS == board).all(axis=1).sum() == 1


@pytest.mark.parametrize("model", list(RedModel))
def test_prior_sums_to_one(model):
    assert np.isclose(prior(model).sum(), 1)


def test_uniform_cell_prior_gives_each_allowed_cell_one_24th():
    per_cell = np.bincount(
        LAYOUT_RED, weights=prior(RedModel.UNIFORM_CELL), minlength=N_CELLS
    )
    expected = np.full(N_CELLS, 1 / 24)
    expected[CENTER] = 0
    assert np.allclose(per_cell, expected)


def test_uniform_layout_prior_puts_one_seventh_of_red_on_the_outer_ring():
    outer = np.array([_kind(i) != "inner" for i in range(N_CELLS)])
    p_outer = prior(RedModel.UNIFORM_LAYOUT)[outer[LAYOUT_RED]].sum()
    # (4 * 60 + 12 * 180) / 16_800 = 2400 / 16_800 = 1/7
    assert np.isclose(p_outer, 1 / 7)


def test_there_are_eight_distinct_symmetries_and_they_fix_the_center():
    from src.solver.modes.oc import SYMMETRIES

    assert len(set(SYMMETRIES)) == 8
    assert all(sorted(perm) == list(range(N_CELLS)) for perm in SYMMETRIES)
    assert all(perm[CENTER] == CENTER for perm in SYMMETRIES)


def test_legal_boards_and_prior_are_unchanged_by_every_symmetry():
    from src.solver.modes.oc import SYMMETRIES

    weight = {row.tobytes(): w for row, w in zip(LAYOUTS, prior(), strict=True)}
    for perm in SYMMETRIES:
        moved = LAYOUTS[:, list(perm)]
        for row, w in zip(moved, prior(), strict=True):
            assert weight[row.tobytes()] == pytest.approx(w)
