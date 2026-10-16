import pytest

from src.solver.board import BoardInputError, cell_index
from src.solver.modes.oh import BASE_PAYOUT, OC_GAME_VALUE, PRIZE_CHANCE, RATES
from src.solver.oh_board import add_spheres, parse_board
from src.solver.oh_rule import OhBoard, advise, prize_chance, sphere_average


def _advise(text: str):
    return advise(parse_board(text), BASE_PAYOUT, OC_GAME_VALUE)


def test_rates_leave_exactly_the_prize_share_of_one_tile():
    assert sum(RATES.values()) == pytest.approx(1 - PRIZE_CHANCE / 25)


def test_sphere_average_by_hand():
    by_hand = (
        0.0004 * 500
        + 0.0022 * 150
        + 0.0146 * 104
        + 0.0097 * 90
        + 0.0296 * 76
        + 0.0257 * 55
        + 0.0788 * 35
        + 0.2348 * 20
        + 0.5449 * 10
        + 0.0393 * 5
    ) / 0.98
    assert sphere_average(BASE_PAYOUT) == pytest.approx(by_hand)


def test_covered_value_mixes_in_the_prize_while_unfound():
    advice = _advise("A3B")
    chance = PRIZE_CHANCE / 24
    expected = (1 - chance) * sphere_average(BASE_PAYOUT) + chance * OC_GAME_VALUE
    assert advice.prize_chance == pytest.approx(chance)
    assert advice.covered_value == pytest.approx(expected)


def test_no_prize_once_found():
    board = parse_board("A3B B2C*")
    assert prize_chance(board) == 0
    advice = advise(board, BASE_PAYOUT, OC_GAME_VALUE)
    assert advice.covered_value == pytest.approx(sphere_average(BASE_PAYOUT))
    assert board.clicks_left == 4


def test_fresh_board_clicks_a_covered_tile():
    advice = _advise("A3B")
    assert advice.reason == "covered"
    assert advice.best == cell_index("A1")
    assert advice.clicks_left == 5


def test_visible_purple_is_clicked_first_and_costs_nothing():
    board = parse_board("A3B C3P")
    advice = advise(board, BASE_PAYOUT, OC_GAME_VALUE)
    assert (advice.best, advice.reason) == (cell_index("C3"), "purple")
    board = add_spheres(board, "*", advice.best)
    assert board.clicks_left == 5


def test_covered_beats_spheres_you_can_still_collect_later():
    # Two greens and five clicks: both greens fit in the clicks, so the covered
    # tile only competes with "nothing".
    advice = _advise("A1G A2G")
    assert advice.reason == "covered"
    assert advice.weakest_kept == 0


def test_last_click_takes_the_best_sphere_over_a_covered_tile():
    board = parse_board("A1B* A2B* A3B* A4B* B1G")
    advice = advise(board, BASE_PAYOUT, OC_GAME_VALUE)
    assert board.clicks_left == 1
    assert advice.weakest_kept == 35
    assert (advice.best, advice.reason) == (cell_index("B1"), "sphere")


def test_last_click_takes_a_covered_tile_over_a_blue():
    board = parse_board("A1B* A2B* A3B* A4B* B1B")
    advice = advise(board, BASE_PAYOUT, OC_GAME_VALUE)
    assert advice.reason == "covered"


def test_dark_goes_first_among_spheres_worth_keeping():
    board = parse_board("A1T* A2B* A3B* B1R B2D")
    advice = advise(board, BASE_PAYOUT, OC_GAME_VALUE)
    assert board.clicks_left == 2
    assert (advice.best, advice.reason) == (cell_index("B2"), "dark")


def test_red_beats_dark_when_only_one_click_is_left():
    board = parse_board("A1T* A2B* A3B* A4B* B1R B2D")
    advice = advise(board, BASE_PAYOUT, OC_GAME_VALUE)
    assert (advice.best, advice.reason) == (cell_index("B1"), "sphere")


def test_game_over_after_five_paid_clicks():
    advice = _advise("A1B* A2B* A3B* A4B* A5B* B1R")
    assert advice.best is None
    assert advice.clicks_left == 0


@pytest.mark.parametrize(
    "text, message",
    [
        ("A1", "sphere letter"),
        ("A1X", "one of"),
        ("A1B A1T", "already shown"),
        ("A1C", "prize"),
        ("A1C* A2C*", "at most one"),
        ("A1B* A2B* A3B* A4B* A5B* B1B*", "5 paid clicks"),
        ("G", "start with a cell"),
    ],
)
def test_bad_boards_are_rejected(text, message):
    with pytest.raises(BoardInputError, match=message):
        parse_board(text)


def test_spaces_between_cell_and_sphere_are_fine():
    assert parse_board("c4 g* a1 b") == parse_board("C4G* A1B")


def test_cell_after_cell_is_not_merged_as_a_sphere():
    assert parse_board("A1B B2T").cells[cell_index("B2")] == "T"


def test_adding_a_lone_letter_means_the_suggested_cell_was_clicked():
    board = add_spheres(parse_board("A3B"), "T B1 B", cell_index("A1"))
    assert board.cells[cell_index("A1")] == "T"
    assert board.clicked == {cell_index("A1")}
    assert board.cells[cell_index("B1")] == "B"


def test_clicking_a_covered_tile_needs_its_sphere():
    with pytest.raises(BoardInputError, match="covered"):
        add_spheres(OhBoard(), "A1*")
