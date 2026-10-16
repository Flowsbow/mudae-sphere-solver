"""A simple rule for $oh, not an exact search.

Spheres stay on the board until clicked, so the question each click is whether a
covered tile is worth more than the weakest sphere you'd still collect:

1. A visible purple is free: click it.
2. With c paid clicks left, you'll end up collecting the best c visible spheres
   anyway. A covered tile is worth clicking if its average value beats the c-th
   best of them, the one it would push out.
3. Otherwise collect a visible sphere: dark first (Flow's rule; it's random, so
   finding out what it becomes early can't hurt), then the most valuable.

Covered tiles are all valued the same: the rates in src/solver/modes/oh.py, plus
the $oc prize spread evenly over them while it's unfound (Flow's rule, 2026-10-08).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from src.solver.board import N_CELLS, BoardInputError, cell_name
from src.solver.modes.oh import (
    CLICKS,
    COLORS,
    DARK,
    PRIZE,
    PRIZE_CHANCE,
    PURPLE,
    RATES,
)

Cells = tuple[str | None, ...]  # a sphere letter, or None for a covered tile


@dataclass(frozen=True)
class OhBoard:
    cells: Cells = (None,) * N_CELLS
    clicked: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if len(self.cells) != N_CELLS:
            raise BoardInputError(f"expected {N_CELLS} cells, got {len(self.cells)}")
        for cell, letter in enumerate(self.cells):
            if letter is not None and letter not in COLORS + PRIZE:
                raise BoardInputError(f"{cell_name(cell)}: unknown sphere {letter!r}")
            if letter == PRIZE and cell not in self.clicked:
                raise BoardInputError("the $oc prize only shows once it's clicked")
        for cell in self.clicked:
            if self.cells[cell] is None:
                raise BoardInputError(f"{cell_name(cell)} is clicked but covered")
        if self.cells.count(PRIZE) > 1:
            raise BoardInputError("a board has at most one $oc prize")
        if self.clicks_used > CLICKS:
            raise BoardInputError(f"a game has only {CLICKS} paid clicks")

    @property
    def clicks_used(self) -> int:
        return sum(self.cells[cell] != PURPLE for cell in self.clicked)

    @property
    def clicks_left(self) -> int:
        return CLICKS - self.clicks_used

    @property
    def covered(self) -> list[int]:
        return [c for c in range(N_CELLS) if self.cells[c] is None]

    @property
    def prize_found(self) -> bool:
        return PRIZE in self.cells


@dataclass(frozen=True)
class OhAdvice:
    clicks_left: int
    best: int | None
    reason: str | None  # "purple", "dark", "covered", "sphere"; None once over
    covered_value: float | None  # average for one covered tile; None if none left
    prize_chance: float  # chance a given covered tile holds the $oc prize
    # Spheres from clicking each cell: visible spheres not yet clicked, and the
    # average for covered tiles.
    cell_value: dict[int, float] = field(default_factory=dict)
    # The c-th best visible sphere, which a covered click would push out.
    weakest_kept: float = 0.0


def sphere_average(payouts: Mapping[str, float]) -> float:
    """Average spheres from a covered tile that isn't the $oc prize."""
    return sum(p * payouts[c] for c, p in RATES.items()) / sum(RATES.values())


def prize_chance(board: OhBoard) -> float:
    covered = len(board.covered)
    if board.prize_found or not covered:
        return 0.0
    return PRIZE_CHANCE / covered


def advise(board: OhBoard, payouts: Mapping[str, float], oc_value: float) -> OhAdvice:
    covered = board.covered
    chance = prize_chance(board)
    covered_value = (
        (1 - chance) * sphere_average(payouts) + chance * oc_value if covered else None
    )
    visible = {
        c: float(payouts[board.cells[c]])
        for c in range(N_CELLS)
        if board.cells[c] is not None and c not in board.clicked
    }
    cell_value = {**visible, **dict.fromkeys(covered, covered_value)}
    left = board.clicks_left
    if left == 0 or not cell_value:
        return OhAdvice(left, None, None, covered_value, chance, cell_value)

    purples = [c for c in visible if board.cells[c] == PURPLE]
    if purples:
        return OhAdvice(left, purples[0], "purple", covered_value, chance, cell_value)

    paid = sorted(
        (c for c in visible if board.cells[c] != PURPLE),
        key=lambda c: (-visible[c], c),
    )
    kept = paid[:left]
    weakest = visible[kept[-1]] if len(kept) == left else 0.0
    if covered and covered_value > weakest:
        return OhAdvice(
            left, covered[0], "covered", covered_value, chance, cell_value, weakest
        )
    darks = [c for c in kept if board.cells[c] == DARK]
    best, reason = (darks[0], "dark") if darks else (kept[0], "sphere")
    return OhAdvice(left, best, reason, covered_value, chance, cell_value, weakest)
