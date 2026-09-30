import asyncio
import io
from typing import Literal

import discord
from discord import app_commands

from src.bot.mudae_reader import NotAnOcBoardError, read_oc_board
from src.render.board_image import render, render_final
from src.solver.board import BoardInputError, BoardState, Color, cell_name
from src.solver.ev import Analysis, InconsistentBoardError, Solver
from src.solver.modes.oc import BASE_PAYOUT, CLICKS, LAYOUTS, SYMMETRIES, prior
from src.solver.stats import GameStats, Step, game_stats

IMAGE_NAME = "board.png"
EMBED_COLOR = 0xFACC15
# Chosen 2026-09-29: comfortably longer than a $oc game's 2-minute window.
BUTTON_TIMEOUT_SECONDS = 600
CREDIT_URL = "https://github.com/Flowsbow/mudae-sphere-solver"


class OcService:
    def __init__(self) -> None:
        self.solver = Solver(LAYOUTS, prior(), BASE_PAYOUT, CLICKS, SYMMETRIES)
        self.lock = asyncio.Lock()
        self.letters_for: dict[int, bool] = {}
        self.auto_users: set[int] = set()

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


def build_stats_reply(
    stats: GameStats,
    cells: tuple[Color | None, ...],
    clicked: frozenset[int],
    letters: bool,
) -> tuple[discord.Embed, discord.File]:
    description = None
    if stats.luck is not None:
        word = "more" if stats.luck >= 0 else "less"
        description = (
            f"The solver expected **{stats.expected:.1f}**. "
            f"You got **{abs(stats.luck):.1f} {word}** than that."
        )
    embed = discord.Embed(
        title=f"Game over: {stats.score:.0f} spheres",
        description=description,
        color=EMBED_COLOR,
    )
    embed.add_field(
        name="Red",
        value=f"Found on click {stats.red_on_click}"
        if stats.red_on_click
        else "Missed",
    )
    embed.add_field(
        name="Solver picks followed",
        value=f"{stats.followed} of {stats.judged}" if stats.judged else "Not tracked",
    )
    lines = []
    for i, step in enumerate(stats.steps, 1):
        line = (
            f"{i}. {cell_name(step.cell)} {step.color.name.title()} "
            f"+{BASE_PAYOUT[step.color]:.0f}"
        )
        if step.recommended is not None:
            line += (
                " (solver's pick)"
                if step.cell == step.recommended
                else f" (solver said {cell_name(step.recommended)})"
            )
        lines.append(line)
    embed.add_field(name="Your clicks", value="\n".join(lines) or "None", inline=False)
    embed.set_image(url=f"attachment://{IMAGE_NAME}")
    embed.set_footer(
        text="Base sphere values; your multiplier scales them. Outlined = your clicks."
    )
    png = render_final(cells, clicked, letters)
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
) -> tuple[discord.Embed, discord.File, Analysis]:
    analysis = await service.analyze(state)
    png = await asyncio.to_thread(render, state, analysis, BASE_PAYOUT, letters)
    embed, file = build_reply(analysis, png)
    return embed, file, analysis


