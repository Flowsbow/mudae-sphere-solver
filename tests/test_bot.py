import asyncio
import io

import discord
import pytest
from discord import app_commands
from PIL import Image

from src.bot.commands import (
    IMAGE_NAME,
    AddSphereModal,
    BoardView,
    OcService,
    add_reveals,
    build_reply,
    register,
)
from src.render.board_image import render
from src.solver.board import BoardInputError, BoardState
from src.solver.modes.oc import BASE_PAYOUT


@pytest.fixture(scope="module")
def service():
    return OcService()


def _analyze(service, text):
    state = BoardState.parse(text)
    return state, asyncio.run(service.analyze(state))


def test_register_adds_the_oc_command_with_optional_board_and_auto(service):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    register(tree, service)
    command = tree.get_command("oc")
    assert command is not None
    board, auto = command.parameters
    assert board.name == "board"
    assert not board.required
    assert auto.name == "auto"
    assert not auto.required
    assert [c.value for c in auto.choices] == ["on", "off"]


def test_reply_names_the_best_cell_and_attaches_the_image(service):
    state, analysis = _analyze(service, "D4R B2T")
    embed, file = build_reply(analysis, render(state, analysis, BASE_PAYOUT))
    assert embed.title == "Click C4"
    assert "181.8" in embed.description
    assert "3 clicks" in embed.description
    assert embed.image.url == f"attachment://{IMAGE_NAME}"
    assert file.filename == IMAGE_NAME
    assert Image.open(io.BytesIO(file.fp.read())).size == (398, 398)


def test_reply_says_one_click_in_the_singular(service):
    state, analysis = _analyze(service, "D4R B2T C4G E4O")
    embed, _ = build_reply(analysis, render(state, analysis, BASE_PAYOUT))
    assert "1 click " in embed.description


def test_reply_for_a_finished_game(service):
    state, analysis = _analyze(service, "D4R D5O E4O C5Y E3Y")
    embed, _ = build_reply(analysis, render(state, analysis, BASE_PAYOUT))
    assert embed.title.startswith("Game over")


def test_concurrent_requests_all_get_answers(service):
    boards = ["D4R B2T", "A1B", "C3T D4B", "B2Y"]

    async def run_all():
        return await asyncio.gather(
            *(service.analyze(BoardState.parse(b)) for b in boards)
        )

    results = asyncio.run(run_all())
    assert all(r.best is not None for r in results)


def test_add_reveals_accepts_cell_space_color():
    state = add_reveals(BoardState.parse("D4R"), "c4 g")
    assert state == BoardState.parse("D4R C4G")


def test_add_reveals_accepts_several_at_once():
    state = add_reveals(BoardState(), "D4R B2T")
    assert state == BoardState.parse("D4R B2T")


@pytest.mark.parametrize("text", ["", "C4", "Z9 G", "D4 R"])
def test_add_reveals_rejects_bad_or_repeated_input(text):
    with pytest.raises(BoardInputError):
        add_reveals(BoardState.parse("D4R"), text)


def _view(service, text, owner=1):
    async def make():
        return BoardView(service, BoardState.parse(text), owner)

    return asyncio.run(make())


def test_manual_view_has_add_a_sphere_then_the_credit_link(service):
    view = _view(service, "D4R", owner=99)
    add, credit = view.children
    assert add.label == "Add a sphere"
    assert not add.disabled
    assert credit.url == "https://github.com/Flowsbow/mudae-sphere-solver"


def test_auto_view_has_only_the_credit_link(service):
    async def make():
        return BoardView(service, BoardState.parse("D4R"), 99, manual=False)

    (credit,) = asyncio.run(make()).children
    assert credit.url == "https://github.com/Flowsbow/mudae-sphere-solver"


def test_button_is_disabled_once_all_clicks_are_used(service):
    view = _view(service, "D4R D5O E4O C5Y E3Y")
    assert view.add_sphere.disabled
    assert view.children[-1].url == "https://github.com/Flowsbow/mudae-sphere-solver"


class _FakeResponse:
    def __init__(self):
        self.sent = []

    async def send_message(self, content, ephemeral=False):
        self.sent.append((content, ephemeral))


class _FakeInteraction:
    def __init__(self, user_id):
        self.user = type("User", (), {"id": user_id})()
        self.guild_id = None
        self.response = _FakeResponse()


def test_only_the_command_user_can_press_the_button(service):
    view = _view(service, "D4R", owner=1)
    owner, stranger = _FakeInteraction(1), _FakeInteraction(2)
    assert asyncio.run(view.interaction_check(owner)) is True
    assert asyncio.run(view.interaction_check(stranger)) is False
    assert stranger.response.sent[0][1] is True


class _FakeModalResponse(_FakeResponse):
    def __init__(self):
        super().__init__()
        self.deferred = False

    async def defer(self):
        self.deferred = True


class _FakeModalInteraction(_FakeInteraction):
    def __init__(self, user_id):
        super().__init__(user_id)
        self.response = _FakeModalResponse()
        self.edits = []

    async def edit_original_response(self, **kwargs):
        self.edits.append(kwargs)


def _submit(service, board, typed):
    async def run():
        view = BoardView(service, BoardState.parse(board), 1)
        modal = AddSphereModal(view)
        modal.sphere._value = typed
        interaction = _FakeModalInteraction(1)
        await modal.on_submit(interaction)
        return view, interaction

    return asyncio.run(run())


