import asyncio

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
    def __init__(self, kwargs):
        self.first = kwargs
        self.edits = []

    async def edit(self, **kwargs):
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


def _play(service, *steps):
    tracker = AutoTracker(service)

    async def run():
        results = []
        for kind, message in steps:
            if kind == "new":
                await tracker.on_message(message)
            else:
                await tracker.on_message_edit(message)
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
    assert reply.first["view"].children == []
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


def test_oc_auto_option_turns_auto_mode_on_and_off(service):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    register(tree, service)
    command = tree.get_command("oc")
    interaction = type("I", (), {"user": _Author(42), "response": _FakeResponse()})()

    asyncio.run(command.callback(interaction, auto="on"))
    assert 42 in service.auto_users
    asyncio.run(command.callback(interaction, auto="off"))
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
