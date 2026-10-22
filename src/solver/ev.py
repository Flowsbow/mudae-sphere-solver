import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from src.solver.board import N_CELLS, BoardState, Color
from src.solver.payouts import affine_fit

N_COLORS = len(Color)
TIE_TOLERANCE = 1e-9  # floating-point noise; far below a 1-point payout difference
# Bump when the saved cache's layout changes.
MEMO_FORMAT = 1


class InconsistentBoardError(ValueError):
    pass


@dataclass(frozen=True)
class Analysis:
    clicks_left: int
    best: int | None
    value: float
    cell_value: dict[int, float]
    color_probs: dict[int, dict[Color, float]]

    @property
    def tied(self) -> frozenset[int]:
        """Every cell exactly as good as the best one."""
        if self.best is None:
            return frozenset()
        top = self.cell_value[self.best]
        return frozenset(
            c for c, v in self.cell_value.items() if v >= top - TIE_TOLERANCE
        )

    def for_payouts(
        self, base: Mapping[Color, float], payouts: Mapping[Color, float]
    ) -> "Analysis":
        """This analysis, made with `base` payouts, in a sphere bonus's payouts.

        The next click's value is exact: it only needs the color odds. The rest
        of the game is converted with the a x base + b fit of the payouts, which
        a bonus matches up to Mudae's rounding. The picks stay the base ones:
        sim/verify_oc_bonus.py (2026-10-22) followed them through every board for 9
        bonuses: at every decision they were as good as a solver built for the
        bonus payouts, and the value shown was within 0.33 spheres of the true
        expected total."""
        if payouts == base:
            return self
        a, b = affine_fit(base, payouts)
        later = b * (self.clicks_left - 1)

        def convert(cell: int, value: float) -> float:
            odds = self.color_probs[cell]
            now_base = sum(p * base[color] for color, p in odds.items())
            now = sum(p * payouts[color] for color, p in odds.items())
            return now + a * (value - now_base) + later

        cell_value = {c: convert(c, v) for c, v in self.cell_value.items()}
        value = 0.0 if self.best is None else cell_value[self.best]
        return replace(self, value=value, cell_value=cell_value)


