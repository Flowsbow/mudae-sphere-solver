import asyncio
import io

import discord
import pytest
from discord import app_commands
from PIL import Image
from test_bot import _FakeCommandInteraction, _FakeInteraction, _FakeModalInteraction

from src.bot.commands import IMAGE_NAME, OcService
from src.bot.oq import AddOqSphereModal, OqBoardView, OqService, register_oq
from src.render.board_image import render_oq
from src.solver.board import BoardInputError, cell_index
from src.solver.modes.oq import BASE_PAYOUT, PURPLE, RED, RED_SHOWN
from src.solver.oq_board import add_cells, parse_board
from src.solver.oq_ev import HIDDEN
from src.solver.payouts import with_bonus

# Cells from Flow's finished $oq game in data/mudae/oq_finished.txt.
THREE_CLICKS = "C3B B4G A1T"
EXACT_ENDGAME = "A1T A5T B2T B4G A4P C5P"  # 4 paid clicks used, 3 left
FINISHED = "A1T A5T B2T B4G B5G C3B D3T A4P C5P"  # all 7 paid clicks used


@pytest.fixture(scope="module")
def service():
    return OqService(OcService())


def test_base_payouts_with_flows_bonus_match_the_observed_ones():
    # Seen in Flow's $oq games at +6 / 25%, 2026-10-03.
    pay = with_bonus(BASE_PAYOUT, 6, 25)
    assert [pay[0], pay[1], pay[2], pay[PURPLE], pay[RED]] == [20, 33, 51, 14, 195]


def test_parse_reads_counts_purples_and_the_red():
    codes = parse_board("C3B B4G A1T")
    assert codes[cell_index("C3")] == 0
    assert codes[cell_index("B4")] == 2
    assert codes[cell_index("A1")] == 1
    assert codes.count(HIDDEN) == 22
    assert parse_board("C3 B B4 G A1 T") == codes
    shown = parse_board("A1P B1P C1P E5R")
    assert shown[cell_index("E5")] == RED_SHOWN


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Z9B", "not a cell"),
        ("A1X", "color must be one of"),
        ("A1B A1T", "listed twice"),
        ("A1P B1P C1P", "Add both at once"),
        ("E5R", "only appears after 3 purples"),
        ("A1P B1P C1P D1P", "only 3 purples"),
    ],
)
def test_parse_rejects_bad_boards(text, message):
    with pytest.raises(BoardInputError, match=message):
        parse_board(text)


def test_adding_r_on_the_shown_red_means_it_was_clicked():
    codes = add_cells(parse_board("A1P B1P"), "C1 P E5 R")
    assert codes[cell_index("E5")] == RED_SHOWN
    codes = add_cells(codes, "E5 R")
    assert codes[cell_index("E5")] == RED


def test_adding_an_already_revealed_cell_is_refused():
    with pytest.raises(BoardInputError, match="already revealed"):
        add_cells(parse_board("C3B"), "C3 T")


def test_new_game_uses_the_early_rule(service):
    analysis = asyncio.run(service.analyze(parse_board("")))
    assert analysis.clicks_left == 7
    assert not analysis.exact
    assert analysis.best is not None


def _run_oq(service, board):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    register_oq(tree, service)
    interaction = _FakeCommandInteraction(1)
    asyncio.run(tree.get_command("oq").callback(interaction, board=board))
    return interaction


def test_oq_is_a_user_installable_command_with_an_optional_board(service):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    register_oq(tree, service)
    command = tree.get_command("oq")
    (board,) = command.parameters
    assert board.name == "board" and not board.required
    payload = command.to_dict(tree)
    assert sorted(payload["integration_types"]) == [0, 1]
    assert sorted(payload["contexts"]) == [0, 1, 2]


def test_oq_replies_with_the_likeliest_purple_and_an_image(service):
    interaction = _run_oq(service, THREE_CLICKS)
    ((_, sent),) = interaction.followup.sent
    # A1 = 1 with B2 ruled out by C3 = 0: one purple between A2 and B1.
    assert sent["embed"].title in ("Click A2", "Click B1")
    assert "**50%** chance it's purple" in sent["embed"].description
    assert sent["file"].filename == IMAGE_NAME
    add, credit = sent["view"].children
    assert add.label == "Add a sphere" and not add.disabled
    assert credit.url == "https://github.com/Flowsbow/mudae-sphere-solver"


