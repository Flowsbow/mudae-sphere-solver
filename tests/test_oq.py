import pytest

from src.solver.board import cell_index
from src.solver.ev import InconsistentBoardError
from src.solver.modes.oc import SYMMETRIES
from src.solver.modes.oq import LAYOUTS, PURPLE, RED, RED_SHOWN, neighbors
from src.solver.oq_ev import EXACT_CLICKS, HIDDEN, OqSolver, clicks_used

# Test values only: every code pays differently, so a mix-up changes the answer.
PAY = {0: 20, 1: 33, 2: 51, 3: 70, 4: 90, PURPLE: 14, RED: 195}

# Flow's finished $oq board, 2026-09-30 screenshot. P = purple, R = the red.
SCREENSHOT = ["G P G T T", "G P G T P", "T T T T T", "T T B B B", "R T B B B"]
LETTER_CODE = {"B": 0, "T": 1, "G": 2, "Y": 3, "O": 4, "P": PURPLE, "R": PURPLE}


@pytest.fixture(scope="module")
def solver():
    return OqSolver(LAYOUTS, PAY)


def board(**cells) -> tuple[int, ...]:
    codes = [HIDDEN] * 25
    for name, code in cells.items():
        codes[cell_index(name)] = code
    return tuple(codes)


def test_every_placement_of_four_purples_is_listed():
    assert len(LAYOUTS) == 12650  # 25 choose 4
    assert ((LAYOUTS == PURPLE).sum(axis=1) == 4).all()


def test_the_screenshot_board_is_a_legal_layout():
    cells = [LETTER_CODE[x] for row in SCREENSHOT for x in row.split()]
    assert (LAYOUTS == cells).all(axis=1).sum() == 1


@pytest.mark.parametrize(("cell", "n"), [("A1", 3), ("A3", 5), ("C3", 8)])
def test_neighbors_are_the_8_tiles_around(cell, n):
    assert len(neighbors(cell_index(cell))) == n


def test_the_red_costs_a_click_and_purples_do_not():
    assert clicks_used(board(A1=PURPLE, B2=PURPLE, C3=PURPLE, D4=RED, E5=0)) == 2


def test_once_every_purple_is_known_the_rest_is_simple(solver):
    # Purples A2 B2 B5 found, red shown at E1, 1 paid click used (D4 blue):
    # 6 clicks left, so the red plus the five best remaining cells.
    codes = board(A2=PURPLE, B2=PURPLE, B5=PURPLE, E1=RED_SHOWN, D4=0)
    result = solver.analyze(codes)
    assert result.exact
    # The red, the four greens (A1 A3 B1 B3) and one teal.
    assert result.value == pytest.approx(195 + 4 * 51 + 33)
    assert result.cell_value[cell_index("E1")] == pytest.approx(result.value)


def test_the_last_click_takes_the_red_when_it_is_shown(solver):
    codes = board(
        A2=PURPLE,
        B2=PURPLE,
        B5=PURPLE,
        E1=RED_SHOWN,
        A1=2,
        A3=2,
        B1=2,
        B3=2,
        A4=1,
        A5=1,
    )
    result = solver.analyze(codes)
    assert result.clicks_left == 1
    assert result.best == cell_index("E1")
    assert result.value == pytest.approx(195)


def test_early_clicks_use_the_rule_and_late_clicks_are_exact(solver):
    early = solver.analyze(board())
    assert not early.exact and early.value is None
    assert early.purple_prob[0] == pytest.approx(4 / 25)
    late = board(A1=0, A2=0, A3=0, A4=1, A5=1)
    result = solver.analyze(late)
    assert result.clicks_left == 2 <= EXACT_CLICKS
    assert result.exact and result.value > 0


def test_symmetry_does_not_change_the_answer():
    codes = board(A1=2, C3=1, D4=0, E5=0, A5=1)  # cells of the screenshot board
    plain = OqSolver(LAYOUTS, PAY).analyze(codes)
    fast = OqSolver(LAYOUTS, PAY, symmetries=SYMMETRIES).analyze(codes)
    assert fast.value == pytest.approx(plain.value)
    assert fast.best == plain.best


def test_an_impossible_board_is_refused(solver):
    with pytest.raises(InconsistentBoardError):
        solver.analyze(board(A1=4))  # a corner has only 3 neighbors


def test_equal_totals_go_to_the_bigger_payout_first(solver):
    # Every purple known, 6 paid clicks left: any order of the best 6 clicks gives
    # the same total, so the red (195) should be suggested before a green.
    codes = board(A2=PURPLE, B2=PURPLE, C2=PURPLE, D4=RED_SHOWN, E1=0)
    result = solver.analyze(codes)
    assert result.value == pytest.approx(195 + 3 * 70 + 2 * 51)
    assert result.best == cell_index("D4")


def test_early_rule_ties_are_cells_with_the_same_odds_and_payout(solver):
    analysis = solver.analyze((HIDDEN,) * 25)
    assert not analysis.exact
    assert analysis.best in analysis.tied
    # On an empty board every inner tile has the same odds and payout chances.
    inner = {cell_index(f"{r}{c}") for r in "BCD" for c in "234"}
    assert analysis.tied == inner
    for cell in analysis.tied:
        assert analysis.purple_prob[cell] == pytest.approx(
            analysis.purple_prob[analysis.best]
        )
        assert analysis.cell_payout[cell] == pytest.approx(
            analysis.cell_payout[analysis.best]
        )


def test_exact_ties_are_cells_with_the_same_value(solver):
    # Every purple is known here, so all collecting orders tie.
    codes = board(A1=PURPLE, B2=PURPLE, C3=PURPLE, D4=RED_SHOWN)
    analysis = solver.analyze(codes)
    assert analysis.exact
    top = analysis.cell_value[analysis.best]
    assert analysis.tied == {
        c for c, v in analysis.cell_value.items() if v == pytest.approx(top)
    }
    assert len(analysis.tied) > 1


def test_too_many_placements_with_three_clicks_left_waits_for_two():
    # The audit's slow board: 1,820 placements fit, 42.6 s for an exact search.
    codes = board(A1=0, A2=0, B1=0, B2=0)
    capped = OqSolver(LAYOUTS, PAY)
    assert len(capped.consistent(codes)) == 1820
    analysis = capped.analyze(codes)
    assert analysis.clicks_left == EXACT_CLICKS
    assert not analysis.exact and analysis.best is not None
    assert capped._memo == {}


def test_few_placements_with_three_clicks_left_still_search_exactly(solver):
    codes = board(C3=0, B4=2, A1=1, E5=0)  # 4 paid clicks used
    assert len(solver.consistent(codes)) <= 100
    assert solver.analyze(codes).exact


def test_best_on_board_is_the_hindsight_of_that_one_board(solver):
    layout = LAYOUTS[1234]
    known = solver.best_on_board(tuple(int(x) for x in layout))
    assert known == pytest.approx(solver._known_value((HIDDEN,) * 25, layout))


def test_best_on_board_refuses_a_board_that_breaks_the_rules(solver):
    with pytest.raises(InconsistentBoardError):
        solver.best_on_board((0,) * 25)
