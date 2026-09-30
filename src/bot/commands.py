import asyncio
import io

import discord
from discord import app_commands

from src.render.board_image import render
from src.solver.board import BoardInputError, BoardState, cell_name
from src.solver.ev import Analysis, InconsistentBoardError, Solver
from src.solver.modes.oc import BASE_PAYOUT, CLICKS, LAYOUTS, SYMMETRIES, prior

IMAGE_NAME = "board.png"
EMBED_COLOR = 0xFACC15
# Chosen 2026-09-29: comfortably longer than a $oc game's 2-minute window.
BUTTON_TIMEOUT_SECONDS = 600


class OcService:
    def __init__(self) -> None:
        self.solver = Solver(LAYOUTS, prior(), BASE_PAYOUT, CLICKS, SYMMETRIES)
        self.lock = asyncio.Lock()
        self.letters_for: dict[int, bool] = {}

    async def analyze(self, state: BoardState) -> Analysis:
        async with self.lock:
            return await asyncio.to_thread(self.solver.analyze, state)

    async def warm_up(self) -> None:
        await self.analyze(BoardState())


def build_reply(analysis: Analysis, png: bytes) -> tuple[discord.Embed, discord.File]:
    if analysis.best is None:
        title = "Game over: no clicks left"
        description = None
    else:
        clicks = analysis.clicks_left
        title = f"Click {cell_name(analysis.best)}"
        description = (
            f"**{analysis.value:.1f}** spheres expected over the next {clicks} "
            f"click{'s' if clicks != 1 else ''} if you follow the solver."
        )
    embed = discord.Embed(title=title, description=description, color=EMBED_COLOR)
    embed.set_image(url=f"attachment://{IMAGE_NAME}")
    embed.set_footer(
        text="+N = average spheres from that click. Assumes red is equally likely "
        "in any non-center cell."
    )
    return embed, discord.File(io.BytesIO(png), filename=IMAGE_NAME)


def add_reveals(state: BoardState, text: str) -> BoardState:
    tokens = text.split()
    if len(tokens) == 2 and len(tokens[0]) == 2 and len(tokens[1]) == 1:
        tokens = [tokens[0] + tokens[1]]
    added = BoardState.parse(" ".join(tokens))
    if added.n_revealed == 0:
        raise BoardInputError("type a cell and a color, like C4 G")
    for cell, color in enumerate(added.revealed):
        if color is not None:
            state = state.reveal(cell, color)
    return state


async def solve_and_draw(
    service: OcService, state: BoardState, letters: bool = False
) -> tuple[discord.Embed, discord.File]:
    analysis = await service.analyze(state)
    png = await asyncio.to_thread(render, state, analysis, BASE_PAYOUT, letters)
    return build_reply(analysis, png)


class BoardView(discord.ui.View):
    def __init__(self, service: OcService, state: BoardState, owner_id: int) -> None:
        super().__init__(timeout=BUTTON_TIMEOUT_SECONDS)
        self.service = service
        self.state = state
        self.owner_id = owner_id
        self.letters = service.letters_for.get(owner_id, False)
        self.message: discord.Message | None = None
        self.refresh()

    def refresh(self) -> None:
        self.add_sphere.disabled = self.state.n_revealed >= CLICKS
        self.colorblind.label = f"Colorblind: {'On' if self.letters else 'Off'}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "Only the person who ran /oc can update this board.", ephemeral=True
        )
        return False

    @discord.ui.button(label="Add a sphere", style=discord.ButtonStyle.primary)
    async def add_sphere(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(AddSphereModal(self))

    @discord.ui.button(label="Colorblind: Off", style=discord.ButtonStyle.secondary)
    async def colorblind(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.letters = not self.letters
        self.service.letters_for[self.owner_id] = self.letters
        await interaction.response.defer()
        embed, file = await solve_and_draw(self.service, self.state, self.letters)
        self.refresh()
        await interaction.edit_original_response(
            embed=embed, attachments=[file], view=self
        )

    async def on_timeout(self) -> None:
        self.add_sphere.disabled = True
        self.colorblind.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class AddSphereModal(discord.ui.Modal, title="Add a sphere"):
    sphere = discord.ui.TextInput(
        label="Cell and color",
        placeholder="C4 G   (colors: R O Y G T B)",
        max_length=40,
    )

    def __init__(self, board_view: BoardView) -> None:
        super().__init__()
        self.board_view = board_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        view = self.board_view
        try:
            state = add_reveals(view.state, self.sphere.value)
        except BoardInputError as err:
            await interaction.response.send_message(
                f"Couldn't add that: {err}", ephemeral=True
            )
            return

        await interaction.response.defer()
        try:
            embed, file = await solve_and_draw(view.service, state, view.letters)
        except InconsistentBoardError as err:
            await interaction.followup.send(
                f"That board can't happen in $oc: {err}", ephemeral=True
            )
            return
        view.state = state
        view.refresh()
        await interaction.edit_original_response(
            embed=embed, attachments=[file], view=view
        )


def register(tree: app_commands.CommandTree, service: OcService) -> None:
    @tree.command(name="oc", description="Best next click for a $oc board")
    @app_commands.describe(
        board="Revealed cells, e.g. D4R B2T (R O Y G T B). Leave empty for a new game."
    )
    async def oc(interaction: discord.Interaction, board: str = "") -> None:
        try:
            state = BoardState.parse(board)
        except BoardInputError as err:
            await interaction.response.send_message(
                f"Couldn't read that board: {err}", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        letters = service.letters_for.get(interaction.user.id, False)
        try:
            embed, file = await solve_and_draw(service, state, letters)
        except InconsistentBoardError as err:
            await interaction.followup.send(f"That board can't happen in $oc: {err}")
            return
        view = BoardView(service, state, interaction.user.id)
        view.message = await interaction.followup.send(
            embed=embed, file=file, view=view, wait=True
        )
