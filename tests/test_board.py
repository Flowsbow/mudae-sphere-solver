import pytest

from src.solver.board import (
    N_CELLS,
    BoardInputError,
    BoardState,
    Color,
    cell_index,
    cell_name,
)


def test_cell_index_of_corners_and_center():
    assert cell_index("A1") == 0
    assert cell_index("A5") == 4
    assert cell_index("C3") == 12
    assert cell_index("d4") == 18
    assert cell_index("E5") == 24


def test_cell_name_inverts_cell_index():
    assert all(cell_index(cell_name(i)) == i for i in range(N_CELLS))


def test_parse_reads_cells_and_colors():
    state = BoardState.parse("B2T, c4t D4R")
    assert state.revealed[cell_index("B2")] is Color.TEAL
    assert state.revealed[cell_index("C4")] is Color.TEAL
    assert state.revealed[cell_index("D4")] is Color.RED
    assert state.n_revealed == 3


def test_parse_of_nothing_is_the_empty_board():
    assert BoardState.parse("") == BoardState()
    assert BoardState().n_revealed == 0


@pytest.mark.parametrize("text", ["F1R", "A6R", "A1X", "A1", "A1RR", "A1R A1B"])
def test_parse_rejects_bad_input(text):
    with pytest.raises(BoardInputError):
        BoardState.parse(text)


def test_reveal_returns_a_new_state():
    empty = BoardState()
    one = empty.reveal(18, Color.RED)
    assert empty.n_revealed == 0
    assert one.revealed[18] is Color.RED


def test_reveal_rejects_an_already_revealed_cell():
    with pytest.raises(BoardInputError):
        BoardState.parse("D4R").reveal(18, Color.BLUE)


def test_states_with_the_same_reveals_are_equal_and_hash_equal():
    a = BoardState.parse("B2T D4R")
    b = BoardState.parse("D4R B2T")
    assert a == b
    assert hash(a) == hash(b)


def test_a_lone_color_gets_the_suggested_cell():
    from src.solver.board import with_suggested_cell

    c4 = cell_index("C4")
    assert with_suggested_cell("g", c4) == "C4 g"
    assert with_suggested_cell("  G ", c4) == "C4 G"
    assert with_suggested_cell("P E1 R", c4) == "C4 P E1 R"
    assert with_suggested_cell("B2 T", c4) == "B2 T"
    assert with_suggested_cell("", c4) == ""
    with pytest.raises(BoardInputError, match="no suggested cell"):
        with_suggested_cell("g", None)
