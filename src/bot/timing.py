"""Console lines for slow solves and a periodic heartbeat, to find out why the
first $oc or $oq reply after a quiet stretch can take minutes (Flow, 2026-10-15)."""

import logging
import time
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path

log = logging.getLogger("solver")

# Chosen 2026-10-15: well below the 2-minute game window, above a cached solve.
SLOW_SOLVE_SECONDS = 1.0


def payout_label(payouts: Mapping, red) -> str:
    """Names a payout table without IDs: red pays 150 at base values, more with
    a sphere bonus, and 500 when a $oq rainbow replaces it."""
    return f"red pays {payouts[red]}"


@asynccontextmanager
async def timed_solve(name: str, lock, new: bool, label: str, cached: int):
    """Hold `lock` for one solve and log it when it was slow or built a solver.
    `new` and `cached` describe the solver cache when the solve was asked for."""
    asked = time.perf_counter()
    async with lock:
        started = time.perf_counter()
        yield
    done = time.perf_counter()
    waited, computed = started - asked, done - started
    if new or waited + computed >= SLOW_SOLVE_SECONDS:
        log.info(
            "solve %s: waited %.1fs in the queue, %.1fs computing, %s solver, "
            "%s, %d cached",
            name,
            waited,
            computed,
            "new" if new else "cached",
            label,
            cached,
        )


def resident_mb() -> float | None:
    """This process's memory in RAM right now, on Linux; None elsewhere."""
    statm = Path("/proc/self/statm")
    if not statm.exists():
        return None
    pages = int(statm.read_text().split()[1])
    return pages * 4096 / 2**20
