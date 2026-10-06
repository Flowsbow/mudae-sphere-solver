import asyncio

import discord
import pytest
from test_auto import _Message, _play
from test_mudae_reader import _buttons_from_dump
from test_rewards import dump_content

from src.bot.commands import OcService
from src.bot.mudae_reader import (
    MUDAE_ID,
    NotAnOcBoardError,
    NotAnOqBoardError,
    read_oc_board,
    read_oq_board,
)
from src.bot.oq import OqService
from src.bot.rewards import REWARDS_PLACEHOLDER
from src.bot.totals import StatsStore
from src.solver.board import cell_index
from src.solver.modes.oq import BASE_PAYOUT, PURPLE, RED, RED_SHOWN
from src.solver.oq_ev import HIDDEN

PLAYER = 5
OQ_TEXT = dump_content("oq_fresh.txt")
# The real finished game in data/mudae/oq_red_finished.txt. Its rewards message
# (oq_rewards_finished.txt) starts Y T G P P P R G, which fixes the first 8 clicks.
FINAL = [
    "spP spT spB spB spB",
    "spG spY spT spT spB",
    "spP spG spP spG spT",
    "spT spG spG sp spT",
    "spB spB spT spT spT",
]
FINAL = [e for row in FINAL for e in row.split()]
ORDER = ["B2", "B3", "B1", "A1", "C1", "C3", "D4", "C4", "D2", "D3"]
VALUE = {"spB": 10, "spT": 20, "spG": 35, "spY": 55, "spP": 5, "sp": 150, "spW": 500}


def _at(ms):
    return (2_000_000 + ms) << 22


BOARD_ID, REWARDS_ID = _at(0), _at(680)


def _mudae(dump: str, swap=None, message_id=1):
    rows = []
    buttons = _buttons_from_dump(dump)
    for r in range(5):
        children = [
            type(
                "Btn",
                (),
                {
                    "emoji": discord.PartialEmoji(
                        name=(swap or {}).get(b.emoji, b.emoji)
                    ),
                    "disabled": b.disabled,
                    "style": b.style,
                },
            )()
            for b in buttons[r * 5 : r * 5 + 5]
        ]
        rows.append(type("Row", (), {"children": children})())
    text = dump_content(dump)
    return _Message(MUDAE_ID, text, rows, message_id)


def test_reader_sees_a_red_that_is_shown_but_not_clicked():
    board = read_oq_board(_mudae("oq_red_shown.txt"))
    assert board.codes[cell_index("D2")] == RED_SHOWN
    assert [cell_index(c) for c in ("D1", "D5", "E5")] == [
        i for i, code in enumerate(board.codes) if code == PURPLE
    ]
    assert not board.finished and not board.rainbow


def test_reader_sees_a_clicked_red():
    board = read_oq_board(_mudae("oq_red_midgame.txt"))
    assert board.codes[cell_index("D4")] == RED


def test_reader_reads_a_rainbow_as_the_fourth_purple():
    board = read_oq_board(_mudae("oq_red_shown.txt", swap={"sp": "spW"}))
    assert board.codes[cell_index("D2")] == RED_SHOWN
    assert board.rainbow


def test_reader_keeps_only_the_clicked_tiles_of_a_finished_board():
    board = read_oq_board(_mudae("oq_finished.txt"))
    assert board.finished
    clicked = [i for i, code in enumerate(board.codes) if code != HIDDEN]
    assert clicked == [
        cell_index(c) for c in ("A1", "A4", "A5", "B2", "B4", "B5", "C3", "C5", "D3")
    ]


def test_oc_and_oq_boards_are_told_apart_by_mudaes_rules_text():
    with pytest.raises(NotAnOcBoardError):
        read_oc_board(_mudae("oq_fresh.txt"))
    with pytest.raises(NotAnOqBoardError):
        read_oq_board(_mudae("oc_fresh.txt"))


def _board(clicks: int, finished=False, rainbow=False, final=FINAL, order=ORDER):
    shown = set(order[:clicks])
    purples = sum(final[cell_index(c)] == "spP" for c in shown)
    children = []
    for i, emoji in enumerate(final):
        name = f"{'ABCDE'[i // 5]}{i % 5 + 1}"
        if emoji == "sp" and rainbow:
            emoji = "spW"
        clicked = name in shown
        if finished:
            style, disabled = ("primary" if clicked else "secondary"), True
        elif clicked:
            style, disabled = "secondary", True
        elif emoji in ("sp", "spW") and purples == 3:
            style, disabled = "secondary", False
        else:
            emoji, style, disabled = "spU", "secondary", False
        children.append(
            type(
                "Btn",
                (),
                {
                    "emoji": discord.PartialEmoji(name=emoji),
                    "disabled": disabled,
                    "style": style,
                },
            )()
        )
    rows = [
        type("Row", (), {"children": children[r * 5 : r * 5 + 5]})() for r in range(5)
    ]
    return _Message(MUDAE_ID, OQ_TEXT, rows, BOARD_ID)


