import asyncio
import json

import discord
import pytest
from discord import app_commands
from test_mudae_reader import _buttons_from_dump

import src.bot.auto as auto_module
from src.bot.auto import AutoTracker
from src.bot.commands import OcService, register
from src.bot.mudae_reader import MUDAE_ID
from src.solver.board import BoardState

PLAYER = 5
CHANNEL = type("Channel", (), {"id": 77})()


@pytest.fixture(scope="module")
def service():
    return OcService()


class _FakeReply:
    fail_game_over = False  # set to make the end-of-game edit fail, like a 500

    def __init__(self, kwargs):
        self.first = kwargs
        self.edits = []

    async def edit(self, **kwargs):
        await asyncio.sleep(0)  # a real edit waits on Discord
        if self.fail_game_over and kwargs["embed"].title.startswith("Game over"):
            response = type("Response", (), {"status": 500, "reason": "Error"})()
            raise discord.HTTPException(response, "edit failed")
        self.edits.append(kwargs)
        return self


class _Author:
    def __init__(self, user_id):
        self.id = user_id


class _Message:
    def __init__(self, author_id, content="", components=(), message_id=1):
        self.id = message_id
        self.author = _Author(author_id)
        self.content = content
        self.channel = CHANNEL
        self.guild = None
        self.components = list(components)
        self.interaction_metadata = None
        self.replies = []

    async def reply(self, **kwargs):
        reply = _FakeReply(kwargs)
        self.replies.append(reply)
        return reply


def _rows(dump_name):
    buttons = _buttons_from_dump(dump_name)
    rows = []
    for r in range(5):
        children = [
            type(
                "Btn",
                (),
                {
                    "emoji": discord.PartialEmoji(name=b.emoji),
                    "disabled": b.disabled,
                    "style": b.style,
                },
            )()
            for b in buttons[r * 5 : r * 5 + 5]
        ]
        rows.append(type("Row", (), {"children": children})())
    return rows


def _board(dump_name, message_id=100):
    return _Message(MUDAE_ID, components=_rows(dump_name), message_id=message_id)


def _play(service, *steps, stats=None, oq=None):
    tracker = AutoTracker(service, stats, oq)
    # discord.py logs an exception from one event and keeps handling the next.
    tracker.errors = []

    async def run():
        results = []
        for kind, message in steps:
            handler = tracker.on_message if kind == "new" else tracker.on_message_edit
            try:
                await handler(message)
            except discord.HTTPException as err:
                tracker.errors.append(err)
            results.append(message)
        return tracker, results

    return asyncio.run(run())


def test_full_game_reply_follows_every_mudae_edit(service):
    service.auto_users.add(PLAYER)
    try:
        fresh = _board("oc_fresh.txt")
        tracker, _ = _play(
            service,
            ("new", _Message(PLAYER, "$oc 2")),
            ("new", fresh),
            ("edit", _board("oc_midgame.txt")),
            ("edit", _board("oc_finished.txt")),
        )
    finally:
        service.auto_users.discard(PLAYER)

    (reply,) = fresh.replies
    assert reply.first["embed"].title.startswith("Click ")
    assert reply.first["mention_author"] is False
    (credit,) = reply.first["view"].children
    assert credit.url == "https://github.com/Flowsbow/mudae-sphere-solver"
    mid, end = reply.edits
    assert "2 clicks" in mid["embed"].description
    assert mid["view"].state == BoardState.parse("A1R A2O A3G B1O B2Y")
    # Clicks from the dump: A1 red, A2 orange, A3 green, B1 orange, B2 yellow.
    assert end["embed"].title == "Game over: 420 spheres"
    fields = {f.name: f.value for f in end["embed"].fields}
    assert fields["Red"] == "Found on click 1"
    assert len(fields["Your clicks"].splitlines()) == 5
    assert "344.7" in end["embed"].description
    assert end["attachments"][0].filename == "board.png"
    assert (
        end["view"].children[-1].url
        == "https://github.com/Flowsbow/mudae-sphere-solver"
    )
    assert tracker.games == {}


