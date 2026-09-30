from pathlib import Path

import pytest

from src.bot.mudae_reader import (
    ButtonInfo,
    NotAnOcBoardError,
    board_from_buttons,
)
from src.solver.board import BoardState
from src.solver.ev import Solver
from src.solver.modes.oc import BASE_PAYOUT, CLICKS, LAYOUTS, SYMMETRIES, prior

DUMPS = Path(__file__).resolve().parent.parent / "data" / "mudae"


def _buttons_from_dump(name: str) -> list[ButtonInfo]:
    buttons = []
    for line in (DUMPS / name).read_text().splitlines():
        if "| emoji=" not in line:
            continue
        fields = dict(
            part.strip().split("=", 1) for part in line.split("|")[1:] if "=" in part
        )
        buttons.append(
            ButtonInfo(
                emoji=fields["emoji"].split(":")[0],
                disabled=fields["disabled"] == "True",
                style=fields["style"],
            )
        )
    return buttons


def test_fresh_board_reads_as_empty():
    board = board_from_buttons(_buttons_from_dump("oc_fresh.txt"))
    assert board.state == BoardState()
    assert not board.finished


def test_midgame_board_reads_the_three_clicked_cells():
    board = board_from_buttons(_buttons_from_dump("oc_midgame.txt"))
    assert board.state == BoardState.parse("A1R A3G B2Y")
    assert not board.finished


def test_finished_board_reads_every_cell_and_is_marked_finished():
    board = board_from_buttons(_buttons_from_dump("oc_finished.txt"))
    assert board.finished
    letters = "".join(c.name[0] for c in board.state.revealed)
    assert letters == "ROGGTOYBBBGBYBBTBBYBGBBBT"


def test_midgame_board_from_mudae_is_solvable():
    board = board_from_buttons(_buttons_from_dump("oc_midgame.txt"))
    solver = Solver(LAYOUTS, prior(), BASE_PAYOUT, CLICKS, SYMMETRIES)
    analysis = solver.analyze(board.state)
    assert analysis.clicks_left == 2
    assert analysis.best is not None


def test_rejects_a_message_with_the_wrong_number_of_buttons():
    with pytest.raises(NotAnOcBoardError):
        board_from_buttons([ButtonInfo("spU", False)] * 24)


def test_rejects_an_unknown_emoji():
    buttons = [ButtonInfo("spU", False)] * 24 + [ButtonInfo("spX", True)]
    with pytest.raises(NotAnOcBoardError):
        board_from_buttons(buttons)


def test_finished_board_knows_which_five_cells_were_clicked():
    from src.solver.board import cell_index

    board = board_from_buttons(_buttons_from_dump("oc_finished.txt"))
    assert board.clicked == {cell_index(c) for c in ("A1", "A2", "A3", "B1", "B2")}


def test_midgame_board_has_no_blurple_cells():
    board = board_from_buttons(_buttons_from_dump("oc_midgame.txt"))
    assert board.clicked == frozenset()
