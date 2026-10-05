import asyncio
import io

import discord
from discord import app_commands

from src.bot.commands import (
    BUTTON_TIMEOUT_SECONDS,
    CREDIT_URL,
    EMBED_COLOR,
    IMAGE_NAME,
    OcService,
)
from src.render.board_image import percent, purples_all_known, render_oq
from src.solver.board import BoardInputError, cell_name
from src.solver.ev import InconsistentBoardError
from src.solver.modes.oc import SYMMETRIES
from src.solver.modes.oq import BASE_PAYOUT, LAYOUTS
from src.solver.oq_board import LETTERS, add_cells, parse_board
from src.solver.oq_ev import EXACT_CLICKS, OqAnalysis, OqSolver
from src.solver.payouts import with_bonus

# A solver's position cache can reach about 0.3 GB (MEMO_LIMIT in oq_ev.py), so
# only two payout tables are kept at once.
MAX_SOLVERS = 2

Payouts = dict[int, int]


class OqService:
    def __init__(self, settings: OcService) -> None:
        self.settings = settings
        self.solvers: dict[tuple[tuple[int, int], ...], OqSolver] = {}
        self.lock = asyncio.Lock()

    def payouts_for(self, user_id: int, server_id: int | None) -> Payouts:
        bonus = self.settings.bonus_for.get((user_id, server_id))
        return BASE_PAYOUT if bonus is None else with_bonus(BASE_PAYOUT, *bonus)

    def _solver_for(self, payouts: Payouts) -> OqSolver:
        key = tuple(sorted(payouts.items()))
        solver = self.solvers.pop(key, None)
        if solver is None:
            solver = OqSolver(LAYOUTS, payouts, symmetries=SYMMETRIES)
        self.solvers[key] = solver
        if len(self.solvers) > MAX_SOLVERS:
            del self.solvers[next(iter(self.solvers))]
        return solver

    async def analyze(
        self, codes: tuple[int, ...], payouts: Payouts = BASE_PAYOUT
    ) -> OqAnalysis:
        async with self.lock:
            solver = self._solver_for(payouts)
            return await asyncio.to_thread(solver.analyze, codes)


def build_oq_reply(
    analysis: OqAnalysis, png: bytes, bonus: bool = False
) -> tuple[discord.Embed, discord.File]:
    if analysis.best is None:
        title, description = "Game over: no paid clicks left", None
    else:
        left = analysis.clicks_left
        clicks = f"{left} paid click{'s' if left != 1 else ''}"
        title = f"Click {cell_name(analysis.best)}"
        if analysis.exact:
            description = (
                f"**{analysis.value:.1f}** spheres expected from the rest of the game "
                f"({clicks} left) if you follow the solver."
            )
        else:
            chance = percent(analysis.purple_prob[analysis.best])
            description = (
                f"**{chance}** chance it's purple. With {clicks} left the solver "
                f"goes for the likeliest purple; it searches exactly from "
                f"{EXACT_CLICKS} left."
            )
    embed = discord.Embed(title=title, description=description, color=EMBED_COLOR)
    embed.set_image(url=f"attachment://{IMAGE_NAME}")
    values = "your /spherebonus values" if bonus else "base values"
    if purples_all_known(analysis):
        key = "Every purple is known: +N = spheres from that tile."
    else:
        key = (
            "% = chance the tile is purple, if every placement of the 4 purples is "
            "equally likely."
        )
    embed.set_footer(text=f"{key} Payouts: {values}; yellow and orange are assumed.")
    return embed, discord.File(io.BytesIO(png), filename=IMAGE_NAME)


async def solve_and_draw_oq(
    service: OqService, codes: tuple[int, ...], payouts: Payouts
) -> tuple[discord.Embed, discord.File, OqAnalysis]:
    analysis = await service.analyze(codes, payouts)
    png = await asyncio.to_thread(render_oq, codes, analysis)
    embed, file = build_oq_reply(analysis, png, bonus=payouts != BASE_PAYOUT)
    return embed, file, analysis


class OqBoardView(discord.ui.View):
    def __init__(
        self,
        service: OqService,
        codes: tuple[int, ...],
        owner_id: int,
        payouts: Payouts,
    ) -> None:
        super().__init__(timeout=BUTTON_TIMEOUT_SECONDS)
        self.service = service
        self.codes = codes
        self.owner_id = owner_id
        self.payouts = payouts
        self.message: discord.Message | None = None
        self.add_item(
            discord.ui.Button(label="Flowsbow/mudae-sphere-solver", url=CREDIT_URL)
        )

    def refresh(self, analysis: OqAnalysis) -> None:
        self.add_sphere.disabled = analysis.best is None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "Only the person who ran /oq can update this board.", ephemeral=True
        )
        return False

    @discord.ui.button(label="Add a sphere", style=discord.ButtonStyle.primary)
    async def add_sphere(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(AddOqSphereModal(self))

    async def on_timeout(self) -> None:
        self.add_sphere.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class AddOqSphereModal(discord.ui.Modal, title="Add a sphere"):
    sphere = discord.ui.TextInput(
        label="Cell and color",
        placeholder=f"C4 G   (colors: {LETTERS})",
        max_length=40,
    )

    def __init__(self, board_view: OqBoardView) -> None:
        super().__init__()
        self.board_view = board_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        view = self.board_view
        try:
            codes = add_cells(view.codes, self.sphere.value)
        except BoardInputError as err:
            await interaction.response.send_message(
                f"Couldn't add that: {err}", ephemeral=True
            )
            return
        await interaction.response.defer()
        try:
            embed, file, analysis = await solve_and_draw_oq(
                view.service, codes, view.payouts
            )
        except InconsistentBoardError as err:
            await interaction.followup.send(
                f"That board can't happen in $oq: {err}", ephemeral=True
            )
            return
        view.codes = codes
        view.refresh(analysis)
        await interaction.edit_original_response(
            embed=embed, attachments=[file], view=view
        )


def register_oq(tree: app_commands.CommandTree, service: OqService) -> None:
    @tree.command(name="oq", description="Best next click for a $oq board")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        board="Revealed tiles, e.g. C3B B4G A1T (B T G Y O P R). Skip for a new game."
    )
    async def oq(interaction: discord.Interaction, board: str = "") -> None:
        try:
            codes = parse_board(board)
        except BoardInputError as err:
            await interaction.response.send_message(
                f"Couldn't read that board: {err}", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True)
        user_id = interaction.user.id
        payouts = service.payouts_for(user_id, interaction.guild_id)
        try:
            embed, file, analysis = await solve_and_draw_oq(service, codes, payouts)
        except InconsistentBoardError as err:
            await interaction.followup.send(f"That board can't happen in $oq: {err}")
            return
        view = OqBoardView(service, codes, user_id, payouts)
        view.refresh(analysis)
        view.message = await interaction.followup.send(
            embed=embed, file=file, view=view, wait=True
        )
