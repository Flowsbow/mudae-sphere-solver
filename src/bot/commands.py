import asyncio
import io
from pathlib import Path
from typing import Literal

import discord
from discord import app_commands

from src.bot.mudae_reader import NotAnOcBoardError, read_oc_board
from src.bot.settings import PlayerSettings, load_settings, save_settings
from src.render.board_image import render, render_final
from src.solver.board import BoardInputError, BoardState, Color, cell_name
from src.solver.ev import Analysis, InconsistentBoardError, Solver
from src.solver.modes.oc import BASE_PAYOUT, CLICKS, LAYOUTS, SYMMETRIES, prior
from src.solver.payouts import with_bonus
from src.solver.stats import GameStats, Step, game_stats

IMAGE_NAME = "board.png"
EMBED_COLOR = 0xFACC15
# Chosen 2026-09-29: comfortably longer than a $oc game's 2-minute window.
BUTTON_TIMEOUT_SECONDS = 600
CREDIT_URL = "https://github.com/Flowsbow/mudae-sphere-solver"
# A solver with a full game cached is about 12 MB (tracemalloc, 2026-10-03), so
# this caps the cache near 100 MB.
MAX_SOLVERS = 8
# Chosen 2026-10-03 to reject typos; not a Mudae limit.
MAX_BONUS = 1000

Payouts = dict[Color, int]


class OcService:
    def __init__(self, settings_path: Path | None = None) -> None:
        self.solvers: dict[tuple[int, ...], Solver] = {}
        self.lock = asyncio.Lock()
        self.settings_path = settings_path
        saved = load_settings(settings_path)
        self.letters_for: dict[int, bool] = dict.fromkeys(saved.colorblind_users, True)
        self.auto_users: set[int] = saved.auto_users
        self.bonus_for = saved.sphere_bonus

    def save_settings(self) -> None:
        colorblind = {user for user, on in self.letters_for.items() if on}
        save_settings(
            self.settings_path,
            PlayerSettings(self.auto_users, colorblind, self.bonus_for),
        )

    def payouts_for(self, user_id: int, server_id: int | None) -> Payouts:
        bonus = self.bonus_for.get((user_id, server_id))
        return BASE_PAYOUT if bonus is None else with_bonus(BASE_PAYOUT, *bonus)

    def _solver_for(self, payouts: Payouts) -> Solver:
        key = tuple(payouts[color] for color in Color)
        solver = self.solvers.pop(key, None)
        if solver is None:
            solver = Solver(LAYOUTS, prior(), payouts, CLICKS, SYMMETRIES)
        self.solvers[key] = solver
        if len(self.solvers) > MAX_SOLVERS:
            del self.solvers[next(iter(self.solvers))]
        return solver

    async def analyze(
        self, state: BoardState, payouts: Payouts = BASE_PAYOUT
    ) -> Analysis:
        async with self.lock:
            solver = self._solver_for(payouts)
            return await asyncio.to_thread(solver.analyze, state)

    async def warm_up(self, payouts: Payouts = BASE_PAYOUT) -> None:
        await self.analyze(BoardState(), payouts)


def build_reply(
    analysis: Analysis, png: bytes, bonus: bool = False
) -> tuple[discord.Embed, discord.File]:
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
    values = "your /spherebonus values" if bonus else "base values"
    embed.set_footer(
        text=f"+N = average spheres from that click, in {values}. Assumes red is "
        "equally likely in any non-center cell."
    )
    return embed, discord.File(io.BytesIO(png), filename=IMAGE_NAME)


