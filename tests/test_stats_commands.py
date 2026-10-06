import asyncio

import discord
import pytest
from discord import app_commands
from test_totals import PLAYER, oc, oq

from src.bot.stats_commands import (
    RING_EVERY_BOARD,
    RING_SOLVER,
    red_grid,
    register_stats,
    stats_embed,
)
from src.bot.totals import StatsStore, Totals
from src.solver.board import N_CELLS, cell_index


def _fields(embed):
    return {f.name: f.value for f in embed.fields}


def test_ring_shares_match_the_readme():
    # README, "Model assumption": 66.7% under the solver's model, 14.3% otherwise.
    assert f"{RING_SOLVER:.1%}" == "66.7%"
    assert f"{RING_EVERY_BOARD:.1%}" == "14.3%"


def test_no_games_yet_says_so_and_shows_no_numbers():
    embed = stats_embed(Totals(), "Global stats", "footer")
    assert "No games yet" in embed.description
    assert embed.fields == []


def test_stats_show_every_figure_with_its_game_count():
    totals = Totals()
    for game in (oc(), oc(), oc(followed=3, red="C2"), oq()):
        totals.add(game)
    embed = stats_embed(totals, "Global stats", "footer")
    fields = _fields(embed)
    assert "3 `$oc` and 1 `$oq` game" in embed.description
    assert fields["Spheres gained"] == f"{3 * 999 + 455:,}"
    assert fields["$oc: spheres clicked"].startswith("Blue 0 · Teal 0 · Green 3")
    assert "In 2 games where every pick was followed" in fields["$oc: solver accuracy"]
    assert "± 0.0" in fields["$oc: solver accuracy"]
    assert (
        "Red found in 2 of 2 (100.0%); predicted 99.98%"
        in (fields["$oc: solver accuracy"])
    )
    where = fields["$oc: where red was"]
    assert "Outer ring in 2 of 3 games (66.7% ± 27.2%)" in where
    assert "expects 0.1 each" in where
    assert "Rainbow 0" in fields["$oq: spheres clicked"]
    assert "80.0%" in fields["$oq: solver accuracy"]
    assert all(len(value) <= 1024 for value in fields.values())


def test_red_grid_puts_each_count_in_its_cell():
    cells = [0] * N_CELLS
    cells[cell_index("A1")] = 12
    cells[cell_index("D4")] = 3
    lines = red_grid(cells).strip("`\n").splitlines()
    assert lines[0].split() == ["1", "2", "3", "4", "5"]
    assert lines[1].split() == ["A", "12", "0", "0", "0", "0"]
    assert lines[3].split() == ["C", "0", "0", "-", "0", "0"]
    assert lines[4].split() == ["D", "0", "0", "0", "3", "0"]


class _Response:
    def __init__(self):
        self.sent = []

    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


def _run(command, user_id, **options):
    user = type("User", (), {"id": user_id})()
    interaction = type("I", (), {"user": user, "response": _Response()})()
    asyncio.run(command.callback(interaction, **options))
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
    assert "1 `$oc` and 1 `$oq` game" in sent["embed"].description
    (credit,) = sent["view"].children
    assert credit.url == "https://github.com/Flowsbow/mudae-sphere-solver"


def test_my_stats_is_private_and_only_mine(tree_and_store):
    tree, _ = tree_and_store
    ((_, sent),) = _run(tree.get_command("my-stats"), PLAYER)
    assert sent["ephemeral"] is True
    assert "1 `$oc` and 0 `$oq` games" in sent["embed"].description
    ((_, other),) = _run(tree.get_command("my-stats"), 12345)
    assert "No games yet" in other["embed"].description


def test_my_stats_delete_removes_only_mine(tree_and_store):
    tree, store = tree_and_store
    ((text, sent),) = _run(tree.get_command("my-stats"), PLAYER, delete=True)
    assert text == "Deleted your saved stats."
    assert sent["ephemeral"] is True
    assert PLAYER not in store.players
    assert store.all.oc.games == 1
    ((text, _),) = _run(tree.get_command("my-stats"), PLAYER, delete=True)
    assert text == "You have no saved stats."


@pytest.mark.parametrize("name", ["global-stats", "my-stats"])
def test_stats_commands_can_be_installed_to_a_user_account(tree_and_store, name):
    tree, _ = tree_and_store
    payload = tree.get_command(name).to_dict(tree)
    assert sorted(payload["integration_types"]) == [0, 1]
    assert sorted(payload["contexts"]) == [0, 1, 2]
