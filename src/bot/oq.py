import asyncio
import io
from dataclasses import dataclass

import discord

from src.bot.commands import (
    BUTTON_TIMEOUT_SECONDS,
    CREDIT_URL,
    EMBED_COLOR,
    IMAGE_NAME,
    OcService,
)
from src.render.board_image import percent, purples_all_known, render_oq
from src.solver.board import N_CELLS, BoardInputError, cell_name
from src.solver.ev import InconsistentBoardError
from src.solver.modes.oc import SYMMETRIES
from src.solver.modes.oq import (
    BASE_PAYOUT,
    LAYOUTS,
    PURPLE,
    PURPLES_FOR_RED,
    RAINBOW,
    RED,
    RED_SHOWN,
)
from src.solver.oq_board import LETTERS, add_cells, parse_board
from src.solver.oq_ev import (
    EXACT_CLICKS,
    EXACT_MAX_PLACEMENTS,
    OqAnalysis,
    OqSolver,
    spheres_collected,
)
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

    def payouts_for(
        self, user_id: int, server_id: int | None, rainbow: bool = False
    ) -> Payouts:
        """With rainbow, the 4th purple pays the rainbow's value instead of red's.
        The sphere bonus is assumed to apply to it like the other colors."""
        base = {**BASE_PAYOUT, RED: RAINBOW} if rainbow else BASE_PAYOUT
        bonus = self.settings.bonus_for.get((user_id, server_id))
        return base if bonus is None else with_bonus(base, *bonus)

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

    async def hindsight(
        self,
        codes: tuple[int, ...],
        payouts: Payouts,
        layout: tuple[int, ...] | None = None,
    ) -> tuple[float, int]:
        """Best with hindsight on the real board when it's known; otherwise the
        average over the boards that still fit, and how many there are."""
        async with self.lock:
            solver = self._solver_for(payouts)
            if layout is not None:
                try:
                    return await asyncio.to_thread(solver.best_on_board, layout), 1
                except InconsistentBoardError:
                    pass
            return await asyncio.to_thread(solver.best_with_hindsight, codes)


@dataclass(frozen=True)
class OqGameStats:
    score: float
    best: float  # with hindsight: on the real board, or averaged over those that fit
    boards: int
    red: str
    followed: int
    judged: int
    expected: float | None  # the solver's expected total once it searched exactly


def red_status(codes: tuple[int, ...], rainbow: bool = False) -> str:
    sphere = "Rainbow" if rainbow else "Red"
    if RED in codes:
        return f"{sphere} collected"
    if RED_SHOWN in codes:
        return f"{sphere} shown, not clicked"
    return f"Not reached: found {codes.count(PURPLE)} of {PURPLES_FOR_RED} purples"


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
                f"{EXACT_CLICKS} left ({EXACT_CLICKS - 1} if more than "
                f"{EXACT_MAX_PLACEMENTS} placements still fit)."
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
    embed.set_footer(text=f"{key} Payouts: {values}.")
    return embed, discord.File(io.BytesIO(png), filename=IMAGE_NAME)


def build_oq_stats_reply(
    stats: OqGameStats, png: bytes, bonus: bool = False
) -> tuple[discord.Embed, discord.File]:
    description = None
    if stats.expected is not None:
        gap = stats.score - stats.expected
        description = (
            "When exact search took over, the solver expected "
            f"**{stats.expected:.1f}**. You got "
            f"**{abs(gap):.1f} {'more' if gap >= 0 else 'less'}** than that."
        )
    embed = discord.Embed(
        title=f"Game over: {stats.score:.0f} spheres",
        description=description,
        color=EMBED_COLOR,
    )
    embed.add_field(name="Red", value=stats.red)
    embed.add_field(
        name="Solver picks followed",
        value=f"{stats.followed} of {stats.judged}" if stats.judged else "Not tracked",
    )
    best = (
        f"{stats.best:.0f}"
        if stats.boards == 1
        else f"{stats.best:.1f} (average over the {stats.boards:,} boards that fit)"
    )
    share = stats.score / stats.best if stats.best else 0.0
    embed.add_field(
        name="Best with hindsight",
        value=f"{best}. You got {share:.0%} of it.",
        inline=False,
    )
    embed.set_image(url=f"attachment://{IMAGE_NAME}")
    values = "Your /spherebonus values" if bonus else "Base values"
    embed.set_footer(
        text="Best with hindsight = the most anyone could get knowing where every "
        "purple was from the start. Even perfect play can't reach it every game, "
        f"because nobody sees the board in advance. {values}."
    )
    return embed, discord.File(io.BytesIO(png), filename=IMAGE_NAME)


