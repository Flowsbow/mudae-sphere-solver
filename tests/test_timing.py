import asyncio
import logging

import src.bot.timing as timing
from src.bot.timing import payout_label, timed_solve
from src.solver.board import Color
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


def test_late_delivery_is_measured_from_discords_timestamps(caplog):
    import datetime
    import time as clock

    from src.bot.auto import AutoGame, _late_by, _log_slow_reply
    from src.bot.rewards import DISCORD_EPOCH_MS

    now = datetime.datetime.now(datetime.UTC)
    edited = type("M", (), {"id": 1, "edited_at": now - datetime.timedelta(seconds=40)})
    assert 39 < _late_by(edited) < 42
    posted_ms = int(clock.time() * 1000) - 3000
    fresh = type("M", (), {"id": (posted_ms - DISCORD_EPOCH_MS) << 22})
    assert 2 < _late_by(fresh) < 5

    game = AutoGame(view=object(), reply=None, started=0, channel_id=1, server_id=None)
    caplog.set_level(logging.INFO, logger="solver")
    _log_slow_reply(game, "board", 0.5, clock.perf_counter())
    assert caplog.messages == []
    _log_slow_reply(game, "click", 40.2, clock.perf_counter())
    assert caplog.messages == [
        "slow reply $oc click: Discord delivered it 40.2s after Mudae posted it, "
        "then the bot took 0.0s to solve, draw and send"
    ]
    _log_slow_reply(None, "board", 99.0, clock.perf_counter())
    assert len(caplog.messages) == 1
