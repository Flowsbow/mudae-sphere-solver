from dataclasses import dataclass

import discord

from src.solver.board import N_CELLS, BoardInputError, BoardState, Color
from src.solver.modes.oq import PURPLE, RED, RED_SHOWN
from src.solver.oq_board import check
from src.solver.oq_ev import HIDDEN

# Everything below comes from Flow's inspector dumps of one real $oc game,
# 2026-09-29: data/mudae/oc_fresh.txt, oc_midgame.txt, oc_finished.txt.
MUDAE_ID = 432610292342587392
HIDDEN_EMOJI = "spU"
# At game end Mudae marks the player's clicks blurple ("primary"): oc_finished.txt.
CLICKED_STYLE = "primary"
EMOJI_COLOR = {
    "sp": Color.RED,
    "spO": Color.ORANGE,
    "spY": Color.YELLOW,
    "spG": Color.GREEN,
    "spT": Color.TEAL,
    "spB": Color.BLUE,
}


class NotAnOcBoardError(ValueError):
    pass


@dataclass(frozen=True)
class ButtonInfo:
    emoji: str | None
    disabled: bool
    style: str | None = None


@dataclass(frozen=True)
class MudaeBoard:
    state: BoardState
    finished: bool
    clicked: frozenset[int] = frozenset()


def buttons_of(message: discord.Message) -> list[ButtonInfo]:
    found = []
    for row in message.components:
        for item in getattr(row, "children", []):
            emoji = getattr(item, "emoji", None)
            style = getattr(item, "style", None)
            found.append(
                ButtonInfo(
                    emoji=emoji.name if emoji is not None else None,
                    disabled=bool(getattr(item, "disabled", False)),
                    style=getattr(style, "name", style),
                )
            )
    return found


def board_from_buttons(buttons: list[ButtonInfo]) -> MudaeBoard:
    if len(buttons) != N_CELLS:
        raise NotAnOcBoardError(f"expected {N_CELLS} buttons, found {len(buttons)}")
    cells: list[Color | None] = []
    for i, button in enumerate(buttons):
        if button.emoji == HIDDEN_EMOJI:
            cells.append(None)
        elif button.emoji in EMOJI_COLOR:
            cells.append(EMOJI_COLOR[button.emoji])
        else:
            raise NotAnOcBoardError(f"button {i} has unknown emoji {button.emoji!r}")
    finished = all(color is not None for color in cells)
    clicked = frozenset(
        i for i, button in enumerate(buttons) if button.style == CLICKED_STYLE
    )
    return MudaeBoard(BoardState(tuple(cells)), finished, clicked)


def is_sphere_board(message: discord.Message) -> bool:
    # Every $oc, $oq and $oh button in Flow's dumps uses an "sp..." emoji.
    return message.author.id == MUDAE_ID and any(
        button.emoji is not None and button.emoji.startswith("sp")
        for button in buttons_of(message)
    )


def read_oc_board(message: discord.Message) -> MudaeBoard:
    if message.author.id != MUDAE_ID:
        raise NotAnOcBoardError("that message isn't from Mudae")
    if OQ_RULES in message.content:
        raise NotAnOcBoardError("that's a $oq board")
    return board_from_buttons(buttons_of(message))


# $oq, from Flow's dumps of real games, 2026-10-04 and 2026-10-05:
# data/mudae/oq_fresh.txt, oq_red_shown.txt, oq_red_midgame.txt,
# oq_red_finished.txt and oq_finished.txt.
OQ_RULES = "**Find 3 purple spheres**"
OQ_EMOJI_CODE = {"spB": 0, "spT": 1, "spG": 2, "spY": 3, "spO": 4, "spP": PURPLE}
# The 4th purple once 3 are found: red ("sp"), or rainbow ("spW", Flow,
# 2026-10-05). Clickable while shown (oq_red_shown.txt), disabled once clicked.
FOURTH_PURPLE = {"sp": "RED", "spW": "RAINBOW"}


class NotAnOqBoardError(ValueError):
    pass


@dataclass(frozen=True)
class OqMudaeBoard:
    codes: tuple[int, ...]  # only what the player has revealed
    finished: bool
    rainbow: bool  # the 4th purple turned rainbow instead of red
    # The whole board once the game is over (Mudae reveals every tile): purple
    # counts, with all 4 purples as PURPLE, as in src/solver/modes/oq.py LAYOUTS.
    layout: tuple[int, ...] | None = None


def _oq_code(button: ButtonInfo, finished: bool) -> int:
    if button.emoji == HIDDEN_EMOJI:
        return HIDDEN
    if button.emoji in FOURTH_PURPLE:
        if finished:
            return RED if button.style == CLICKED_STYLE else RED_SHOWN
        return RED if button.disabled else RED_SHOWN
    if button.emoji not in OQ_EMOJI_CODE:
        raise NotAnOqBoardError(f"unknown emoji {button.emoji!r}")
    # At game end Mudae shows the whole board; only blurple tiles were clicked.
    if finished and button.style != CLICKED_STYLE:
        return HIDDEN
    return OQ_EMOJI_CODE[button.emoji]


def read_oq_board(message: discord.Message) -> OqMudaeBoard:
    if message.author.id != MUDAE_ID or OQ_RULES not in message.content:
        raise NotAnOqBoardError("that isn't a Mudae $oq board")
    buttons = buttons_of(message)
    if len(buttons) != N_CELLS:
        raise NotAnOqBoardError(f"expected {N_CELLS} buttons, found {len(buttons)}")
    finished = all(button.emoji != HIDDEN_EMOJI for button in buttons)
    codes = tuple(_oq_code(button, finished) for button in buttons)
    try:
        check(codes)
    except BoardInputError as err:
        raise NotAnOqBoardError(str(err)) from err
    rainbow = any(button.emoji == "spW" for button in buttons)
    layout = None
    if finished:
        layout = tuple(
            PURPLE if b.emoji in FOURTH_PURPLE else OQ_EMOJI_CODE[b.emoji]
            for b in buttons
        )
    return OqMudaeBoard(codes, finished, rainbow, layout)
