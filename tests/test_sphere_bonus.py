import asyncio
import json

import discord
import pytest
from discord import app_commands
from test_auto import PLAYER, _board_from, _Message, _play
from test_bot import _FakeCommandInteraction

import src.bot.commands as commands
from src.bot.commands import (
    MAX_BONUS,
    BoardView,
    OcService,
    build_stats_reply,
    register,
    set_sphere_bonus,
)
from src.bot.settings import SettingsFileError
from src.solver.board import BoardState, Color
from src.solver.modes.oc import BASE_PAYOUT
from src.solver.payouts import with_bonus
from src.solver.stats import Step, game_stats

SERVER = 99
OTHER_SERVER = 98
# Flow's other server, 2026-10-03: +6 from $kt, 25% reported by Flow.
FLOW_BONUS = (6, 25)
ONE_CLICK_LEFT = "D4R B2T C4G E4O"


def test_bonus_matches_the_observed_payouts():
    pay = with_bonus(BASE_PAYOUT, *FLOW_BONUS)
    # Seen in Flow's $oq games, 2026-10-03.
    assert [pay[Color.BLUE], pay[Color.TEAL], pay[Color.GREEN], pay[Color.RED]] == [
        20,
        33,
        51,
        195,
    ]
    # Not seen yet: what the formula predicts.
    assert [pay[Color.YELLOW], pay[Color.ORANGE]] == [76, 120]


def test_observed_purple():
    assert with_bonus({"purple": 5}, *FLOW_BONUS) == {"purple": 14}


def test_halves_round_up_like_the_observed_teal():
    # 1.25 x 26 = 32.5. Python's round() would give 32; Mudae paid 33.
    assert with_bonus({"teal": 20}, *FLOW_BONUS) == {"teal": 33}


def test_no_bonus_leaves_base_values():
    assert with_bonus(BASE_PAYOUT, 0, 0) == BASE_PAYOUT


def test_bonus_survives_a_restart_for_that_server_only(tmp_path):
    path = tmp_path / "settings.json"
    set_sphere_bonus(OcService(path), 11, SERVER, *FLOW_BONUS)
    after = OcService(path)
    assert after.payouts_for(11, SERVER) == with_bonus(BASE_PAYOUT, *FLOW_BONUS)
    assert after.payouts_for(11, OTHER_SERVER) == BASE_PAYOUT
    assert after.payouts_for(11, None) == BASE_PAYOUT
    assert after.payouts_for(12, SERVER) == BASE_PAYOUT


def test_a_dm_bonus_is_saved_too(tmp_path):
    path = tmp_path / "settings.json"
    set_sphere_bonus(OcService(path), 11, None, *FLOW_BONUS)
    assert OcService(path).payouts_for(11, None) == with_bonus(BASE_PAYOUT, *FLOW_BONUS)


def test_giving_one_number_keeps_the_other(tmp_path):
    service = OcService(tmp_path / "settings.json")
    set_sphere_bonus(service, 11, SERVER, flat=6)
    set_sphere_bonus(service, 11, SERVER, percent=25)
    assert service.bonus_for[(11, SERVER)] == FLOW_BONUS


def test_setting_both_to_zero_removes_the_bonus_and_saves(tmp_path):
    path = tmp_path / "settings.json"
    service = OcService(path)
    set_sphere_bonus(service, 11, SERVER, *FLOW_BONUS)
    set_sphere_bonus(service, 11, SERVER, 0, 0)
    assert json.loads(path.read_text())["sphere_bonus"] == []
    assert OcService(path).payouts_for(11, SERVER) == BASE_PAYOUT


def test_no_numbers_just_shows_the_values(tmp_path):
    path = tmp_path / "settings.json"
    text = set_sphere_bonus(OcService(path), 11, SERVER)
    assert not path.exists()
    assert "+0 flat, +0%" in text
    assert "Blue 10 · Teal 20 · Green 35 · Yellow 55 · Orange 90 · Red 150" in text


def test_reply_lists_the_new_values():
    text = set_sphere_bonus(OcService(), 11, SERVER, *FLOW_BONUS)
    assert "this server: +6 flat, +25%" in text
    assert "Blue 20 · Teal 33 · Green 51 · Yellow 76 · Orange 120 · Red 195" in text


def test_a_bonus_entry_missing_a_number_stops_startup(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"sphere_bonus": [{"user": 1, "server": null, "flat": 6}]}')
    with pytest.raises(SettingsFileError, match="Fix it or delete it"):
        OcService(path)


