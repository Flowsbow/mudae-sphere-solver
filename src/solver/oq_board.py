from src.solver.board import (
    N_CELLS,
    BoardInputError,
    cell_index,
    cell_name,
    with_suggested_cell,
)
from src.solver.modes.oq import PURPLE, PURPLES_FOR_RED, RED, RED_SHOWN
from src.solver.oq_ev import HIDDEN

# Mudae's $oq rules text: "Blue = 0, teal = 1, green = 2, yellow = 3, orange = 4".
# R is the red sphere: typed on a hidden cell it means "shown, not clicked yet";
# typed again on that cell it means "clicked".
LETTER_CODE = {"B": 0, "T": 1, "G": 2, "Y": 3, "O": 4, "P": PURPLE, "R": RED_SHOWN}
LETTERS = " ".join(LETTER_CODE)


def _tokens(text: str) -> list[tuple[int, str]]:
    words = text.replace(",", " ").split()
    merged: list[str] = []
    for word in words:
        if merged and len(merged[-1]) == 2 and len(word) == 1:
            merged[-1] += word
        else:
            merged.append(word)
    tokens = []
    for token in merged:
        if len(token) != 3:
            raise BoardInputError(f"{token!r}: expected a cell then a color, like C4T")
        letter = token[2].upper()
        if letter not in LETTER_CODE:
            raise BoardInputError(f"{token!r}: color must be one of {LETTERS}")
        tokens.append((cell_index(token[:2]), letter))
    return tokens


def check(codes: tuple[int, ...]) -> None:
    purples = codes.count(PURPLE)
    reds = sum(1 for x in codes if x in (RED, RED_SHOWN))
    if purples > PURPLES_FOR_RED:
        raise BoardInputError("only 3 purples can be found; the 4th turns red")
    if reds > 1:
        raise BoardInputError("there is only one red")
    if reds and purples < PURPLES_FOR_RED:
        raise BoardInputError("the red only appears after 3 purples are found")
    if purples == PURPLES_FOR_RED and not reds:
        raise BoardInputError(
            "after the 3rd purple, Mudae shows the 4th as red. Add both at once, "
            "like B2 P E1 R"
        )


def parse_board(text: str) -> tuple[int, ...]:
    codes = [HIDDEN] * N_CELLS
    for cell, letter in _tokens(text):
        if codes[cell] != HIDDEN:
            raise BoardInputError(f"{cell_name(cell)} is listed twice")
        codes[cell] = LETTER_CODE[letter]
    check(tuple(codes))
    return tuple(codes)


def add_cells(
    codes: tuple[int, ...], text: str, suggested: int | None = None
) -> tuple[int, ...]:
    tokens = _tokens(with_suggested_cell(text, suggested))
    if not tokens:
        raise BoardInputError("type a cell and a color, like C4 G")
    new = list(codes)
    for cell, letter in tokens:
        if new[cell] == RED_SHOWN and letter == "R":
            new[cell] = RED
        elif new[cell] != HIDDEN:
            raise BoardInputError(f"{cell_name(cell)} is already revealed")
        else:
            new[cell] = LETTER_CODE[letter]
    check(tuple(new))
    return tuple(new)
