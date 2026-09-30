from collections.abc import Mapping
from dataclasses import dataclass

from src.solver.board import Color


@dataclass(frozen=True)
class Step:
    cell: int
    color: Color
    recommended: int | None


@dataclass(frozen=True)
class GameStats:
    score: float
    expected: float | None
    steps: tuple[Step, ...]
    red_on_click: int | None
    followed: int
    judged: int

    @property
    def luck(self) -> float | None:
        return None if self.expected is None else self.score - self.expected


def game_stats(
    steps: list[Step], payouts: Mapping[Color, float], expected: float | None
) -> GameStats:
    score = sum(payouts[step.color] for step in steps)
    red_on_click = next(
        (i for i, step in enumerate(steps, 1) if step.color is Color.RED), None
    )
    judged = [step for step in steps if step.recommended is not None]
    followed = sum(step.cell == step.recommended for step in judged)
    return GameStats(score, expected, tuple(steps), red_on_click, followed, len(judged))