def test_adding_a_sphere_edits_the_same_message_with_the_new_board(service):
    view, interaction = _submit(service, "B2T", "D4 R")
    assert interaction.response.deferred
    (edit,) = interaction.edits
    assert edit["embed"].title == "Click C4"
    assert edit["attachments"][0].filename == IMAGE_NAME
    assert edit["view"] is view
    assert view.state == BoardState.parse("D4R B2T")


def test_a_typo_in_the_popup_gets_a_private_error_and_no_edit(service):
    view, interaction = _submit(service, "B2T", "Q9 R")
    assert interaction.edits == []
    assert interaction.response.sent[0][1] is True
    assert view.state == BoardState.parse("B2T")


def test_colorblindmode_toggles_and_applies_to_later_boards(service):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    register(tree, service)
    command = tree.get_command("colorblindmode")
    assert command.parameters == []
    interaction = _FakeInteraction(7)

    asyncio.run(command.callback(interaction))
    assert service.letters_for[7] is True
    assert _view(service, "A1B", owner=7).letters
    asyncio.run(command.callback(interaction))
    assert service.letters_for[7] is False
    assert all(ephemeral for _, ephemeral in interaction.response.sent)
    service.letters_for.pop(7)


def test_solve_sphere_board_is_a_message_command(service):
    from discord.enums import AppCommandType

    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    register(tree, service)
    assert tree.get_command("Solve sphere board", type=AppCommandType.message)


class _FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))
        return object()


class _FakeCommandResponse(_FakeResponse):
    async def defer(self, thinking=False):
        self.thinking = thinking


class _FakeCommandInteraction(_FakeInteraction):
    def __init__(self, user_id):
        super().__init__(user_id)
        self.response = _FakeCommandResponse()
        self.followup = _FakeFollowup()


def _mudae_message(dump_name, author_id=None):
    from test_mudae_reader import _buttons_from_dump

    from src.bot.mudae_reader import MUDAE_ID

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
                },
            )()
            for b in buttons[r * 5 : r * 5 + 5]
        ]
        rows.append(type("Row", (), {"children": children})())
    author = type("Author", (), {"id": author_id or MUDAE_ID})()
    return type("Msg", (), {"author": author, "components": rows})()


def _right_click_solve(service, message):
    from discord.enums import AppCommandType

    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    register(tree, service)
    command = tree.get_command("Solve sphere board", type=AppCommandType.message)
    interaction = _FakeCommandInteraction(5)
    asyncio.run(command.callback(interaction, message))
    return interaction


def test_right_click_on_a_live_mudae_board_replies_with_the_solution(service):
    interaction = _right_click_solve(service, _mudae_message("oc_midgame.txt"))
    ((_, kwargs),) = interaction.followup.sent
    assert kwargs["embed"].title.startswith("Click ")
    assert "2 clicks" in kwargs["embed"].description
    assert kwargs["view"].state == BoardState.parse("A1R A3G B2Y")


def test_right_click_on_a_finished_game_says_it_is_over(service):
    interaction = _right_click_solve(service, _mudae_message("oc_finished.txt"))
    assert interaction.followup.sent == []
    assert "already over" in interaction.response.sent[0][0]


def test_right_click_on_someone_elses_message_is_refused(service):
    interaction = _right_click_solve(service, _mudae_message("oc_fresh.txt", 1))
    assert interaction.followup.sent == []
    assert "isn't from Mudae" in interaction.response.sent[0][0]


def test_fifth_sphere_in_the_popup_shows_the_stats_screen(service):
    async def run():
        state = BoardState.parse("D4R D5O E4O C5Y")
        analysis = await service.analyze(state)
        view = BoardView(service, state, 1, analysis)
        modal = AddSphereModal(view)
        modal.sphere._value = "E3 Y"
        interaction = _FakeModalInteraction(1)
        await modal.on_submit(interaction)
        return view, interaction

    view, interaction = asyncio.run(run())
    (edit,) = interaction.edits
    assert edit["embed"].title == "Game over: 440 spheres"
    fields = {f.name: f.value for f in edit["embed"].fields}
    # Cells typed into /oc have no click order, so they're listed in board order:
    # C5, D4, D5, E4, then the popup's E3.
    assert fields["Red"] == "Found on click 2"
    assert fields["Solver picks followed"].endswith("of 1")
    assert view.add_sphere.disabled
    assert view.children[-1].url == "https://github.com/Flowsbow/mudae-sphere-solver"


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("oc", "chat_input"),
        ("colorblindmode", "chat_input"),
        ("spherebonus", "chat_input"),
        ("Solve sphere board", "message"),
    ],
)
def test_commands_can_be_installed_to_a_user_account(service, name, kind):
    from discord.enums import AppCommandType

    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    register(tree, service)
    command = tree.get_command(name, type=AppCommandType[kind])
    payload = command.to_dict(tree)
    # Discord's codes: install 0 = server, 1 = user; context 0 = server, 1 = bot DM,
    # 2 = group DM or other DMs.
    assert sorted(payload["integration_types"]) == [0, 1]
    assert sorted(payload["contexts"]) == [0, 1, 2]