def _rewards(clicks: int, rainbow=False, final=FINAL, order=ORDER):
    lines = []
    for cell in order[:clicks]:
        emoji = final[cell_index(cell)]
        if emoji == "sp" and rainbow:
            emoji = "spW"
        free = "(Free) " if emoji == "spP" else ""
        lines.append(f"<:{emoji}:1437140625844867244> {free}**+{VALUE[emoji]}**")
    return _Message(MUDAE_ID, "\n".join(lines), message_id=REWARDS_ID)


@pytest.fixture(scope="module")
def oq_service():
    return OqService(OcService())


def _play_oq(
    oq_service, rainbow=False, typed="$oq", stats=None, final=FINAL, order=ORDER
):
    stats = stats if stats is not None else StatsStore()
    game = {"rainbow": rainbow, "final": final, "order": order}
    steps = [
        ("new", _Message(PLAYER, typed)),
        ("new", _board(0, **game)),
        ("new", _Message(MUDAE_ID, REWARDS_PLACEHOLDER, message_id=REWARDS_ID)),
    ]
    for n in range(1, len(order) + 1):
        steps.append(("edit", _board(n, **game)))
        steps.append(("edit", _rewards(n, **game)))
    steps.append(("edit", _board(len(order), finished=True, **game)))
    oq_service.settings.auto_users.add(PLAYER)
    try:
        _play(oq_service.settings, *steps, stats=stats, oq=oq_service)
    finally:
        oq_service.settings.auto_users.discard(PLAYER)
    return stats, steps[1][1].replies


def test_a_full_oq_game_is_followed_and_recorded(oq_service):
    stats, (reply,) = _play_oq(oq_service)
    assert reply.first["embed"].title.startswith("Click ")
    assert reply.first["mention_author"] is False
    (credit,) = reply.first["view"].children
    assert credit.url == "https://github.com/Flowsbow/mudae-sphere-solver"

    end = reply.edits[-1]["embed"]
    fields = {f.name: f.value for f in end.fields}
    assert end.title == "Game over: 380 spheres"
    assert fields["Red"] == "Red collected"
    assert fields["Solver picks followed"].endswith("of 10")
    # Mudae showed the whole board, so hindsight is for that board, not an average.
    assert "average" not in fields["Best with hindsight"]

    totals = stats.all.oq
    assert totals.games == 1
    assert totals.spheres_gained == 380
    assert totals.clicked == {
        "BLUE": 0, "TEAL": 1, "GREEN": 4, "YELLOW": 1, "ORANGE": 0,
        "PURPLE": 3, "RED": 1, "RAINBOW": 0,
    }  # fmt: skip
    assert stats.players[PLAYER].oq == totals
    assert stats.all.oc.games == 0


def test_a_rainbow_game_shows_and_counts_the_rainbow(oq_service):
    stats, (reply,) = _play_oq(oq_service, rainbow=True)
    end = reply.edits[-1]["embed"]
    fields = {f.name: f.value for f in end.fields}
    assert fields["Red"] == "Rainbow collected"
    assert end.title == "Game over: 730 spheres"  # 380 with the red's 150 -> 500
    assert stats.all.oq.spheres_gained == 730
    assert stats.all.oq.clicked["RAINBOW"] == 1
    assert stats.all.oq.clicked["RED"] == 0


def test_typing_oc_does_not_claim_an_oq_board(oq_service):
    stats, replies = _play_oq(oq_service, typed="$oc")
    assert replies == []
    assert stats.all.oq.games == 0


def test_the_oq_command_does_not_claim_an_oc_board():
    from test_auto import _board as oc_board

    service = OcService()
    service.auto_users.add(PLAYER)
    fresh = oc_board("oc_fresh.txt")
    _play(service, ("new", _Message(PLAYER, "$oq")), ("new", fresh))
    assert fresh.replies == []


def test_an_auto_oq_board_has_no_add_a_sphere_button(oq_service):
    from src.bot.oq import OqBoardView

    async def make():
        return OqBoardView(oq_service, (HIDDEN,) * 25, PLAYER, {}, manual=False)

    view = asyncio.run(make())
    assert [item.url for item in view.children] == [
        "https://github.com/Flowsbow/mudae-sphere-solver"
    ]