class BoardView(discord.ui.View):
    def __init__(
        self,
        service: OcService,
        state: BoardState,
        owner_id: int,
        analysis: Analysis | None = None,
        manual: bool = True,
    ) -> None:
        super().__init__(timeout=BUTTON_TIMEOUT_SECONDS)
        self.service = service
        self.state = state
        self.owner_id = owner_id
        self.letters = service.letters_for.get(owner_id, False)
        self.message: discord.Message | None = None
        self.history = [
            Step(cell, color, None)
            for cell, color in enumerate(state.revealed)
            if color is not None
        ]
        self.last_best = analysis.best if analysis else None
        self.expected = (
            sum(BASE_PAYOUT[step.color] for step in self.history) + analysis.value
            if analysis
            else None
        )
        self.final: tuple[tuple[Color | None, ...], frozenset[int]] | None = None
        if not manual:
            self.remove_item(self.add_sphere)
        self.add_item(
            discord.ui.Button(label="Flowsbow/mudae-sphere-solver", url=CREDIT_URL)
        )
        self.refresh()

    def advance(self, state: BoardState, analysis: Analysis | None = None) -> None:
        new = [
            (cell, color)
            for cell, (old, color) in enumerate(
                zip(self.state.revealed, state.revealed, strict=True)
            )
            if old is None and color is not None
        ]
        recommended = self.last_best if len(new) == 1 else None
        self.history += [Step(cell, color, recommended) for cell, color in new]
        self.state = state
        if analysis is not None:
            self.last_best = analysis.best

    def finish(
        self, cells: tuple[Color | None, ...], clicked: frozenset[int]
    ) -> tuple[discord.Embed, discord.File]:
        self.final = (cells, clicked)
        self.add_sphere.disabled = True
        return self.stats_reply()

    def stats_reply(self) -> tuple[discord.Embed, discord.File]:
        cells, clicked = self.final
        stats = game_stats(self.history, BASE_PAYOUT, self.expected)
        return build_stats_reply(stats, cells, clicked, self.letters)

    def refresh(self) -> None:
        self.add_sphere.disabled = self.final is not None or (
            self.state.n_revealed >= CLICKS
        )

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

    async def on_timeout(self) -> None:
        self.add_sphere.disabled = True
        if self.message is not None and self.add_sphere in self.children:
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
            embed, file, analysis = await solve_and_draw(
                view.service, state, view.letters
            )
        except InconsistentBoardError as err:
            await interaction.followup.send(
                f"That board can't happen in $oc: {err}", ephemeral=True
            )
            return
        view.advance(state, analysis)
        if state.n_revealed >= CLICKS:
            clicked = frozenset(step.cell for step in view.history)
            embed, file = view.finish(state.revealed, clicked)
        view.refresh()
        await interaction.edit_original_response(
            embed=embed, attachments=[file], view=view
        )


async def send_board(
    interaction: discord.Interaction, service: OcService, state: BoardState
) -> None:
    await interaction.response.defer(thinking=True)
    letters = service.letters_for.get(interaction.user.id, False)
    try:
        embed, file, analysis = await solve_and_draw(service, state, letters)
    except InconsistentBoardError as err:
        await interaction.followup.send(f"That board can't happen in $oc: {err}")
        return
    view = BoardView(service, state, interaction.user.id, analysis)
    view.message = await interaction.followup.send(
        embed=embed, file=file, view=view, wait=True
    )


def set_auto(service: OcService, user_id: int, on: bool) -> str:
    if on:
        service.auto_users.add(user_id)
        return (
            "Auto mode on. Type `$oc` and I'll solve Mudae's board as you play. "
            "Turn it off with `/oc auto: off`."
        )
    service.auto_users.discard(user_id)
    return "Auto mode off."


def toggle_colorblind(service: OcService, user_id: int) -> str:
    on = not service.letters_for.get(user_id, False)
    service.letters_for[user_id] = on
    if on:
        return "Colorblind mode on: boards from now on use lettered blocks."
    return "Colorblind mode off. Run `/colorblindmode` again to turn it back on."


def register(tree: app_commands.CommandTree, service: OcService) -> None:
    @tree.command(name="oc", description="Best next click for a $oc board")
    @app_commands.describe(
        board="Revealed cells, e.g. D4R B2T (R O Y G T B). Skip for a new game.",
        auto="Solve your Mudae $oc games automatically.",
    )
    async def oc(
        interaction: discord.Interaction,
        board: str = "",
        auto: Literal["on", "off"] | None = None,
    ) -> None:
        if auto is not None:
            text = set_auto(service, interaction.user.id, auto == "on")
            await interaction.response.send_message(text, ephemeral=True)
            return
        try:
            state = BoardState.parse(board)
        except BoardInputError as err:
            await interaction.response.send_message(
                f"Couldn't read that board: {err}", ephemeral=True
            )
            return
        await send_board(interaction, service, state)

    @tree.command(
        name="colorblindmode",
        description="Toggle lettered blocks instead of colored spheres",
    )
    async def colorblindmode(interaction: discord.Interaction) -> None:
        text = toggle_colorblind(service, interaction.user.id)
        await interaction.response.send_message(text, ephemeral=True)

    @tree.context_menu(name="Solve sphere board")
    async def solve_board(
        interaction: discord.Interaction, message: discord.Message
    ) -> None:
        try:
            board = read_oc_board(message)
        except NotAnOcBoardError as err:
            await interaction.response.send_message(
                f"That doesn't look like a $oc board: {err}", ephemeral=True
            )
            return
        if board.finished:
            await interaction.response.send_message(
                "That game is already over.", ephemeral=True
            )
            return
        await send_board(interaction, service, board.state)