def test_no_reply_for_players_who_have_not_turned_auto_on(service):
    fresh = _board("oc_fresh.txt")
    _play(service, ("new", _Message(PLAYER, "$oc")), ("new", fresh))
    assert fresh.replies == []


def test_no_reply_when_nobody_typed_oc(service):
    service.auto_users.add(PLAYER)
    try:
        fresh = _board("oc_fresh.txt")
        _play(service, ("new", fresh))
    finally:
        service.auto_users.discard(PLAYER)
    assert fresh.replies == []


@pytest.mark.parametrize("text", ["$och", "$ocx 2", "hello $oc", "$oq"])
def test_other_commands_do_not_count_as_oc(service, text):
    service.auto_users.add(PLAYER)
    try:
        fresh = _board("oc_fresh.txt")
        _play(service, ("new", _Message(PLAYER, text)), ("new", fresh))
    finally:
        service.auto_users.discard(PLAYER)
    assert fresh.replies == []


def test_a_board_long_after_the_oc_message_is_ignored(service, monkeypatch):
    monkeypatch.setattr(auto_module, "PENDING_SECONDS", -1)
    service.auto_users.add(PLAYER)
    try:
        fresh = _board("oc_fresh.txt")
        _play(service, ("new", _Message(PLAYER, "$oc")), ("new", fresh))
    finally:
        service.auto_users.discard(PLAYER)
    assert fresh.replies == []


def test_edits_to_untracked_messages_are_ignored(service):
    tracker, _ = _play(service, ("edit", _board("oc_midgame.txt", message_id=999)))
    assert tracker.games == {}


class _FakeResponse:
    def __init__(self):
        self.sent = []

    async def send_message(self, content, ephemeral=False):
        self.sent.append((content, ephemeral))


def test_autoread_toggles_auto_mode_on_and_off(service):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    register(tree, service)
    command = tree.get_command("autoread")
    interaction = type("I", (), {"user": _Author(42), "response": _FakeResponse()})()

    asyncio.run(command.callback(interaction))
    assert 42 in service.auto_users
    asyncio.run(command.callback(interaction))
    assert 42 not in service.auto_users
    assert all(ephemeral for _, ephemeral in interaction.response.sent)


def _board_from(cells: dict[str, str], clicked=(), message_id=100):
    from src.bot.mudae_reader import EMOJI_COLOR, HIDDEN_EMOJI
    from src.solver.board import COLOR_LETTERS, cell_index

    emoji_for = {color: name for name, color in EMOJI_COLOR.items()}
    by_index = {cell_index(c): COLOR_LETTERS[v] for c, v in cells.items()}
    clicked_idx = {cell_index(c) for c in clicked}
    rows = []
    for r in range(5):
        children = []
        for i in range(r * 5, r * 5 + 5):
            color = by_index.get(i)
            children.append(
                type(
                    "Btn",
                    (),
                    {
                        "emoji": discord.PartialEmoji(
                            name=emoji_for[color] if color is not None else HIDDEN_EMOJI
                        ),
                        "disabled": color is not None,
                        "style": "primary" if i in clicked_idx else "secondary",
                    },
                )()
            )
        rows.append(type("Row", (), {"children": children})())
    return _Message(MUDAE_ID, components=rows, message_id=message_id)


