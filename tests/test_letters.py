"""$toggleletter boards and rewards: data/mudae/*_letters.txt (Flow, 2026-10-21)."""

from test_auto import _Message, _rows
from test_rewards import dump_content

from src.bot.emoji_names import plain_emoji, plain_text
from src.bot.mudae_reader import MUDAE_ID, read_oc_board, read_oh_board
from src.bot.rewards import parse_oh_rewards, parse_rewards
from src.solver.board import Color, cell_index
from src.solver.oh_board import parse_board
from src.solver.oh_rule import with_free_darks


def _message(dump):
    return _Message(MUDAE_ID, dump_content(dump), _rows(dump))


def test_letter_style_names_become_the_usual_ones():
    assert plain_emoji("spB2") == "spB"
    assert plain_emoji("spR2") == "sp"
    assert plain_emoji("spL2") == "spL"
    assert plain_emoji("spB") == "spB"
    assert plain_emoji("sp") == "sp"
    assert plain_emoji(None) is None
    assert plain_text("<:spR2:9> **+150**") == "<:sp:9> **+150**"


def test_finished_oc_board_with_letters_reads():
    board = read_oc_board(_message("oc_finished_letters.txt"))
    assert board.finished
    assert board.state.revealed[cell_index("B4")] == Color.RED
    assert board.clicked == {cell_index(c) for c in ("B2", "B4", "B5", "C2", "C4")}


def test_finished_oh_board_with_letters_reads_and_has_a_free_dark():
    board = read_oh_board(_message("oh_finished_letters.txt"))
    assert board.finished
    oh = board.board
    assert oh.cells[cell_index("E1")] == "L" and oh.cells[cell_index("B5")] == "D"
    # 6 non-purple clicks in a 5-click game: the dark turned purple, which is free.
    assert oh.free_darks == 1
    assert oh.clicks_left == 0


def test_oh_rewards_with_letters_parse():
    rewards = parse_oh_rewards(dump_content("oh_rewards_letters.txt"))
    labels = [r.label for r in rewards]
    assert labels == [
        "BLUE", "BLUE", "PURPLE", "PURPLE", "BLUE", "BLUE", "DARK", "LIGHT",
    ]  # fmt: skip
    assert rewards[6].became == "PURPLE" and rewards[6].spheres == 5
    assert rewards[7].spheres == 50  # blue + blue + teal + blue
    assert sum(r.spheres for r in rewards) == 105


def test_oc_rewards_with_letters_parse():
    rewards = parse_rewards("<:spR2:1> **+150**\n<:spB2:2> **+10**")
    assert [(r.emoji, r.spheres) for r in rewards] == [("sp", 150), ("spB", 10)]


def test_a_live_board_that_looks_out_of_clicks_had_a_free_dark():
    board = parse_board("A1B* A2B* A3B* A4D* A5B* B1G")
    assert board.clicks_left == 0  # typed: nothing says the dark was free
    cells, clicked = board.cells, board.clicked
    live = with_free_darks(cells, clicked, live=True)
    assert live.free_darks == 1 and live.clicks_left == 1


def test_a_free_dark_is_never_invented_without_a_dark():
    board = with_free_darks(parse_board("A1B* A2B*").cells, frozenset(), live=True)
    assert board.free_darks == 0
