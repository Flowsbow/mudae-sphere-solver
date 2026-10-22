import asyncio
import logging

import numpy as np
import pytest

from src.bot.commands import OcService
from src.solver.board import BoardState, Color
from src.solver.ev import Solver
from src.solver.modes.oc import BASE_PAYOUT, CLICKS, LAYOUTS, SYMMETRIES, prior
from src.solver.payouts import with_bonus

FLOW_BONUS = (6, 25)  # Flow's own, see src/solver/payouts.py


@pytest.fixture(scope="module")
def built():
    solver = Solver(LAYOUTS, prior(), BASE_PAYOUT, CLICKS, SYMMETRIES)
    solver.analyze(BoardState())
    return solver


def _fresh(payouts=BASE_PAYOUT):
    return Solver(LAYOUTS, prior(), payouts, CLICKS, SYMMETRIES)


def test_a_saved_solver_loads_with_the_same_answers(built, tmp_path):
    path = tmp_path / "oc_solver.npz"
    built.save_memo(path)
    loaded = _fresh()
    assert loaded.load_memo(path)
    assert loaded.cached_positions == built.cached_positions
    for board in ("", "D4R", "A1B B2T C4G"):
        state = BoardState.parse(board)
        assert loaded.analyze(state) == built.analyze(state)


def test_a_file_from_other_rules_is_not_loaded(built, tmp_path):
    path = tmp_path / "oc_solver.npz"
    built.save_memo(path)
    other = _fresh({**BASE_PAYOUT, Color.RED: 151})
    assert not other.load_memo(path)
    assert other.cached_positions == 0


def test_a_missing_or_broken_file_is_not_loaded(tmp_path):
    solver = _fresh()
    assert not solver.load_memo(tmp_path / "missing.npz")
    broken = tmp_path / "broken.npz"
    broken.write_bytes(b"not a cache")
    assert not solver.load_memo(broken)
    np.savez(tmp_path / "no_print.npz", keys=np.zeros((1, 25), np.int8))
    assert not solver.load_memo(tmp_path / "no_print.npz")


def test_warm_up_builds_and_saves_then_the_next_start_loads(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="solver")
    path = tmp_path / "oc_solver.npz"
    asyncio.run(OcService(solver_path=path).warm_up())
    assert path.exists() and not path.with_name(path.name + ".partial").exists()
    assert any(m.startswith("built the $oc solver") for m in caplog.messages)
    caplog.clear()
    restarted = OcService(solver_path=path)
    asyncio.run(restarted.warm_up())
    assert restarted.solver.cached_positions > 0
    assert any(m.startswith("loaded the $oc solver") for m in caplog.messages)


def test_bonus_players_share_the_base_solver():
    service = OcService()
    pay = with_bonus(BASE_PAYOUT, *FLOW_BONUS)
    state = BoardState.parse("D4R B2T")
    base = asyncio.run(service.analyze(state))
    bonus = asyncio.run(service.analyze(state, pay))
    assert bonus.best == base.best
    assert bonus.color_probs == base.color_probs
    assert bonus.value > base.value


def test_bonus_values_match_a_solver_built_for_them(built):
    # Within the 0.33 spheres sim/verify_oc_bonus.py found, 2026-10-22.
    pay = with_bonus(BASE_PAYOUT, *FLOW_BONUS)
    own = _fresh(pay)
    layout = LAYOUTS[1234]
    for cells in ((), (7,), (0, 18), (3, 11, 21), (1, 9, 16, 23)):
        state = BoardState()
        for cell in cells:
            state = state.reveal(cell, Color(int(layout[cell])))
        converted = built.analyze(state).for_payouts(BASE_PAYOUT, pay)
        exact = own.analyze(state)
        assert converted.best in exact.tied
        assert converted.value == pytest.approx(exact.value, abs=0.33)


def test_base_payouts_are_left_alone(built):
    analysis = built.analyze(BoardState.parse("D4R"))
    assert analysis.for_payouts(BASE_PAYOUT, dict(BASE_PAYOUT)) is analysis
