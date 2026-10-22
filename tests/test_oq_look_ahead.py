import asyncio
import threading
import time

import pytest

from src.bot.commands import OcService
from src.bot.oq import OqService
from src.solver.modes.oc import SYMMETRIES
from src.solver.modes.oq import BASE_PAYOUT, LAYOUTS
from src.solver.oq_board import parse_board
from src.solver.oq_ev import EXACT_CLICKS, OqAnalysis, OqSolver, SearchStopped

FOUR_LEFT = "A1T A5T B2T A4P C5P"  # 3 paid clicks used of 7
THREE_LEFT = "A1T A5T B2T B4G A4P C5P"


def _solver():
    return OqSolver(LAYOUTS, BASE_PAYOUT, symmetries=SYMMETRIES)


def test_the_next_boards_needing_a_search_come_likeliest_first():
    solver = _solver()
    codes = parse_board(FOUR_LEFT)
    best = solver.analyze(codes).best
    boards = solver.next_exact_positions(codes, best)
    assert boards
    sizes = [len(solver.consistent(b)) for b in boards]
    assert sizes == sorted(sizes, reverse=True)
    assert all(
        solver.clicks - sum(0 <= x <= 5 for x in b) == EXACT_CLICKS for b in boards
    )
    assert solver.next_exact_positions(parse_board(THREE_LEFT), 0) == []


class _StopsPartway(OqSolver):
    def __init__(self, after):
        super().__init__(LAYOUTS, BASE_PAYOUT, symmetries=SYMMETRIES)
        self.calls, self.after = 0, after

    def value(self, codes, idx):
        self.calls += 1
        if self.calls == self.after:
            self.stop_requested = True
        return super().value(codes, idx)


def test_a_search_stopped_partway_keeps_a_cache_that_gives_the_same_answers():
    solver = _StopsPartway(after=2000)
    codes = parse_board(THREE_LEFT)
    with pytest.raises(SearchStopped):
        solver.analyze(codes)
    assert solver._memo  # some positions were finished before the stop
    solver.stop_requested = False
    assert solver.analyze(codes) == _solver().analyze(codes)


def test_the_look_ahead_fills_the_cache_for_the_next_board():
    service = OqService(OcService())
    codes = parse_board(FOUR_LEFT)

    async def play():
        analysis = await service.analyze(codes)
        assert service.look_ahead is not None
        await service.look_ahead
        solver = service.solvers[service._key(BASE_PAYOUT)]
        (likeliest, *_) = solver.next_exact_positions(codes, analysis.best)
        started = time.perf_counter()
        warm = await service.analyze(likeliest)
        return likeliest, warm, time.perf_counter() - started

    board, warm, seconds = asyncio.run(play())
    assert warm == _solver().analyze(board)
    assert seconds < 0.5


class _SlowSolver(OqSolver):
    """Searching LONG takes until stopped (or 2 s); anything else is instant."""

    LONG = parse_board(THREE_LEFT)

    def __init__(self):
        super().__init__(LAYOUTS, BASE_PAYOUT, symmetries=SYMMETRIES)
        self.started = threading.Event()

    def analyze(self, codes):
        if codes == self.LONG:
            self.started.set()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if self.stop_requested:
                    raise SearchStopped
                time.sleep(0.01)
        return OqAnalysis(3, 0, True, 0.0, {}, {}, {})


def _with_slow_look_ahead():
    service = OqService(OcService())
    solver = _SlowSolver()
    service.solvers[service._key(BASE_PAYOUT)] = solver
    service.look_ahead_cancelled = False
    service.look_ahead = asyncio.create_task(
        service._look_ahead(solver, [_SlowSolver.LONG])
    )
    return service, solver


def test_a_real_request_stops_the_look_ahead_at_once():
    async def play():
        service, solver = _with_slow_look_ahead()
        await asyncio.to_thread(solver.started.wait)
        started = time.perf_counter()
        await service.analyze(parse_board(FOUR_LEFT))
        return service, solver, time.perf_counter() - started

    service, solver, seconds = asyncio.run(play())
    assert seconds < 1
    assert service.look_ahead.done() and service.searching is None
    assert not solver.stop_requested


def test_asking_for_the_board_being_searched_lets_it_finish():
    async def play():
        service, solver = _with_slow_look_ahead()
        await asyncio.to_thread(solver.started.wait)
        started = time.perf_counter()
        await service.analyze(_SlowSolver.LONG)
        return time.perf_counter() - started

    assert asyncio.run(play()) > 1.5
