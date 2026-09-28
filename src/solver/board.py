from dataclasses import dataclass
from enum import IntEnum
from typing import Self

SIZE = 5  # $oc board is 5x5: Flow, observed, 2026-09-26
N_CELLS = SIZE * SIZE
# Naming chosen 2026-09-26: rows A-E top to bottom, columns 1-5 left to right.
ROW_NAMES = "ABCDE"
COL_NAMES = "12345"


class Color(IntEnum):
    BLUE = 0
    TEAL = 1
    GREEN = 2
    YELLOW = 3
    ORANGE = 4
    RED = 5


COLOR_LETTERS = {
    "B": Color.BLUE,
    "T": Color.TEAL,
    "G": Color.GREEN,
    "Y": Color.YELLOW,
    "O": Color.ORANGE,
    "R": Color.RED,
}


class BoardInputError(ValueError):
    pass


def cell_index(name: str) -> int:
    name = name.strip().upper()
    if len(name) != 2 or name[0] not in ROW_NAMES or name[1] not in COL_NAMES:
        raise BoardInputError(f"{name!r} is not a cell; use A1 to E5")
    return ROW_NAMES.index(name[0]) * SIZE + COL_NAMES.index(name[1])


def cell_name(index: int) -> str:
    row, col = divmod(index, SIZE)
    return ROW_NAMES[row] + COL_NAMES[col]


@dataclass(frozen=True)
class BoardState:
    revealed: tuple[Color | None, ...] = (None,) * N_CELLS

    def __post_init__(self) -> None:
        if len(self.revealed) != N_CELLS:
            raise ValueError(f"expected {N_CELLS} cells, got {len(self.revealed)}")

    @classmethod
    def parse(cls, text: str) -> Self:
        cells: list[Color | None] = [None] * N_CELLS
        for token in text.replace(",", " ").split():
            if len(token) != 3:
                raise BoardInputError(
                    f"{token!r}: expected a cell then a color, like C4T"
                )
            index = cell_index(token[:2])
            letter = token[2].upper()
            if letter not in COLOR_LETTERS:
                raise BoardInputError(
                    f"{token!r}: color must be one of {' '.join(COLOR_LETTERS)}"
                )
            if cells[index] is not None:
                raise BoardInputError(f"{cell_name(index)} is listed twice")
            cells[index] = COLOR_LETTERS[letter]
        return cls(tuple(cells))

    @property
    def n_revealed(self) -> int:
        return sum(color is not None for color in self.revealed)

    def reveal(self, index: int, color: Color) -> Self:
        if self.revealed[index] is not None:
            raise BoardInputError(f"{cell_name(index)} is already revealed")
        cells = list(self.revealed)
        cells[index] = color
        return type(self)(tuple(cells))