class OqBoardView(discord.ui.View):
    def __init__(
        self,
        service: OqService,
        codes: tuple[int, ...],
        owner_id: int,
        payouts: Payouts,
        manual: bool = True,
    ) -> None:
        super().__init__(timeout=BUTTON_TIMEOUT_SECONDS)
        self.service = service
        self.codes = codes
        self.owner_id = owner_id
        self.payouts = payouts
        self.bonus = payouts != BASE_PAYOUT
        self.rainbow = False
        self.message: discord.Message | None = None
        self.last_best: int | None = None
        self.last_tied: frozenset[int] = frozenset()
        self.followed = self.judged = 0
        self.expected: float | None = None
        self.expected_rainbow = False  # whether `expected` already knew of a rainbow
        self.history: list[int] = []
        self.final_stats: OqGameStats | None = None
        if not manual:
            self.remove_item(self.add_sphere)
        self.add_item(
            discord.ui.Button(label="Flowsbow/mudae-sphere-solver", url=CREDIT_URL)
        )

    def use_rainbow(self, payouts: Payouts) -> None:
        """The 4th purple turned rainbow: value it with `payouts` from now on."""
        self.rainbow = True
        self.payouts = payouts

    async def update(
        self,
        codes: tuple[int, ...],
        final: bool = False,
        layout: tuple[int, ...] | None = None,
    ) -> tuple[discord.Embed, discord.File]:
        analysis = await self.service.analyze(codes, self.payouts)
        clicked = [
            c
            for c in range(N_CELLS)
            if codes[c] != self.codes[c] and codes[c] != RED_SHOWN
        ]
        if len(clicked) == 1 and self.last_best is not None:
            self.judged += 1
            self.followed += clicked[0] in (self.last_tied | {self.last_best})
        self.history += clicked
        self.codes = codes
        self.last_best = analysis.best
        self.last_tied = analysis.tied
        if analysis.exact and analysis.best is not None and self.expected is None:
            self.expected = spheres_collected(codes, self.payouts) + analysis.value
            self.expected_rainbow = self.rainbow
        over = final or analysis.best is None
        self.add_sphere.disabled = over

        png = await asyncio.to_thread(render_oq, codes, analysis, self.rainbow)
        if not over:
            return build_oq_reply(analysis, png, self.bonus)
        best, boards = await self.service.hindsight(codes, self.payouts, layout)
        # A prediction made before the rainbow appeared assumed a red, so it
        # can't be compared with the score.
        fair = self.expected_rainbow == self.rainbow
        self.final_stats = OqGameStats(
            score=spheres_collected(codes, self.payouts),
            best=best,
            boards=boards,
            red=red_status(codes, self.rainbow),
            followed=self.followed,
            judged=self.judged,
            expected=self.expected if fair else None,
        )
        return build_oq_stats_reply(self.final_stats, png, self.bonus)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "Only the person who ran /manual-input can update this board.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Add a sphere", style=discord.ButtonStyle.primary)
    async def add_sphere(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(AddOqSphereModal(self))

    async def on_timeout(self) -> None:
        self.add_sphere.disabled = True
        if self.message is not None and self.add_sphere in self.children:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class AddOqSphereModal(discord.ui.Modal, title="Add a sphere"):
    sphere = discord.ui.TextInput(
        label="Cell and color",
        placeholder=f"C4 G, or just G for the suggested cell ({LETTERS})",
        max_length=40,
    )

    def __init__(self, board_view: OqBoardView) -> None:
        super().__init__()
        self.board_view = board_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        view = self.board_view
        try:
            codes = add_cells(view.codes, self.sphere.value, view.last_best)
        except BoardInputError as err:
            await interaction.response.send_message(
                f"Couldn't add that: {err}", ephemeral=True
            )
            return
        await interaction.response.defer()
        try:
            embed, file = await view.update(codes)
        except InconsistentBoardError as err:
            await interaction.followup.send(
                f"That board can't happen in $oq: {err}", ephemeral=True
            )
            return
        await interaction.edit_original_response(
            embed=embed, attachments=[file], view=view
        )


async def send_oq_board(
    interaction: discord.Interaction, service: OqService, board: str
) -> None:
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
    view = OqBoardView(service, codes, user_id, payouts)
    try:
        embed, file = await view.update(codes)
    except InconsistentBoardError as err:
        await interaction.followup.send(f"That board can't happen in $oq: {err}")
        return
    view.message = await interaction.followup.send(
        embed=embed, file=file, view=view, wait=True
    )
