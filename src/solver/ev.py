from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from src.solver.board import N_CELLS, BoardState, Color

N_COLORS = len(Color)
TIE_TOLERANCE = 1e-9  # floating-point noise; far below a 1-point payout difference


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
