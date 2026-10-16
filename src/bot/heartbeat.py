import asyncio
import logging
import time

from src.bot.commands import OcService
from src.bot.oq import OqService
from src.bot.timing import resident_mb
from src.solver.board import BoardState, Color
from src.solver.modes.oc import BASE_PAYOUT

log = logging.getLogger("solver")

# Chosen 2026-10-15: often enough to show in the console what the bot was doing
# before a slow reply, rarely enough not to flood it.
HEARTBEAT_SECONDS = 300


async def beat(oc: OcService, oq: OqService) -> str:
    """Re-solve the fresh $oc board for every cached payout table, rebuilding the
    base one if it was pushed out, and describe the caches.

    A cached solve takes milliseconds (about 0.03 s, 2026-10-15), so a slow
    heartbeat points at the machine (memory swapped out, CPU throttled) rather
    than the solver; timed_solve logs any touch over a second."""
    started = time.perf_counter()
    rebuilt = OcService._key(BASE_PAYOUT) not in oc.solvers
    tables = [dict(zip(Color, key, strict=True)) for key in oc.solvers]
    if rebuilt:
        tables.append(BASE_PAYOUT)
    for payouts in tables:
        await oc.analyze(BoardState(), payouts)
    took = time.perf_counter() - started
    mb = resident_mb()
    memory = "" if mb is None else f", {mb:.0f} MB in RAM"
    return (
        f"heartbeat: {len(tables)} $oc solvers touched in {took:.2f}s"
        f"{' (rebuilt the base one)' if rebuilt else ''}, {len(oq.solvers)} $oq "
        f"solvers cached, {len(set(oc.bonus_for.values()))} different sphere "
        f"bonuses saved{memory}"
    )


async def run_heartbeat(
    oc: OcService, oq: OqService, interval: float = HEARTBEAT_SECONDS
) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            log.info(await beat(oc, oq))
        except Exception:
            log.exception("heartbeat failed")
