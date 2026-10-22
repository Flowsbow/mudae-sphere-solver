import io
import math

import discord
import numpy as np
from discord import app_commands

from src.bot.commands import CREDIT_URL, EMBED_COLOR
from src.bot.totals import OcTotals, OqTotals, Running, StatsStore, Totals
from src.render.stats_image import render_stats
from src.solver.board import N_CELLS, SIZE
from src.solver.modes.oc import LAYOUT_RED, RedModel, prior

STATS_IMAGE = "stats.png"

# docs/readme_numbers.json, oc.UNIFORM_CELL.optimal_red_found (base values),
# matched by simulation in sim/verify_readme_numbers.py (README, "Verification").
PREDICTED_RED_FOUND = 0.9997685185185184
OUTER_RING = [i for i in range(N_CELLS) if {i // SIZE, i % SIZE} & {0, SIZE - 1}]


def ring_share(model: RedModel) -> float:
    return float(prior(model)[np.isin(LAYOUT_RED, OUTER_RING)].sum())


RING_SOLVER = ring_share(RedModel.UNIFORM_CELL)
RING_EVERY_BOARD = ring_share(RedModel.UNIFORM_LAYOUT)

GLOBAL_FOOTER = (
    "Only games from players with /autoread on, and only when the clicks matched "
    "Mudae's rewards message. Totals only: no user, server or message IDs are stored."
)
MY_FOOTER = "Saved under your Discord ID. /delete-stats removes them."
DELETE_PROMPT = (
    "Delete your saved stats? This can't be undone. The global totals keep your games."
)


def _games(n: int) -> str:
    return f"{n:,} game{'s' if n != 1 else ''}"


def _difference(running: Running, fmt: str = "+.1f") -> str:
    if running.standard_error is None:
        return f"{running.mean:{fmt}}; the ± needs 2 games"
    return f"{running.mean:{fmt}} ± {running.standard_error:{fmt.lstrip('+')}}"


def oc_accuracy_text(totals: OcTotals) -> str:
    luck = totals.followed_luck
    if luck.n == 0:
        return "No games yet where every solver pick was followed."
    score = totals.followed_score.mean
    found = totals.followed_red_found
    return (
        f"In {_games(luck.n)} where every pick was followed: average "
        f"**{score:.1f}**, predicted **{score - luck.mean:.1f}**. Red found in "
        f"{found / luck.n:.1%}; predicted {PREDICTED_RED_FOUND:.2%}."
    )


def red_position_text(totals: OcTotals) -> str:
    n = totals.games
    ring = sum(totals.red_cells[i] for i in OUTER_RING)
    share = ring / n
    error = f" ± {math.sqrt(share * (1 - share) / n):.1%}" if 0 < ring < n else ""
    return (
        f"Red on the outer ring in {share:.1%}{error} of {_games(n)}. The solver "
        f"assumes {RING_SOLVER:.1%}; if every legal board were equally likely it "
        f"would be {RING_EVERY_BOARD:.1%}."
    )


def oq_accuracy_text(totals: OqTotals) -> str:
    share, luck = totals.followed_share, totals.followed_luck
    parts = []
    if share.n:
        parts.append(
            f"Every pick followed in {_games(share.n)}: "
            f"{_difference(share, '.1%')} of the best score possible with hindsight."
        )
    if luck.n:
        parts.append(
            f"Once exact search took over: {_difference(luck)} spheres against "
            f"its prediction ({_games(luck.n)})."
        )
    fourth = totals.clicked["RED"] + totals.clicked["RAINBOW"]
    if fourth:
        parts.append(
            f"Rainbow on {totals.clicked['RAINBOW']:,} of {fourth:,} collected 4th "
            "purples."
        )
    return " ".join(parts) or "No games yet where every solver pick was followed."


OH_TEXT = (
    "Solved by a simple rule, not a search, so there's no prediction to check yet."
)


def stats_message(
    totals: Totals, title: str, footer: str
) -> tuple[discord.Embed, discord.File | None]:
    oc, oq, oh = totals.oc, totals.oq, totals.oh
    games = oc.games + oq.games + oh.games
    if games == 0:
        description = (
            "No games yet. Turn on `/autoread` and play `$oc`, `$oq` or `$oh`."
        )
    else:
        description = (
            f"From {oc.games:,} `$oc`, {oq.games:,} `$oq` and {oh.games:,} `$oh` "
            f"game{'s' if oh.games != 1 else ''} read by `/autoread`."
        )
    embed = discord.Embed(title=title, description=description, color=EMBED_COLOR)
    embed.set_footer(text=footer)
    if games == 0:
        return embed, None
    gained = oc.spheres_gained + oq.spheres_gained + oh.spheres_gained
    embed.add_field(name="Spheres gained", value=f"{gained:,}", inline=False)
    if oc.games:
        embed.add_field(
            name="$oc",
            value=f"{oc_accuracy_text(oc)}\n{red_position_text(oc)}",
            inline=False,
        )
    if oq.games:
        embed.add_field(name="$oq", value=oq_accuracy_text(oq), inline=False)
    if oh.games:
        embed.add_field(name="$oh", value=OH_TEXT, inline=False)
    embed.set_image(url=f"attachment://{STATS_IMAGE}")
    return embed, discord.File(io.BytesIO(render_stats(totals)), filename=STATS_IMAGE)


def _with(file: discord.File | None) -> dict:
    return {} if file is None else {"file": file}


def credit_view() -> discord.ui.View:
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(label="Flowsbow/mudae-sphere-solver", url=CREDIT_URL)
    )
    return view


def delete_my_stats(stats: StatsStore, user_id: int) -> str:
    if stats.delete_player(user_id):
        return "Deleted your saved stats."
    return "You have no saved stats."


class DeleteStatsView(discord.ui.View):
    def __init__(self, stats: StatsStore) -> None:
        super().__init__(timeout=60)
        self.stats = stats

    @discord.ui.button(label="Delete my stats", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await interaction.response.edit_message(
            content=delete_my_stats(self.stats, interaction.user.id), view=None
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await interaction.response.edit_message(
            content="Cancelled. Your stats are still saved.", view=None
        )


def register_stats(tree: app_commands.CommandTree, stats: StatsStore) -> None:
    @tree.command(
        name="global-stats",
        description="Solver stats from every player's auto-read $oc, $oq and $oh games",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def global_stats(interaction: discord.Interaction) -> None:
        embed, file = stats_message(stats.all, "Global stats", GLOBAL_FOOTER)
        await interaction.response.send_message(
            embed=embed, view=credit_view(), **_with(file)
        )

    @tree.command(name="my-stats", description="Your stats from auto-read games")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def my_stats(interaction: discord.Interaction) -> None:
        totals = stats.players.get(interaction.user.id, Totals())
        embed, file = stats_message(totals, "Your stats", MY_FOOTER)
        await interaction.response.send_message(
            embed=embed, view=credit_view(), ephemeral=True, **_with(file)
        )

    @tree.command(name="delete-stats", description="Delete your saved stats")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def delete_stats(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            DELETE_PROMPT, view=DeleteStatsView(stats), ephemeral=True
        )