def test_one_click_at_a_time_tracks_every_solver_pick(service):
    final = dict(
        zip(
            [f"{r}{c}" for r in "ABCDE" for c in "12345"],
            "ROGGTOYBBBGBYBBTBBYBGBBBT",
            strict=True,
        )
    )
    order = ["A1", "A2", "B1", "B2", "A3"]
    steps = [("new", _Message(PLAYER, "$oc")), ("new", _board_from({}))]
    for n in range(1, 5):
        steps.append(("edit", _board_from({c: final[c] for c in order[:n]})))
    steps.append(("edit", _board_from(final, clicked=order)))

    service.auto_users.add(PLAYER)
    try:
        fresh = steps[1][1]
        _play(service, *steps)
    finally:
        service.auto_users.discard(PLAYER)

    end = fresh.replies[0].edits[-1]
    fields = {f.name: f.value for f in end["embed"].fields}
    assert end["embed"].title == "Game over: 420 spheres"
    assert fields["Solver picks followed"].endswith("of 5")
    clicks = fields["Your clicks"].splitlines()
    assert [line.split()[1] for line in clicks] == order
    assert all("solver" in line for line in clicks)


# A full auto-read game with Mudae's rewards message alongside it. The rewards
# amounts are double the base values, as on a server with a multiplier.
FINAL = dict(
    zip(
        [f"{r}{c}" for r in "ABCDE" for c in "12345"],
        "ROGGTOYBBBGBYBBTBBYBGBBBT",
        strict=True,
    )
)
ORDER = ["A1", "A2", "B1", "B2", "A3"]


def _at(ms):
    return (1_000_000 + ms) << 22


BOARD_ID, REWARDS_ID = _at(0), _at(500)


def _rewards(cells, ids=REWARDS_ID):
    from src.bot.mudae_reader import EMOJI_COLOR
    from src.solver.board import COLOR_LETTERS
    from src.solver.modes.oc import BASE_PAYOUT

    emoji_for = {color: name for name, color in EMOJI_COLOR.items()}
    lines = []
    for cell in cells:
        color = COLOR_LETTERS[FINAL[cell]]
        lines.append(
            f"<:{emoji_for[color]}:1437140700604137554> **+{2 * BASE_PAYOUT[color]}**"
        )
    if lines:
        lines[-1] += " (Stock: **1,120**)"
    return _Message(MUDAE_ID, "\n".join(lines), message_id=ids)


def _game_steps(rewards_order=ORDER, rewards_last=True, extra=()):
    from src.bot.rewards import REWARDS_PLACEHOLDER

    steps = [
        ("new", _Message(PLAYER, "$oc")),
        ("new", _board_from({}, message_id=BOARD_ID)),
        *extra,
        ("new", _Message(MUDAE_ID, REWARDS_PLACEHOLDER, message_id=REWARDS_ID)),
    ]
    for n in range(1, 5):
        steps.append(
            ("edit", _board_from({c: FINAL[c] for c in ORDER[:n]}, message_id=BOARD_ID))
        )
        steps.append(("edit", _rewards(rewards_order[:n])))
    final_board = ("edit", _board_from(FINAL, clicked=ORDER, message_id=BOARD_ID))
    final_rewards = ("edit", _rewards(rewards_order))
    steps += (
        [final_board, final_rewards] if rewards_last else [final_rewards, final_board]
    )
    return steps


def _play_game(service, stats, **kwargs):
    from src.bot.totals import StatsStore

    stats = stats if stats is not None else StatsStore()
    service.auto_users.add(PLAYER)
    try:
        steps = _game_steps(**kwargs)
        _play(service, *steps, stats=stats)
    finally:
        service.auto_users.discard(PLAYER)
    end = steps[1][1].replies[0].edits[-1]
    return stats, {f.name: f.value for f in end["embed"].fields}


def test_a_checked_game_is_recorded_with_mudaes_reward_amounts(service):
    from src.solver.board import cell_index

    stats, fields = _play_game(service, None)
    totals = stats.all.oc
    assert totals.games == 1
    assert totals.spheres_gained == 2 * 420
    assert totals.clicked == {
        "BLUE": 0, "TEAL": 0, "GREEN": 1, "YELLOW": 1, "ORANGE": 2, "RED": 1,
    }  # fmt: skip
    followed, picks = fields["Solver picks followed"].split(" of ")
    assert (totals.picks_followed, totals.picks) == (int(followed), int(picks))
    assert totals.red_cells[cell_index("A1")] == 1
    assert stats.players[PLAYER].oc == totals


