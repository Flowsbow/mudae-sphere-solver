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


def test_register_adds_the_oc_command_with_an_optional_board_option(service):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    register(tree, service)
    command = tree.get_command("oc")
    assert command is not None
    (board,) = command.parameters
    assert board.name == "board"
    assert not board.required


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


def test_view_has_the_add_a_sphere_and_colorblind_buttons(service):
    view = _view(service, "D4R", owner=99)
    add, colorblind = view.children
    assert add.label == "Add a sphere"
    assert not add.disabled
    assert colorblind.label == "Colorblind: Off"


def test_button_is_disabled_once_all_clicks_are_used(service):
    view = _view(service, "D4R D5O E4O C5Y E3Y")
    assert view.add_sphere.disabled


class _FakeResponse:
    def __init__(self):
        self.sent = []

    async def send_message(self, content, ephemeral=False):
        self.sent.append((content, ephemeral))


class _FakeInteraction:
    def __init__(self, user_id):
        self.user = type("User", (), {"id": user_id})()
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


def test_colorblind_button_redraws_the_same_message_and_is_remembered(service):
    async def run():
        view = BoardView(service, BoardState.parse("D4R B2T"), 7)
        interaction = _FakeModalInteraction(7)
        await view.colorblind.callback(interaction)
        return view, interaction

    view, interaction = asyncio.run(run())
    (edit,) = interaction.edits
    assert view.letters
    assert view.colorblind.label == "Colorblind: On"
    assert edit["attachments"][0].filename == IMAGE_NAME
    assert service.letters_for[7] is True
    assert _view(service, "A1B", owner=7).letters
    service.letters_for.pop(7)
