import asyncio
import io

import discord
import pytest
from discord import app_commands
from PIL import Image
from test_totals import PLAYER, oc, oq

from src.bot.stats_commands import (
    DELETE_PROMPT,
    RING_EVERY_BOARD,
    RING_SOLVER,
    STATS_IMAGE,
    register_stats,
    stats_message,
)
from src.bot.totals import OhResult, StatsStore, Totals
from src.render.stats_image import render_stats


def _fields(embed):
    return {f.name: f.value for f in embed.fields}


def test_ring_shares_match_the_readme():
    # README, "Model assumption": 66.7% under the solver's model, 14.3% otherwise.
    assert f"{RING_SOLVER:.1%}" == "66.7%"
    assert f"{RING_EVERY_BOARD:.1%}" == "14.3%"


def test_no_games_yet_says_so_and_sends_no_image():
    embed, file = stats_message(Totals(), "Global stats", "footer")
    assert "No games yet" in embed.description
    assert embed.fields == []
    assert file is None
    assert render_stats(Totals()) is None


def _totals():
    totals = Totals()
    for game in (oc(), oc(), oc(followed=3, red="C2"), oq()):
        totals.add(game)
    return totals


def test_stats_text_keeps_what_the_image_doesnt_show():
    embed, file = stats_message(_totals(), "Global stats", "footer")
    fields = _fields(embed)
    assert "3 `$oc`, 1 `$oq` and 0 `$oh` games" in embed.description
    assert fields["Spheres gained"] == f"{3 * 999 + 455:,}"
    assert "In 2 games where every pick was followed" in fields["$oc"]
    assert "Red found in 100.0%; predicted 99.98%" in fields["$oc"]
    assert "outer ring in 66.7% ± 27.2% of 3 games" in fields["$oc"]
    assert "80.0%" in fields["$oq"]
    assert "Rainbow on 0 of 1 collected 4th purples" in fields["$oq"]
    assert "$oh" not in fields
    assert all(len(value) <= 1024 for value in fields.values())
    assert embed.image.url == f"attachment://{STATS_IMAGE}"
    assert file.filename == STATS_IMAGE


def test_stats_image_is_a_png_that_grows_with_each_game():
    totals = _totals()
    two_games = Image.open(io.BytesIO(render_stats(totals)))
    totals.add(OhResult(("LIGHT", "DARK", "PRIZE"), 80, 2, 1))
    three_games = Image.open(io.BytesIO(render_stats(totals)))
    assert two_games.format == three_games.format == "PNG"
    assert two_games.width == three_games.width == 640
    assert three_games.height > two_games.height


def test_oh_games_get_their_own_line():
    totals = Totals()
    totals.add(OhResult(("BLUE", "PRIZE"), 10, 2, 2))
    embed, _ = stats_message(totals, "Global stats", "footer")
    assert "0 `$oc`, 0 `$oq` and 1 `$oh` game read" in embed.description
    assert "no prediction to check" in _fields(embed)["$oh"]


class _Response:
    def __init__(self):
        self.sent = []

    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))

    async def edit_message(self, **kwargs):
        self.sent.append((kwargs["content"], kwargs))


def _interaction(user_id):
    user = type("User", (), {"id": user_id})()
    return type("I", (), {"user": user, "response": _Response()})()


def _run(command, user_id, **options):
    interaction = _interaction(user_id)
    asyncio.run(command.callback(interaction, **options))
    return interaction.response.sent


def _press(button, user_id):
    interaction = _interaction(user_id)
    asyncio.run(button.callback(interaction))
    return interaction.response.sent


@pytest.fixture
def tree_and_store():
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    store = StatsStore()
    store.record(PLAYER, oc())
    store.record(7, oq())
    register_stats(tree, store)
    return tree, store


def test_global_stats_is_public_and_counts_everyone(tree_and_store):
    tree, _ = tree_and_store
    ((_, sent),) = _run(tree.get_command("global-stats"), 99)
    assert sent.get("ephemeral", False) is False
    assert "1 `$oc`, 1 `$oq` and 0 `$oh` games" in sent["embed"].description
    assert sent["file"].filename == STATS_IMAGE
    (credit,) = sent["view"].children
    assert credit.url == "https://github.com/Flowsbow/mudae-sphere-solver"


def test_my_stats_is_private_and_only_mine(tree_and_store):
    tree, _ = tree_and_store
    ((_, sent),) = _run(tree.get_command("my-stats"), PLAYER)
    assert sent["ephemeral"] is True
    assert "1 `$oc`, 0 `$oq` and 0 `$oh` games" in sent["embed"].description
    ((_, other),) = _run(tree.get_command("my-stats"), 12345)
    assert "No games yet" in other["embed"].description


def test_my_stats_has_no_delete_option(tree_and_store):
    tree, _ = tree_and_store
    assert tree.get_command("my-stats").to_dict(tree)["options"] == []


def test_delete_stats_asks_first_and_deletes_nothing_yet(tree_and_store):
    tree, store = tree_and_store
    ((text, sent),) = _run(tree.get_command("delete-stats"), PLAYER)
    assert text == DELETE_PROMPT
    assert sent["ephemeral"] is True
    assert PLAYER in store.players


def test_confirm_deletes_only_mine(tree_and_store):
    tree, store = tree_and_store
    ((_, sent),) = _run(tree.get_command("delete-stats"), PLAYER)
    ((text, edit),) = _press(sent["view"].confirm, PLAYER)
    assert text == "Deleted your saved stats."
    assert edit["view"] is None
    assert PLAYER not in store.players
    assert 7 in store.players
    assert store.all.oc.games == 1
    ((text, _),) = _press(sent["view"].confirm, PLAYER)
    assert text == "You have no saved stats."


def test_cancel_keeps_my_stats(tree_and_store):
    tree, store = tree_and_store
    ((_, sent),) = _run(tree.get_command("delete-stats"), PLAYER)
    ((text, edit),) = _press(sent["view"].cancel, PLAYER)
    assert text == "Cancelled. Your stats are still saved."
    assert edit["view"] is None
    assert PLAYER in store.players


@pytest.mark.parametrize("name", ["global-stats", "my-stats", "delete-stats"])
def test_stats_commands_can_be_installed_to_a_user_account(tree_and_store, name):
    tree, _ = tree_and_store
    payload = tree.get_command(name).to_dict(tree)
    assert sorted(payload["integration_types"]) == [0, 1]
    assert sorted(payload["contexts"]) == [0, 1, 2]
