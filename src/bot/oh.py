import asyncio
import io

import discord

from src.bot.commands import (
    BUTTON_TIMEOUT_SECONDS,
    CREDIT_URL,
    EMBED_COLOR,
    IMAGE_NAME,
    OcService,
)
from src.render.board_image import percent, render_oh
from src.solver.board import BoardInputError, cell_name
from src.solver.modes.oc import CLICKS as OC_CLICKS
from src.solver.modes.oh import BASE_PAYOUT, OC_GAME_VALUE, PRIZE
from src.solver.oh_board import LETTERS, add_spheres, parse_board
from src.solver.oh_rule import OhAdvice, OhBoard, advise
from src.solver.payouts import with_bonus

Payouts = dict[str, float]


class OhService:
    def __init__(self, settings: OcService) -> None:
        self.settings = settings

    def bonus(self, user_id: int, server_id: int | None) -> tuple[int, int] | None:
        return self.settings.bonus_for.get((user_id, server_id))

    def payouts_for(self, user_id: int, server_id: int | None) -> Payouts:
        """Dark and light are averages, so the bonus formula gives their average
        with the bonus only up to rounding."""
        bonus = self.bonus(user_id, server_id)
        return BASE_PAYOUT if bonus is None else with_bonus(BASE_PAYOUT, *bonus)

    def oc_value_for(self, user_id: int, server_id: int | None) -> float:
        """Each of a $oc game's clicks collects one sphere, so a bonus of +flat and
        +percent adds flat per click and then scales the total. This skips the
        rounding and the solver's small change of plan for bonus payouts."""
        bonus = self.bonus(user_id, server_id)
        if bonus is None:
            return OC_GAME_VALUE
        flat, pct = bonus
        return (OC_GAME_VALUE + OC_CLICKS * flat) * (100 + pct) / 100


def describe(advice: OhAdvice, board: OhBoard) -> tuple[str, str | None]:
    cell = cell_name(advice.best)
    value = advice.cell_value[advice.best]
    covered = advice.covered_value
    if advice.reason == "purple":
        return f"Click {cell} (free)", "Purple doesn't use a click."
    if advice.reason == "covered":
        prize = (
            f", counting a {percent(advice.prize_chance)} chance of the free $oc game"
            if advice.prize_chance
            else ""
        )
        if advice.weakest_kept:
            versus = (
                f"more than the weakest sphere you'd still collect "
                f"({advice.weakest_kept:.0f})"
            )
        else:
            versus = "and you have clicks to spare for every sphere showing"
        return (
            f"Click {cell} (covered)",
            f"A covered tile is worth **{covered:.1f}** spheres on average{prize}, "
            f"{versus}. Any covered tile is as good.",
        )
    if advice.reason == "dark":
        return (
            f"Click {cell} (dark)",
            f"Dark is worth about **{value:.0f}** on average. You'd collect it anyway, "
            "so the rule clicks it first.",
        )
    if covered is None:
        return f"Click {cell}", f"Worth **{value:.0f}**. No covered tiles are left."
    return (
        f"Click {cell}",
        f"Worth **{value:.0f}**, more than a covered tile ({covered:.1f} on average).",
    )


def collected(board: OhBoard, payouts: Payouts) -> tuple[float, bool]:
    """Spheres from the clicked tiles (dark and light at their average), and
    whether the $oc prize was one of them."""
    spheres = sum(
        payouts[board.cells[c]] for c in board.clicked if board.cells[c] != PRIZE
    )
    return spheres, board.prize_found


def build_oh_reply(
    board: OhBoard,
    advice: OhAdvice,
    png: bytes,
    payouts: Payouts,
    final: bool = False,
) -> tuple[discord.Embed, discord.File]:
    values = "Base values" if payouts == BASE_PAYOUT else "Your /spherebonus values"
    if final or advice.best is None:
        spheres, prize = collected(board, payouts)
        title = f"Game over: about {spheres:.0f} spheres"
        description = "Plus the free $oc game." if prize else None
        footer = f"Dark and light count at their average. {values}."
    else:
        title, description = describe(advice, board)
        left = advice.clicks_left
        footer = (
            f"{left} paid click{'s' if left != 1 else ''} left. A simple rule, not an "
            "exact search. Covered tiles use colblitz's rates, plus the free $oc "
            f"game half of all boards hide. {values}."
        )
    embed = discord.Embed(title=title, description=description, color=EMBED_COLOR)
    embed.set_image(url=f"attachment://{IMAGE_NAME}")
    embed.set_footer(text=footer)
    return embed, discord.File(io.BytesIO(png), filename=IMAGE_NAME)


class OhBoardView(discord.ui.View):
    def __init__(
        self,
        service: OhService,
        board: OhBoard,
        owner_id: int,
        payouts: Payouts,
        oc_value: float,
        manual: bool = True,
    ) -> None:
        super().__init__(timeout=BUTTON_TIMEOUT_SECONDS)
        self.service = service
        self.board = board
        self.owner_id = owner_id
        self.payouts = payouts
        self.oc_value = oc_value
        self.message: discord.Message | None = None
        self.last_best: int | None = None
        if not manual:
            self.remove_item(self.add_sphere)
        self.add_item(
            discord.ui.Button(label="Flowsbow/mudae-sphere-solver", url=CREDIT_URL)
        )

    async def update(
        self, board: OhBoard, final: bool = False
    ) -> tuple[discord.Embed, discord.File]:
        self.board = board
        advice = advise(board, self.payouts, self.oc_value)
        self.last_best = None if final else advice.best
        over = final or advice.best is None
        self.add_sphere.disabled = over
        png = await asyncio.to_thread(render_oh, board, None if over else advice)
        return build_oh_reply(board, advice, png, self.payouts, final=over)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "Only the person who ran /manual-input can update this board.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Add spheres", style=discord.ButtonStyle.primary)
    async def add_sphere(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(AddOhSpheresModal(self))

    async def on_timeout(self) -> None:
        self.add_sphere.disabled = True
        if self.message is not None and self.add_sphere in self.children:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class AddOhSpheresModal(discord.ui.Modal, title="Add spheres"):
    spheres = discord.ui.TextInput(
        label="What changed (* = you clicked it)",
        placeholder="T B1 B: suggested tile was teal, B1 now shows blue",
        max_length=100,
    )

    def __init__(self, board_view: OhBoardView) -> None:
        super().__init__()
        self.board_view = board_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        view = self.board_view
        try:
            board = add_spheres(view.board, self.spheres.value, view.last_best)
        except BoardInputError as err:
            await interaction.response.send_message(
                f"Couldn't add that: {err}", ephemeral=True
            )
            return
        await interaction.response.defer()
        embed, file = await view.update(board)
        await interaction.edit_original_response(
            embed=embed, attachments=[file], view=view
        )


async def send_oh_board(
    interaction: discord.Interaction, service: OhService, text: str
) -> None:
    try:
        board = parse_board(text)
    except BoardInputError as err:
        await interaction.response.send_message(
            f"Couldn't read that board: {err} Spheres: {LETTERS}.", ephemeral=True
        )
        return
    server = interaction.guild_id
    user = interaction.user.id
    view = OhBoardView(
        service,
        board,
        user,
        service.payouts_for(user, server),
        service.oc_value_for(user, server),
    )
    embed, file = await view.update(board)
    await interaction.response.send_message(embed=embed, file=file, view=view)
    view.message = await interaction.original_response()
