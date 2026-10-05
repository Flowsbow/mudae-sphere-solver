from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from src.solver.board import N_CELLS
from src.solver.ev import TIE_TOLERANCE, InconsistentBoardError
from src.solver.modes.oq import (
    CLICKS,
    N_PURPLE,
    PURPLE,
    PURPLES_FOR_RED,
    RED,
    RED_SHOWN,
)

HIDDEN = -1
COUNTS = range(5)  # 0-4 purple neighbors: blue, teal, green, yellow, orange
# Exact search costs 0.3 s with 2 paid clicks left, 5.7 s with 3 and 87 s with 4
# (measured 2026-09-30), so earlier clicks use the early-game rule instead.
EXACT_CLICKS = 3
# Positions kept between requests. About 320 bytes each (measured 2026-09-30),
# so at most about 0.3 GB.
MEMO_LIMIT = 1_000_000


@dataclass(frozen=True)
class OqAnalysis:
    clicks_left: int
    best: int | None
    exact: bool
    value: float | None  # expected spheres from here; only when exact
    cell_value: dict[int, float]  # only when exact
    purple_prob: dict[int, float]


def clicks_used(codes: tuple[int, ...]) -> int:
    return sum(1 for x in codes if 0 <= x <= RED)


class OqSolver:
    """Exact expected spheres for $oq, over every placement of the purples.

    `payouts` maps the codes 0-4 (purple counts), PURPLE and RED to spheres.
    """

    def __init__(
        self,
        layouts: np.ndarray,
        payouts: Mapping[int, float],
        clicks: int = CLICKS,
        symmetries: tuple[tuple[int, ...], ...] = (),
    ) -> None:
        self.layouts = layouts
        self.clicks = clicks
        self.symmetries = symmetries
        self.pay = np.zeros(RED_SHOWN + 1)
        for code, value in payouts.items():
            self.pay[code] = value
        self.is_purple = layouts == PURPLE
        self._memo: dict[tuple[int, ...], float] = {}

    def analyze(self, codes: tuple[int, ...]) -> OqAnalysis:
        clicks_left = self.clicks - clicks_used(codes)
        if clicks_left < 0:
            raise InconsistentBoardError(
                f"{clicks_used(codes)} paid clicks but a game has only {self.clicks}"
            )
        idx = self.consistent(codes)
        hidden = [c for c in range(N_CELLS) if codes[c] == HIDDEN]
        mass = self.is_purple[idx].mean(axis=0)
        purple_prob = {c: float(mass[c]) for c in hidden}
        if clicks_left == 0:
            return OqAnalysis(0, None, True, 0.0, {}, purple_prob)
        if clicks_left > EXACT_CLICKS and len(idx) > 1:
            best = self.early_pick(codes, idx)
            return OqAnalysis(clicks_left, best, False, None, {}, purple_prob)
        if len(self._memo) > MEMO_LIMIT:
            self._memo.clear()
        values = self._cell_values(codes, idx)
        top = max(values.values())
        best = min(c for c, v in values.items() if v >= top - TIE_TOLERANCE)
        return OqAnalysis(clicks_left, best, True, top, values, purple_prob)

    def early_pick(self, codes: tuple[int, ...], idx: np.ndarray) -> int:
        """The cell most likely to be purple; ties go to the higher expected payout.

        Chosen by simulation over alternatives: see sim/compare_oq_heuristics.py.
        """
        purple = self.is_purple[idx].mean(axis=0)
        pay = self.pay[np.where(self.is_purple[idx], 0, self.layouts[idx])]
        pay = np.where(self.is_purple[idx], 0.0, pay).mean(axis=0)
        hidden = [c for c in range(N_CELLS) if codes[c] == HIDDEN]
        return max(hidden, key=lambda c: (purple[c], pay[c], -c))

    def consistent(self, codes: tuple[int, ...]) -> np.ndarray:
        mask = np.ones(len(self.layouts), dtype=bool)
        for c, x in enumerate(codes):
            if x == HIDDEN:
                continue
            want = PURPLE if x in (PURPLE, RED, RED_SHOWN) else x
            mask &= self.layouts[:, c] == want
        idx = np.flatnonzero(mask)
        if len(idx) == 0:
            raise InconsistentBoardError("no placement of the purples fits this board")
        return idx

    def value(self, codes: tuple[int, ...], idx: np.ndarray) -> float:
        if clicks_used(codes) >= self.clicks:
            return 0.0
        if len(idx) == 1:
            return self._known_value(codes, self.layouts[idx[0]])
        key = self._canonical(codes)
        if key not in self._memo:
            self._memo[key] = max(self._cell_values(codes, idx).values())
        return self._memo[key]

    def _known_value(self, codes: tuple[int, ...], layout: np.ndarray) -> float:
        """Best total once the purples' places are certain: no more guessing."""
        found = sum(1 for x in codes if x in (PURPLE, RED, RED_SHOWN))
        free = 0.0
        options = []
        if found < N_PURPLE and not any(x in (RED, RED_SHOWN) for x in codes):
            free = (PURPLES_FOR_RED - found) * self.pay[PURPLE]
            options.append(self.pay[RED])
        options += [self.pay[RED] for x in codes if x == RED_SHOWN]
        options += [
            self.pay[layout[c]]
            for c in range(N_CELLS)
            if codes[c] == HIDDEN and layout[c] != PURPLE
        ]
        k = self.clicks - clicks_used(codes)
        return free + float(sum(sorted(options, reverse=True)[:k]))

    def _canonical(self, codes: tuple[int, ...]) -> tuple[int, ...]:
        if not self.symmetries:
            return codes
        return min(tuple(codes[i] for i in perm) for perm in self.symmetries)

    def _cell_values(self, codes: tuple[int, ...], idx: np.ndarray) -> dict[int, float]:
        found = sum(1 for x in codes if x == PURPLE)
        values = {}
        for c in range(N_CELLS):
            if codes[c] == RED_SHOWN:
                child = _set(codes, c, RED)
                values[c] = self.pay[RED] + self.value(child, idx)
                continue
            if codes[c] != HIDDEN:
                continue
            column = self.layouts[idx, c]
            total = 0.0
            for k in COUNTS:
                sub = idx[column == k]
                if len(sub):
                    child = _set(codes, c, k)
                    total += len(sub) * (self.pay[k] + self.value(child, sub))
            sub = idx[column == PURPLE]
            if len(sub):
                child = _set(codes, c, PURPLE)
                if found + 1 < PURPLES_FOR_RED:
                    total += len(sub) * (self.pay[PURPLE] + self.value(child, sub))
                else:
                    total += self._reveal_red(child, sub)
            values[c] = total / len(idx)
        return values

    def _reveal_red(self, codes: tuple[int, ...], idx: np.ndarray) -> float:
        """The 3rd purple was just found: the game shows where the 4th is."""
        known = [c for c, x in enumerate(codes) if x == PURPLE]
        rest = self.is_purple[idx].copy()
        rest[:, known] = False
        red_cell = rest.argmax(axis=1)
        total = 0.0
        for r in np.unique(red_cell):
            sub = idx[red_cell == r]
            child = _set(codes, int(r), RED_SHOWN)
            total += len(sub) * (self.pay[PURPLE] + self.value(child, sub))
        return total


def _set(codes: tuple[int, ...], cell: int, code: int) -> tuple[int, ...]:
    return codes[:cell] + (code,) + codes[cell + 1 :]