class Solver:
    def __init__(
        self,
        layouts: np.ndarray,
        weights: np.ndarray,
        payouts: Mapping[Color, float],
        clicks: int,
        symmetries: tuple[tuple[int, ...], ...] = (),
    ) -> None:
        self.clicks = clicks
        self.symmetries = symmetries
        self.layouts = layouts
        self.weights = weights
        self.pay = np.array([payouts[Color(k)] for k in range(N_COLORS)], dtype=float)
        self.cell_pay = self.pay[layouts]
        self.onehot = (layouts[:, :, None] == np.arange(N_COLORS)).reshape(
            len(layouts), N_CELLS * N_COLORS
        )
        self._memo: dict[tuple[int, ...], float] = {}

    @property
    def cached_positions(self) -> int:
        return len(self._memo)

    def fingerprint(self) -> str:
        """Changes whenever the boards, their odds, payouts, clicks or symmetries
        do, so a saved cache from older rules is never loaded."""
        digest = hashlib.sha256(f"{MEMO_FORMAT} {self.clicks}".encode())
        for array in (self.layouts, self.weights, self.pay):
            digest.update(np.ascontiguousarray(array).tobytes())
        digest.update(repr(self.symmetries).encode())
        return digest.hexdigest()

    def save_memo(self, path: Path) -> None:
        """Write every cached position to `path`, replacing it in one step."""
        keys = np.array(list(self._memo), dtype=np.int8).reshape(-1, N_CELLS)
        values = np.fromiter(self._memo.values(), dtype=float, count=len(keys))
        partial = path.with_name(path.name + ".partial")
        with partial.open("wb") as file:
            np.savez(file, keys=keys, values=values, fingerprint=self.fingerprint())
        os.replace(partial, path)

    def load_memo(self, path: Path) -> bool:
        """Load positions saved by save_memo. False, loading nothing, when the
        file is missing, unreadable or from different rules."""
        try:
            with np.load(path, allow_pickle=False) as saved:
                if str(saved["fingerprint"]) != self.fingerprint():
                    return False
                keys, values = saved["keys"], saved["values"]
        except (OSError, ValueError, KeyError):
            return False
        if keys.ndim != 2 or keys.shape[1] != N_CELLS or len(keys) != len(values):
            return False
        self._memo = dict(zip(map(tuple, keys.tolist()), values.tolist(), strict=True))
        return True

    def analyze(self, state: BoardState) -> Analysis:
        clicks_left = self.clicks - state.n_revealed
        if clicks_left < 0:
            raise InconsistentBoardError(
                f"{state.n_revealed} cells revealed but a game has only {self.clicks}"
            )
        idx = self._consistent(state)
        w = self.weights[idx]
        total = w.sum()
        color_mass = (self.onehot[idx].T @ w).reshape(N_CELLS, N_COLORS) / total
        open_cells = [c for c in range(N_CELLS) if state.revealed[c] is None]
        color_probs = {
            c: {Color(k): float(color_mass[c, k]) for k in range(N_COLORS)}
            for c in open_cells
        }
        if clicks_left == 0:
            return Analysis(0, None, 0.0, {}, color_probs)
        values = self._cell_values(state, idx, clicks_left)
        cell_value = {c: float(values[c]) for c in open_cells}
        top = max(values[c] for c in open_cells)
        best = min(c for c in open_cells if values[c] >= top - TIE_TOLERANCE)
        return Analysis(clicks_left, best, float(values[best]), cell_value, color_probs)

    def _consistent(self, state: BoardState) -> np.ndarray:
        mask = np.ones(len(self.layouts), dtype=bool)
        for c, color in enumerate(state.revealed):
            if color is not None:
                mask &= self.layouts[:, c] == color
        idx = np.flatnonzero(mask)
        if len(idx) == 0:
            raise InconsistentBoardError("no legal board matches these reveals")
        return idx

    def _value(self, state: BoardState, idx: np.ndarray, clicks_left: int) -> float:
        if clicks_left == 0:
            return 0.0
        key = self._canonical(state)
        if key not in self._memo:
            self._memo[key] = float(
                np.nanmax(self._cell_values(state, idx, clicks_left))
            )
        return self._memo[key]

    def _canonical(self, state: BoardState) -> tuple[int, ...]:
        codes = [-1 if color is None else int(color) for color in state.revealed]
        if not self.symmetries:
            return tuple(codes)
        return min(tuple(codes[i] for i in perm) for perm in self.symmetries)

    def _cell_values(
        self, state: BoardState, idx: np.ndarray, clicks_left: int
    ) -> np.ndarray:
        is_open = np.array([color is None for color in state.revealed])
        w = self.weights[idx]
        total = w.sum()
        values = np.full(N_CELLS, np.nan)

        if clicks_left == 1:
            values[is_open] = (w @ self.cell_pay[idx])[is_open] / total
            return values

        weighted = self.onehot[idx] * w[:, None]
        mass = weighted.sum(axis=0).reshape(N_CELLS, N_COLORS)
        immediate = mass @ self.pay

        if clicks_left == 2:
            follow = (weighted.T @ self.cell_pay[idx]).reshape(
                N_CELLS, N_COLORS, N_CELLS
            )
            follow[:, :, ~is_open] = -np.inf
            follow[np.arange(N_CELLS), :, np.arange(N_CELLS)] = -np.inf
            best_follow = np.where(mass > 0, follow.max(axis=2), 0.0).sum(axis=1)
            values[is_open] = (immediate + best_follow)[is_open] / total
            return values

        for c in np.flatnonzero(is_open):
            column = self.layouts[idx, c]
            future = 0.0
            for k in np.flatnonzero(mass[c] > 0):
                sub = idx[column == k]
                child = state.reveal(int(c), Color(int(k)))
                future += mass[c, k] * self._value(child, sub, clicks_left - 1)
            values[c] = (immediate[c] + future) / total
        return values