def test_the_rainbow_tile_is_drawn_differently_from_red(oq_service):
    import io

    from PIL import Image

    from src.render.board_image import _tile_box, render_oq

    codes = read_oq_board(_mudae("oq_red_shown.txt")).codes
    analysis = asyncio.run(oq_service.analyze(codes))
    red, rainbow = (
        Image.open(io.BytesIO(render_oq(codes, analysis, rainbow=flag))).convert("RGB")
        for flag in (False, True)
    )
    x0, y0, x1, y1 = (v // 2 for v in _tile_box(cell_index("D2")))
    tile = rainbow.crop((x0 + 4, y0 + 4, x1 - 4, y1 - 4))
    assert len({tile.getpixel((2, y)) for y in range(0, tile.height, 4)}) >= 5
    assert (
        red.crop((x0, y0, x1, y1)).tobytes() != rainbow.crop((x0, y0, x1, y1)).tobytes()
    )


def test_hindsight_uses_the_real_board_once_mudae_shows_it(oq_service):
    board = read_oq_board(_mudae("oq_finished.txt"))
    averaged = asyncio.run(oq_service.hindsight(board.codes, BASE_PAYOUT))
    real = asyncio.run(oq_service.hindsight(board.codes, BASE_PAYOUT, board.layout))
    assert averaged == (345.0, 6)
    assert real == (315.0, 1)


def test_hindsight_falls_back_to_the_average_for_a_board_off_the_rules(oq_service):
    board = read_oq_board(_mudae("oq_finished.txt"))
    broken = (0,) * 25
    result = asyncio.run(oq_service.hindsight(board.codes, BASE_PAYOUT, broken))
    assert result == (345.0, 6)


def test_a_failed_oq_game_over_edit_still_records_the_game(oq_service, monkeypatch):
    from test_auto import _FakeReply

    monkeypatch.setattr(_FakeReply, "fail_game_over", True)
    stats = StatsStore()
    _play_oq(oq_service, stats=stats)
    assert stats.all.oq.games == 1


def test_an_oq_click_as_good_as_the_solvers_pick_counts_as_followed(oq_service):
    from src.bot.oq import OqBoardView

    empty = (HIDDEN,) * 25

    async def run():
        view = OqBoardView(oq_service, empty, PLAYER, BASE_PAYOUT, manual=False)
        await view.update(empty)
        pick = view.last_best
        other = min(view.last_tied - {pick})
        await view.update(tuple(1 if c == other else HIDDEN for c in range(25)))
        return view, pick, other

    view, pick, other = asyncio.run(run())
    assert other != pick
    assert (view.followed, view.judged) == (1, 1)


# data/mudae/oq_finished.txt: only 2 purples were found, so at the end 6 placements
# still fit what was clicked, but Mudae shows the real one.
FINAL_2P = [
    e
    for row in [
        "spT spT spT spP spT",
        "spP spT spT spG spG",
        "spT spT spB spT spP",
        "spT spT spT spT spT",
        "spT spP spT spB spB",
    ]
    for e in row.split()
]
ORDER_2P = ["C3", "A1", "B2", "A4", "B4", "B5", "C5", "A5", "D3"]


def test_hindsight_on_the_real_board_in_an_auto_read_game(oq_service):
    _, (reply,) = _play_oq(oq_service, final=FINAL_2P, order=ORDER_2P)
    fields = {f.name: f.value for f in reply.edits[-1]["embed"].fields}
    assert fields["Best with hindsight"].startswith("315.")


def test_a_finished_boards_layout_counts_the_red_as_a_purple():
    board = read_oq_board(_mudae("oq_red_finished.txt"))
    assert board.layout[cell_index("D4")] == PURPLE
    assert board.layout.count(PURPLE) == 4
    assert read_oq_board(_mudae("oq_red_midgame.txt")).layout is None


def test_a_prediction_made_before_the_rainbow_is_not_compared(oq_service):
    # Paid clicks first, so exact search starts while the 4th purple is unknown.
    order = ["B2", "B3", "B1", "C4", "D2", "A1", "C1", "C3", "D4", "D3"]
    stats, (reply,) = _play_oq(oq_service, rainbow=True, order=order)
    end = reply.edits[-1]["embed"]
    assert end.title == "Game over: 730 spheres"
    assert end.description is None
    assert stats.all.oq.followed_luck.n == 0
