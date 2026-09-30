from dataclasses import dataclass

import discord

from src.solver.board import N_CELLS, BoardState, Color

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


def read_oc_board(message: discord.Message) -> MudaeBoard:
    if message.author.id != MUDAE_ID:
        raise NotAnOcBoardError("that message isn't from Mudae")
    return board_from_buttons(buttons_of(message))
