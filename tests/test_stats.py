import pytest

from src.solver.board import Color, cell_index
from src.solver.modes.oc import BASE_PAYOUT
from src.solver.stats import Step, game_stats


def _step(name, color, recommended=None):
    rec = cell_index(recommended) if recommended else None
    return Step(cell_index(name), color, rec)


def test_score_luck_red_and_followed():
    steps = [
        _step("C3", Color.TEAL, "C3"),
        _step("B2", Color.YELLOW, "B2"),
        _step("A1", Color.RED, "A1"),
        _step("A2", Color.ORANGE, "B1"),
        _step("B1", Color.ORANGE, "B1"),
    ]
    stats = game_stats(steps, BASE_PAYOUT, expected=344.7)
    assert stats.score == 20 + 55 + 150 + 90 + 90
    assert stats.luck == pytest.approx(405 - 344.7)
    assert stats.red_on_click == 3
    assert (stats.followed, stats.judged) == (4, 5)


def test_missed_red_and_unknown_recommendations():
    steps = [_step("A1", Color.BLUE), _step("A2", Color.TEAL, "A3")]
    stats = game_stats(steps, BASE_PAYOUT, expected=None)
    assert stats.red_on_click is None
    assert stats.luck is None
    assert (stats.followed, stats.judged) == (0, 1)