def test_rewards_that_catch_up_after_the_board_ends_still_count(service):
    stats, _ = _play_game(service, None, rewards_last=False)
    assert stats.all.oc.games == 1


def test_rewards_in_a_different_order_are_not_recorded(service):
    stats, _ = _play_game(service, None, rewards_order=["A2", "A1", "B1", "B2", "A3"])
    assert stats.all.oc.games == 0
    assert stats.players == {}


def test_another_board_at_the_same_time_means_the_game_is_left_out(service):
    other = ("new", _board_from({}, message_id=_at(200)))
    stats, _ = _play_game(service, None, extra=[other])
    assert stats.all.oc.games == 0


def test_a_game_with_no_rewards_message_is_left_out(service):
    from src.bot.totals import StatsStore

    stats = StatsStore()
    service.auto_users.add(PLAYER)
    try:
        steps = [s for s in _game_steps() if s[1].id != REWARDS_ID]
        _play(service, *steps, stats=stats)
    finally:
        service.auto_users.discard(PLAYER)
    assert stats.all.oc.games == 0


def test_games_the_bot_did_not_auto_read_never_count(service):
    from src.bot.totals import StatsStore

    stats = StatsStore()
    _play(service, *_game_steps(), stats=stats)
    assert stats.all.oc.games == 0


def test_saved_stats_hold_no_message_ids(service, tmp_path):
    from src.bot.totals import StatsStore

    paths = tmp_path / "stats.json", tmp_path / "my_stats.json"
    _play_game(service, StatsStore(*paths))
    global_text, players_text = (p.read_text() for p in paths)
    for text in (global_text, players_text):
        assert str(BOARD_ID) not in text
        assert str(REWARDS_ID) not in text
        assert "1120" not in text and "1,120" not in text
    assert set(json.loads(global_text)) == {"version", "oc", "oq"}
    assert set(json.loads(players_text)["players"]) == {str(PLAYER)}
    assert StatsStore(*paths).all.oc.games == 1


def test_autoread_on_message_mentions_the_stats(service):
    from src.bot.commands import set_auto

    text = set_auto(service, 42, on=True)
    service.auto_users.discard(42)
    assert "/my-stats" in text and "/global-stats" in text


def test_a_failed_game_over_edit_still_records_the_game(service, monkeypatch):
    from src.bot.totals import StatsStore

    monkeypatch.setattr(_FakeReply, "fail_game_over", True)
    stats = StatsStore()
    service.auto_users.add(PLAYER)
    try:
        tracker, _ = _play(service, *_game_steps(rewards_last=False), stats=stats)
    finally:
        service.auto_users.discard(PLAYER)
    assert len(tracker.errors) == 1
    assert stats.all.oc.games == 1


def test_two_game_over_edits_at_once_record_the_game_once(service):
    from src.bot.totals import StatsStore

    stats = StatsStore()
    steps = _game_steps(rewards_last=False)
    *early, fourth, fourth_rewards, last_rewards, last_board = steps

    async def run():
        tracker = AutoTracker(service, stats)
        for kind, message in [*early, fourth_rewards, last_rewards]:
            if kind == "new":
                await tracker.on_message(message)
            else:
                await tracker.on_message_edit(message)
        # The 4th click is still being solved when two game-over edits arrive.
        await asyncio.gather(
            tracker.on_message_edit(fourth[1]),
            tracker.on_message_edit(last_board[1]),
            tracker.on_message_edit(last_board[1]),
        )

    service.auto_users.add(PLAYER)
    try:
        asyncio.run(run())
    finally:
        service.auto_users.discard(PLAYER)
    assert stats.all.oc.games == 1
