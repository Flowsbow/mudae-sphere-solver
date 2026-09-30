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
                {"emoji": discord.PartialEmoji(name=b.emoji), "disabled": b.disabled},
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
    mid, end = reply.edits
    assert "2 clicks" in mid["embed"].description
    assert mid["view"].state == BoardState.parse("A1R A3G B2Y")
    assert end["embed"].title == "Game over"
    assert all(item.disabled for item in end["view"].children)
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
