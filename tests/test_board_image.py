import io

import pytest
from PIL import Image

from src.render.board_image import BEST_OUTLINE, _tile_box, click_values, render
from src.solver.board import BoardState, cell_index
from src.solver.ev import Solver
from src.solver.modes.oc import BASE_PAYOUT, CLICKS, LAYOUTS, SYMMETRIES, prior


@pytest.fixture(scope="module")
def solver():
    return Solver(LAYOUTS, prior(), BASE_PAYOUT, CLICKS, SYMMETRIES)


def _image(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def test_click_value_of_a_certain_orange_is_90(solver):
    # Red at A1 forces orange on A2 and B1.
    a = solver.analyze(BoardState.parse("A1R C2B B3B"))
    plus = click_values(a, BASE_PAYOUT)
    assert plus[cell_index("A2")] == pytest.approx(90)
    assert plus[cell_index("B1")] == pytest.approx(90)


def test_click_value_of_a_diagonal_cell_next_to_a_corner_red(solver):
    # 3 of red A1's 4 diagonal cells are yellow, the other teal.
    a = solver.analyze(BoardState.parse("A1R C2B B3B"))
    plus = click_values(a, BASE_PAYOUT)
    assert plus[cell_index("B2")] == pytest.approx(0.75 * 55 + 0.25 * 20)


# 2 * 16 padding + 22 labels + 5 * 64 tiles + 4 * 6 gaps = 398 wide; + 48 footer tall.
def test_render_returns_a_png_of_the_expected_size(solver):
    state = BoardState.parse("D4R B2T")
    img = _image(render(state, solver.analyze(state), BASE_PAYOUT))
    assert img.size == (398, 446)


def test_render_is_deterministic(solver):
    state = BoardState.parse("D4R B2T")
    a = solver.analyze(state)
    assert render(state, a, BASE_PAYOUT) == render(state, a, BASE_PAYOUT)


def test_best_cell_has_the_white_outline_and_others_do_not(solver):
    state = BoardState.parse("D4R B2T")
    a = solver.analyze(state)
    img = _image(render(state, a, BASE_PAYOUT))

    def top_edge_pixel(cell):
        x0, y0, x1, _ = (v // 2 for v in _tile_box(cell))
        return img.getpixel(((x0 + x1) // 2, y0 + 1))

    assert top_edge_pixel(a.best) == BEST_OUTLINE
    other = next(c for c in a.cell_value if c != a.best)
    assert top_edge_pixel(other) != BEST_OUTLINE


def test_render_handles_a_finished_game(solver):
    state = BoardState.parse("D4R D5O E4O C5Y E3Y")
    img = _image(render(state, solver.analyze(state), BASE_PAYOUT))
    assert img.size == (398, 446)
