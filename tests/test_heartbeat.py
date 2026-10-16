import asyncio
import logging

import pytest

import src.bot.heartbeat as heartbeat_module
import src.bot.timing as timing
from src.bot.commands import OcService
from src.bot.heartbeat import beat, run_heartbeat
from src.bot.oq import OqService
from src.bot.timing import payout_label, timed_solve
from src.solver.board import BoardState, Color
from src.solver.modes.oc import BASE_PAYOUT


async def _solve(lock, new, seconds=0.0):
    async with timed_solve("$oc", lock, new, "red pays 150", 3):
        await asyncio.sleep(seconds)


def test_new_solver_is_logged_even_when_fast(caplog):
    caplog.set_level(logging.INFO, logger="solver")
    asyncio.run(_solve(asyncio.Lock(), new=True))
    (line,) = caplog.messages
    assert line.startswith("solve $oc: waited 0.0s in the queue")
    assert "new solver, red pays 150, 3 cached" in line


def test_fast_cached_solve_is_not_logged(caplog):
    caplog.set_level(logging.INFO, logger="solver")
    asyncio.run(_solve(asyncio.Lock(), new=False))
    assert caplog.messages == []


def test_slow_cached_solve_is_logged(caplog, monkeypatch):
    monkeypatch.setattr(timing, "SLOW_SOLVE_SECONDS", 0.01)
    caplog.set_level(logging.INFO, logger="solver")
    asyncio.run(_solve(asyncio.Lock(), new=False, seconds=0.02))
    assert "cached solver" in caplog.messages[0]


def test_time_waiting_for_the_queue_is_counted(caplog, monkeypatch):
    monkeypatch.setattr(timing, "SLOW_SOLVE_SECONDS", 0.15)
    caplog.set_level(logging.INFO, logger="solver")

    async def both():
        lock = asyncio.Lock()
        await asyncio.gather(_solve(lock, False, 0.1), _solve(lock, False, 0.1))

    asyncio.run(both())
    (line,) = caplog.messages  # only the second waited long enough to be slow
    assert line.startswith("solve $oc: waited 0.1s in the queue")


def test_payout_label_names_no_ids():
    assert payout_label(BASE_PAYOUT, Color.RED) == "red pays 150"


@pytest.fixture(scope="module")
def warm():
    service = OcService()
    return service, asyncio.run(beat(service, OqService(service)))


def test_heartbeat_rebuilds_a_missing_base_solver(warm):
    service, line = warm
    assert "1 $oc solvers touched" in line
    assert "(rebuilt the base one)" in line
    assert OcService._key(BASE_PAYOUT) in service.solvers


def test_heartbeat_touch_of_a_cached_solver_is_fast(warm):
    service, _ = warm
    line = asyncio.run(beat(service, OqService(service)))
    assert "rebuilt" not in line
    seconds = float(line.split(" touched in ")[1].split("s")[0])
    assert seconds < 1.0
    assert "0 $oq solvers cached, 0 different sphere bonuses saved" in line


def test_heartbeat_counts_distinct_saved_bonuses(warm):
    service, _ = warm
    service.bonus_for = {(1, None): (6, 25), (2, 9): (6, 25), (3, 9): (0, 10)}
    try:
        line = asyncio.run(beat(service, OqService(service)))
    finally:
        service.bonus_for = {}
    assert "2 different sphere bonuses saved" in line


def test_cached_tables_round_trip_to_payouts(warm):
    service, _ = warm
    (key,) = service.solvers
    assert dict(zip(Color, key, strict=True)) == BASE_PAYOUT
    assert service._key(BASE_PAYOUT) == key
    assert asyncio.run(service.analyze(BoardState())).best is not None


def test_a_failed_heartbeat_is_logged_and_the_next_one_still_runs(caplog, monkeypatch):
    calls = []

    async def flaky(oc, oq):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        if len(calls) == 3:
            raise asyncio.CancelledError
        return "ok"

    monkeypatch.setattr(heartbeat_module, "beat", flaky)
    caplog.set_level(logging.INFO, logger="solver")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_heartbeat(None, None, interval=0))
    assert caplog.messages[:2] == ["heartbeat failed", "ok"]