def test_last_three_clicks_are_searched_exactly(service):
    interaction = _run_oq(service, EXACT_ENDGAME)
    ((_, sent),) = interaction.followup.sent
    assert "spheres expected from the rest of the game (3 paid clicks left)" in (
        sent["embed"].description
    )


def test_a_finished_board_says_game_over_and_disables_the_button(service):
    interaction = _run_oq(service, FINISHED)
    ((_, sent),) = interaction.followup.sent
    assert sent["embed"].title == "Game over: no paid clicks left"
    assert sent["view"].add_sphere.disabled


def test_a_typo_gets_a_private_error_and_no_board(service):
    interaction = _run_oq(service, "A1X")
    assert interaction.followup.sent == []
    ((text, ephemeral),) = interaction.response.sent
    assert "color must be one of" in text and ephemeral


def test_adding_a_sphere_updates_the_same_message(service):
    async def run():
        view = OqBoardView(service, parse_board(THREE_CLICKS), 1, BASE_PAYOUT)
        modal = AddOqSphereModal(view)
        modal.sphere._value = "A2 P"
        interaction = _FakeModalInteraction(1)
        await modal.on_submit(interaction)
        return view, interaction

    view, interaction = asyncio.run(run())
    assert view.codes[cell_index("A2")] == PURPLE
    (edit,) = interaction.edits
    assert edit["view"] is view
    assert edit["attachments"][0].filename == IMAGE_NAME


def test_only_the_command_user_can_update_the_board(service):
    async def run():
        view = OqBoardView(service, parse_board(""), 1, BASE_PAYOUT)
        stranger = _FakeInteraction(2)
        return await view.interaction_check(stranger), stranger

    allowed, stranger = asyncio.run(run())
    assert allowed is False
    assert stranger.response.sent[0][1] is True


def test_render_draws_a_board_image(service):
    codes = parse_board(THREE_CLICKS)
    png = render_oq(codes, asyncio.run(service.analyze(codes)))
    assert Image.open(io.BytesIO(png)).size == (398, 398)


def test_oq_uses_the_players_sphere_bonus():
    from src.bot.commands import set_sphere_bonus

    settings = OcService()
    set_sphere_bonus(settings, 1, None, 6, 25)
    service = OqService(settings)
    assert service.payouts_for(1, None) == with_bonus(BASE_PAYOUT, 6, 25)
    assert service.payouts_for(2, None) == BASE_PAYOUT
    interaction = _run_oq(service, THREE_CLICKS)
    ((_, sent),) = interaction.followup.sent
    assert sent["view"].payouts == with_bonus(BASE_PAYOUT, 6, 25)
    assert "your /spherebonus values" in sent["embed"].footer.text


def test_render_colors_counts_and_shades_hidden_tiles_by_purple_odds(service):
    from src.render.board_image import GAP, LABEL, PAD, TILE

    codes = parse_board(THREE_CLICKS)
    img = Image.open(io.BytesIO(render_oq(codes, asyncio.run(service.analyze(codes)))))

    def corner(name):
        r, c = divmod(cell_index(name), 5)
        return img.getpixel(
            (PAD + LABEL + c * (TILE + GAP) + 12, PAD + LABEL + r * (TILE + GAP) + 12)
        )[:3]

    red, green, blue = corner("C3")  # count 0: a blue block
    assert blue > red + 80
    likely, never = corner("A2"), corner("B2")  # 50% purple vs 0%
    assert likely[0] > never[0] + 30 and likely[2] > never[2] + 30


def test_once_every_purple_is_known_tiles_show_payouts(service):
    interaction = _run_oq(service, "A2P B2P C2P D4R E1B")
    ((_, sent),) = interaction.followup.sent
    assert sent["embed"].title == "Click D4"  # the red, not an equal-total 35
    assert sent["embed"].footer.text.startswith("Every purple is known: +N")
