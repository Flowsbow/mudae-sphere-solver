import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import TypeVar

from src.bot.settings import write_json_atomic
from src.solver.board import N_CELLS, Color
from src.solver.modes import oc, oq

FILE_VERSION = 1
OC_LABELS = tuple(color.name for color in Color)
# The 4th purple is red or, sometimes, rainbow (Flow, 2026-10-05).
OQ_LABELS = (*OC_LABELS[:5], "PURPLE", "RED", "RAINBOW")
T = TypeVar("T")


class StatsFileError(ValueError):
    pass


@dataclass
class Running:
    """A count, a sum and a sum of squares: enough for a mean and its error."""

    n: int = 0
    total: float = 0.0
    squares: float = 0.0

    def add(self, x: float) -> None:
        self.n += 1
        self.total += x
        self.squares += x * x

    @property
    def mean(self) -> float | None:
        return self.total / self.n if self.n else None

    @property
    def standard_error(self) -> float | None:
        if self.n < 2:
            return None
        variance = (self.squares - self.total**2 / self.n) / (self.n - 1)
        return math.sqrt(max(variance, 0.0) / self.n)


@dataclass(frozen=True)
class OcResult:
    """One finished auto-read $oc game, checked against Mudae's rewards."""

    clicks: tuple[str, ...]  # OC_LABELS, in click order
    spheres_gained: int  # Mudae's own +N amounts, bonuses and multipliers included
    picks: int  # clicks the solver had a pick for
    picks_followed: int
    score: float  # in the solver's payout table for this player
    expected: float | None  # the solver's prediction, same table
    red_cell: int

    @property
    def followed_every_pick(self) -> bool:
        return (
            self.expected is not None
            and len(self.clicks) == oc.CLICKS
            and self.picks == self.picks_followed == oc.CLICKS
        )


@dataclass(frozen=True)
class OqResult:
    """One finished auto-read $oq game, checked against Mudae's rewards."""

    clicks: tuple[str, ...]  # OQ_LABELS, in click order
    spheres_gained: int
    picks: int
    picks_followed: int
    score: float  # in the solver's payout table; a rainbow counts as red
    best: float  # best with hindsight, same table
    expected: float | None  # the solver's prediction once exact search took over

    @property
    def followed_every_pick(self) -> bool:
        paid = sum(label != "PURPLE" for label in self.clicks)
        return paid == oq.CLICKS and self.picks == self.picks_followed == len(
            self.clicks
        )


def _counter(labels: tuple[str, ...]) -> Callable[[], dict[str, int]]:
    return lambda: dict.fromkeys(labels, 0)


@dataclass
class OcTotals:
    games: int = 0
    spheres_gained: int = 0
    clicked: dict[str, int] = field(default_factory=_counter(OC_LABELS))
    picks: int = 0
    picks_followed: int = 0
    followed_score: Running = field(default_factory=Running)
    followed_luck: Running = field(default_factory=Running)
    followed_red_found: int = 0
    red_cells: list[int] = field(default_factory=lambda: [0] * N_CELLS)

    def add(self, result: OcResult) -> None:
        self.games += 1
        self.spheres_gained += result.spheres_gained
        for label in result.clicks:
            self.clicked[label] += 1
        self.picks += result.picks
        self.picks_followed += result.picks_followed
        self.red_cells[result.red_cell] += 1
        if result.followed_every_pick:
            self.followed_score.add(result.score)
            self.followed_luck.add(result.score - result.expected)
            self.followed_red_found += "RED" in result.clicks

    def check(self) -> None:
        if tuple(self.clicked) != OC_LABELS or len(self.red_cells) != N_CELLS:
            raise ValueError("$oc totals have the wrong colors or cells")


@dataclass
class OqTotals:
    games: int = 0
    spheres_gained: int = 0
    clicked: dict[str, int] = field(default_factory=_counter(OQ_LABELS))
    picks: int = 0
    picks_followed: int = 0
    followed_share: Running = field(default_factory=Running)  # score / best
    followed_luck: Running = field(default_factory=Running)  # score - expected

    def add(self, result: OqResult) -> None:
        self.games += 1
        self.spheres_gained += result.spheres_gained
        for label in result.clicks:
            self.clicked[label] += 1
        self.picks += result.picks
        self.picks_followed += result.picks_followed
        if result.followed_every_pick:
            self.followed_share.add(result.score / result.best)
            if result.expected is not None:
                self.followed_luck.add(result.score - result.expected)

    def check(self) -> None:
        if tuple(self.clicked) != OQ_LABELS:
            raise ValueError("$oq totals have the wrong colors")


def _from_dict(cls: type[T], data: dict) -> T:
    totals = cls(
        **{
            f.name: Running(**data[f.name]) if f.type is Running else data[f.name]
            for f in fields(cls)
        }
    )
    totals.check()
    return totals


@dataclass
class Totals:
    oc: OcTotals = field(default_factory=OcTotals)
    oq: OqTotals = field(default_factory=OqTotals)

    def add(self, result: OcResult | OqResult) -> None:
        if isinstance(result, OcResult):
            self.oc.add(result)
        else:
            self.oq.add(result)

    @classmethod
    def from_dict(cls, data: dict) -> "Totals":
        return cls(_from_dict(OcTotals, data["oc"]), _from_dict(OqTotals, data["oq"]))


def _load(path: Path | None, parse: Callable[[dict], T]) -> T | None:
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != FILE_VERSION:
            raise ValueError(f"unknown version {data.get('version')!r}")
        return parse(data)
    except (ValueError, TypeError, KeyError, AttributeError) as err:
        raise StatsFileError(
            f"{path} is not a valid stats file ({err!r}). Fix it or delete it."
        ) from err


def _players(data: dict) -> dict[int, Totals]:
    return {
        int(user): Totals.from_dict(entry) for user, entry in data["players"].items()
    }


class StatsStore:
    """Global totals (no IDs at all) and per-player totals keyed by Discord ID."""

    def __init__(
        self, global_path: Path | None = None, players_path: Path | None = None
    ) -> None:
        self.global_path = global_path
        self.players_path = players_path
        self.all = _load(global_path, Totals.from_dict) or Totals()
        self.players = _load(players_path, _players) or {}

    def record(self, user_id: int, result: OcResult | OqResult) -> None:
        self.all.add(result)
        self.players.setdefault(user_id, Totals()).add(result)
        self.save()

    def delete_player(self, user_id: int) -> bool:
        if self.players.pop(user_id, None) is None:
            return False
        self.save()
        return True

    def save(self) -> None:
        if self.global_path is not None:
            write_json_atomic(
                self.global_path, {"version": FILE_VERSION, **asdict(self.all)}
            )
        if self.players_path is not None:
            players = {
                str(user): asdict(totals)
                for user, totals in sorted(self.players.items())
            }
            write_json_atomic(
                self.players_path, {"version": FILE_VERSION, "players": players}
            )
