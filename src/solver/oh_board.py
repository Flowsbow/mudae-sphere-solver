"""Typed $oh boards for /manual-input.

A token is a cell, an optional sphere letter, and an optional * for "I clicked
it": C4G is a tile shown green, C4G* a covered tile you clicked that was green,
C4* a shown sphere you clicked. C is the $oc prize, only ever typed as clicked.
When adding spheres, a first word with no cell means the suggested cell: G means
"I clicked it and got green", * means "I clicked the sphere that was there".
"""

import re

from src.solver.board import N_CELLS, BoardInputError, cell_index, cell_name
from src.solver.modes.oh import COLORS, PRIZE
from src.solver.oh_rule import OhBoard

LETTERS = " ".join(COLORS + PRIZE)
TOKEN = re.compile(r"^([A-E][1-5])?([A-Z])?(\*)?$")


def _words(text: str) -> list[str]:
    merged: list[str] = []
    for word in text.upper().replace(",", " ").split():
        if (
            merged
            and re.fullmatch(r"[A-E][1-5]", merged[-1])
            and re.fullmatch(r"[A-Z]\*?|\*", word)
        ):
            merged[-1] += word
        else:
            merged.append(word)
    return merged


def _token(word: str) -> tuple[int | None, str | None, bool]:
    match = TOKEN.fullmatch(word)
    if match is None or word == "":
        raise BoardInputError(
            f"{word!r}: expected a cell, a sphere and maybe *, like C4G*"
        )
    cell, letter, star = match.groups()
    if letter is not None and letter not in COLORS + PRIZE:
        raise BoardInputError(f"{word!r}: sphere must be one of {LETTERS}")
    return (None if cell is None else cell_index(cell)), letter, star is not None


def _apply(
    cells: list, clicked: set, cell: int, letter: str | None, star: bool
) -> None:
    if letter is not None:
        if cells[cell] is not None:
            raise BoardInputError(f"{cell_name(cell)} is already shown")
        cells[cell] = letter
    elif not star:
        raise BoardInputError(f"{cell_name(cell)}: add a sphere letter or *")
    elif cells[cell] is None:
        raise BoardInputError(
            f"{cell_name(cell)} is covered; type what it was, like {cell_name(cell)}G*"
        )
    if star:
        if cell in clicked:
            raise BoardInputError(f"{cell_name(cell)} is already clicked")
        clicked.add(cell)


def parse_board(text: str) -> OhBoard:
    cells: list[str | None] = [None] * N_CELLS
    clicked: set[int] = set()
    for word in _words(text):
        cell, letter, star = _token(word)
        if cell is None:
            raise BoardInputError(f"{word!r}: start with a cell, like C4G")
        if letter is None:
            raise BoardInputError(f"{word!r}: add the sphere letter, like {word[:2]}G")
        _apply(cells, clicked, cell, letter, star)
    return OhBoard(tuple(cells), frozenset(clicked))


def add_spheres(board: OhBoard, text: str, suggested: int | None = None) -> OhBoard:
    words = _words(text)
    if not words:
        raise BoardInputError("type a cell and a sphere, like C4 G*")
    cells = list(board.cells)
    clicked = set(board.clicked)
    for k, word in enumerate(words):
        cell, letter, star = _token(word)
        if cell is None:
            if k > 0 or suggested is None:
                raise BoardInputError(f"{word!r}: start with a cell, like C4G")
            cell, star = suggested, True
        _apply(cells, clicked, cell, letter, star)
    return OhBoard(tuple(cells), frozenset(clicked))
