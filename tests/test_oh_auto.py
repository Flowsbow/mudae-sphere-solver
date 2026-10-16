import asyncio

import pytest
from test_auto import _Message, _play, _rows
from test_rewards import dump_content

from src.bot.commands import OcService
from src.bot.mudae_reader import (
    MUDAE_ID,
    NotAnOcBoardError,
    NotAnOhBoardError,
    read_oc_board,
    read_oh_board,
)
from src.bot.oh import OhBoardView, OhService
from src.solver.board import cell_index
from src.solver.modes.oh import BASE_PAYOUT, OC_GAME_VALUE
from src.solver.oh_board import parse_board

PLAYER = 5
OH_TEXT = dump_content("oh_fresh.txt")


@pytest.fixture(scope="module")
def service():
    return OcService()


def _oh(dump_name, message_id=300):
    return _Message(
        MUDAE_ID,
        content=dump_content(dump_name),
        components=_rows(dump_name),
        message_id=message_id,
    )


def test_fresh_board_shows_one_blue():
    board = read_oh_board(_oh("oh_fresh.txt"))
    assert not board.finished
    assert board.board == parse_board("A3B")


def test_midgame_reads_shown_tiles_and_the_four_clicks():
    board = read_oh_board(_oh("oh_midgame.txt"))
    assert not board.finished
    assert board.board == parse_board(
        "A1T A3B A5B B1B B2T* B3B* B5B C1B C3B C5B* D1T D2B* D3B E2B E3T"
    )
    assert board.board.clicks_left == 1


def test_finished_board_uses_blurple_for_clicks():
    board = read_oh_board(_oh("oh_finished.txt")).board
    clicked = {c for c in range(25) if c in board.clicked}
    assert clicked == {cell_index(c) for c in ("B2", "B3", "C4", "C5", "D2")}
    assert board.covered == []


def test_unclicked_prize_stays_covered_at_the_end():
    finished = read_oh_board(_oh("oh_finished_dark_prize.txt"))
    assert finished.finished
    assert finished.board.covered == [cell_index("E1")]
    assert finished.board.cells[cell_index("B5")] == "D"


def test_rainbow_game_with_a_multiplier_still_reads():
    board = read_oh_board(_oh("oh_rainbow_finished.txt")).board
    assert "W" in board.cells


def test_oh_board_is_not_read_as_oc():
    with pytest.raises(NotAnOcBoardError, match=r"\$oh"):
        read_oc_board(_oh("oh_fresh.txt"))


def test_oc_board_is_not_read_as_oh():
    message = _Message(
        MUDAE_ID,
        content=dump_content("oc_fresh.txt"),
        components=_rows("oc_fresh.txt"),
    )
    with pytest.raises(NotAnOhBoardError):
        read_oh_board(message)


def test_full_game_reply_follows_every_mudae_edit(service):
    service.auto_users.add(PLAYER)
    try:
        fresh = _oh("oh_fresh.txt")
        tracker, _ = _play(
            service,
            ("new", _Message(PLAYER, "$oh")),
            ("new", fresh),
            ("edit", _oh("oh_midgame.txt")),
            ("edit", _oh("oh_finished.txt")),
        )
    finally:
        service.auto_users.discard(PLAYER)
    (reply,) = fresh.replies
    assert reply.first["embed"].title == "Click A1 (covered)"
    mid, end = reply.edits
    # 1 click left; the best sphere showing is a teal (20), below a covered tile.
    assert mid["embed"].title.endswith("(covered)")
    # Clicks: teal, blue, green, blue, blue.
    assert end["embed"].title == "Game over: about 85 spheres"
    assert tracker.games == {}


def test_oh_needs_the_player_to_type_oh(service):
    service.auto_users.add(PLAYER)
    try:
        fresh = _oh("oh_fresh.txt")
        _play(service, ("new", _Message(PLAYER, "$oc")), ("new", fresh))
    finally:
        service.auto_users.discard(PLAYER)
    assert fresh.replies == []


def test_bonus_raises_sphere_and_oc_values(service):
    oh = OhService(service)
    service.bonus_for[(PLAYER, None)] = (6, 25)
    try:
        payouts = oh.payouts_for(PLAYER, None)
        assert payouts["B"] == 20  # (10 + 6) x 1.25, as observed in with_bonus
        assert oh.oc_value_for(PLAYER, None) == pytest.approx(
            (OC_GAME_VALUE + 5 * 6) * 1.25
        )
    finally:
        del service.bonus_for[(PLAYER, None)]
    assert oh.payouts_for(PLAYER, None) == BASE_PAYOUT


def test_manual_view_marks_game_over_after_five_paid_clicks(service):
    oh = OhService(service)
    board = parse_board("A1B* A2B* A3B* A4B*")
    view = OhBoardView(oh, board, PLAYER, BASE_PAYOUT, OC_GAME_VALUE)
    embed, file = asyncio.run(view.update(board))
    assert embed.title.endswith("(covered)")
    assert not view.add_sphere.disabled
    # The prize click is the 5th paid click.
    done = parse_board("A1B* A2B* A3B* A4B* B1C*")
    embed, file = asyncio.run(view.update(done))
    assert embed.title == "Game over: about 40 spheres"
    assert embed.description == "Plus the free $oc game."
    assert view.add_sphere.disabled
    assert file.filename == "board.png"