def build_stats_reply(
    stats: GameStats,
    cells: tuple[Color | None, ...],
    clicked: frozenset[int],
    letters: bool,
    payouts: Payouts = BASE_PAYOUT,
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
            f"+{payouts[step.color]:.0f}"
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
    values = "Your /spherebonus values" if payouts != BASE_PAYOUT else "Base values"
    embed.set_footer(
        text=f"{values}; your server's multiplier scales them. Outlined = your clicks."
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
    service: OcService,
    state: BoardState,
    letters: bool = False,
    payouts: Payouts = BASE_PAYOUT,
) -> tuple[discord.Embed, discord.File, Analysis]:
    analysis = await service.analyze(state, payouts)
    png = await asyncio.to_thread(render, state, analysis, payouts, letters)
    embed, file = build_reply(analysis, png, bonus=payouts != BASE_PAYOUT)
    return embed, file, analysis


class BoardView(discord.ui.View):
    def __init__(
        self,
        service: OcService,
        state: BoardState,
        owner_id: int,
        analysis: Analysis | None = None,
        manual: bool = True,
        payouts: Payouts = BASE_PAYOUT,
    ) -> None:
        super().__init__(timeout=BUTTON_TIMEOUT_SECONDS)
        self.service = service
        self.state = state
        self.owner_id = owner_id
        self.letters = service.letters_for.get(owner_id, False)
        self.payouts = payouts
        self.message: discord.Message | None = None
        self.history = [
            Step(cell, color, None)
            for cell, color in enumerate(state.revealed)
            if color is not None
        ]
        self.last_best = analysis.best if analysis else None
        self.expected = (
            sum(payouts[step.color] for step in self.history) + analysis.value
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
        stats = game_stats(self.history, self.payouts, self.expected)
        return build_stats_reply(stats, cells, clicked, self.letters, self.payouts)

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
                view.service, state, view.letters, view.payouts
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
    user_id = interaction.user.id
    letters = service.letters_for.get(user_id, False)
    payouts = service.payouts_for(user_id, interaction.guild_id)
    try:
        embed, file, analysis = await solve_and_draw(service, state, letters, payouts)
    except InconsistentBoardError as err:
        await interaction.followup.send(f"That board can't happen in $oc: {err}")
        return
    view = BoardView(service, state, user_id, analysis, payouts=payouts)
    view.message = await interaction.followup.send(
        embed=embed, file=file, view=view, wait=True
    )


def set_auto(service: OcService, user_id: int, on: bool) -> str:
    if on:
        service.auto_users.add(user_id)
    else:
        service.auto_users.discard(user_id)
    service.save_settings()
    if on:
        return (
            "Auto mode on. Type `$oc` and I'll solve Mudae's board as you play. "
            "Turn it off with `/oc auto: off`."
        )
    return "Auto mode off."


def toggle_colorblind(service: OcService, user_id: int) -> str:
    on = not service.letters_for.get(user_id, False)
    service.letters_for[user_id] = on
    service.save_settings()
    if on:
        return "Colorblind mode on: boards from now on use lettered blocks."
    return "Colorblind mode off. Run `/colorblindmode` again to turn it back on."


def describe_payouts(payouts: Payouts) -> str:
    return " · ".join(f"{color.name.title()} {payouts[color]}" for color in Color)


def set_sphere_bonus(
    service: OcService,
    user_id: int,
    server_id: int | None,
    flat: int | None = None,
    percent: int | None = None,
) -> str:
    key = (user_id, server_id)
    if flat is not None or percent is not None:
        old_flat, old_percent = service.bonus_for.get(key, (0, 0))
        bonus = (
            old_flat if flat is None else flat,
            old_percent if percent is None else percent,
        )
        if bonus == (0, 0):
            service.bonus_for.pop(key, None)
        else:
            service.bonus_for[key] = bonus
        service.save_settings()
    flat, percent = service.bonus_for.get(key, (0, 0))
    where = "DMs" if server_id is None else "this server"
    return (
        f"Sphere bonus for {where}: +{flat} flat, +{percent}%.\n"
        f"{describe_payouts(service.payouts_for(user_id, server_id))}\n"
        "Your server's multiplier scales these. Set both to 0 for base values."
    )


def register(tree: app_commands.CommandTree, service: OcService) -> None:
    @tree.command(name="oc", description="Best next click for a $oc board")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
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
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def colorblindmode(interaction: discord.Interaction) -> None:
        text = toggle_colorblind(service, interaction.user.id)
        await interaction.response.send_message(text, ephemeral=True)

    @tree.command(
        name="spherebonus",
        description="Set your premium sphere bonus so the numbers match your payouts",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        flat='The +N on the "Additional spheres" line of $kt.',
        percent="Your percent sphere bonus, e.g. 25. Skip both to see your values.",
    )
    async def spherebonus(
        interaction: discord.Interaction,
        flat: app_commands.Range[int, 0, MAX_BONUS] | None = None,
        percent: app_commands.Range[int, 0, MAX_BONUS] | None = None,
    ) -> None:
        user_id, server_id = interaction.user.id, interaction.guild_id
        text = set_sphere_bonus(service, user_id, server_id, flat, percent)
        await interaction.response.send_message(text, ephemeral=True)
        if flat is not None or percent is not None:
            await service.warm_up(service.payouts_for(user_id, server_id))

    @tree.context_menu(name="Solve sphere board")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
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