def test_analysis_uses_the_players_values():
    service = OcService()
    state = BoardState.parse(ONE_CLICK_LEFT)
    pay = with_bonus(BASE_PAYOUT, *FLOW_BONUS)
    analysis = asyncio.run(service.analyze(state, pay))
    # With one click left the best move is just the best single-click average,
    # computed here from the color odds, which don't depend on payouts.
    best_single_click = max(
        sum(p * pay[color] for color, p in probs.items())
        for probs in analysis.color_probs.values()
    )
    assert analysis.value == pytest.approx(best_single_click)
    base = asyncio.run(service.analyze(state))
    assert analysis.value > base.value + 1


def test_the_solver_cache_drops_the_least_recently_used(monkeypatch):
    monkeypatch.setattr(commands, "MAX_SOLVERS", 2)
    service = OcService()
    state = BoardState.parse(ONE_CLICK_LEFT)
    a, b, c = (with_bonus(BASE_PAYOUT, flat, 0) for flat in (1, 2, 3))
    for table in (a, b, a, c):
        asyncio.run(service.analyze(state, table))
    assert list(service.solvers) == [
        tuple(table[color] for color in Color) for table in (a, c)
    ]


def test_game_over_screen_uses_the_players_values():
    pay = with_bonus(BASE_PAYOUT, *FLOW_BONUS)
    steps = [Step(0, Color.RED, None), Step(1, Color.ORANGE, None)]
    stats = game_stats(steps, pay, expected=None)
    cells = (Color.RED, Color.ORANGE) + (None,) * 23
    embed, _ = build_stats_reply(stats, cells, frozenset({0, 1}), False, pay)
    assert embed.title == "Game over: 315 spheres"
    clicks = {f.name: f.value for f in embed.fields}["Your clicks"]
    assert "+195" in clicks and "+120" in clicks
    assert embed.footer.text.startswith("Your /spherebonus values")


def test_expected_total_counts_earlier_clicks_in_the_players_values():
    service = OcService()
    pay = with_bonus(BASE_PAYOUT, *FLOW_BONUS)
    state = BoardState.parse(ONE_CLICK_LEFT)

    async def make():
        analysis = await service.analyze(state, pay)
        return BoardView(service, state, 1, analysis, payouts=pay), analysis

    view, analysis = asyncio.run(make())
    red, teal, green, orange = 195, 33, 51, 120
    assert view.expected == pytest.approx(red + teal + green + orange + analysis.value)


def test_spherebonus_command_takes_two_optional_bounded_numbers():
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    register(tree, OcService())
    flat, percent = tree.get_command("spherebonus").parameters
    assert [flat.name, percent.name] == ["flat", "percent"]
    assert not flat.required and not percent.required
    assert (flat.min_value, flat.max_value) == (0, MAX_BONUS)
    assert (percent.min_value, percent.max_value) == (0, MAX_BONUS)


def _run_oc(service, server_id):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    register(tree, service)
    interaction = _FakeCommandInteraction(PLAYER)
    interaction.guild_id = server_id
    asyncio.run(tree.get_command("oc").callback(interaction, board=ONE_CLICK_LEFT))
    ((_, sent),) = interaction.followup.sent
    return sent


def test_oc_uses_the_bonus_for_the_server_it_runs_in():
    service = OcService()
    set_sphere_bonus(service, PLAYER, SERVER, *FLOW_BONUS)
    here = _run_oc(service, SERVER)
    pay = with_bonus(BASE_PAYOUT, *FLOW_BONUS)
    assert here["view"].payouts == pay
    state = BoardState.parse(ONE_CLICK_LEFT)
    value = asyncio.run(service.analyze(state, pay)).value
    assert f"**{value:.1f}**" in here["embed"].description
    assert "/spherebonus" in here["embed"].footer.text
    elsewhere = _run_oc(service, OTHER_SERVER)
    assert elsewhere["view"].payouts == BASE_PAYOUT
    assert "base values" in elsewhere["embed"].footer.text


def test_auto_mode_uses_the_bonus_for_the_server_the_board_is_in():
    service = OcService()
    service.auto_users.add(PLAYER)
    set_sphere_bonus(service, PLAYER, SERVER, *FLOW_BONUS)
    board = _board_from({"D4": "R", "B2": "T", "C4": "G", "E4": "O"})
    board.guild = type("Guild", (), {"id": SERVER})()
    _play(service, ("new", _Message(PLAYER, "$oc")), ("new", board))
    (reply,) = board.replies
    assert reply.first["view"].payouts == with_bonus(BASE_PAYOUT, *FLOW_BONUS)
