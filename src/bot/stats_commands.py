import math

import discord
import numpy as np
from discord import app_commands

from src.bot.commands import CREDIT_URL, EMBED_COLOR
from src.bot.totals import OcTotals, OqTotals, Running, StatsStore, Totals
from src.solver.board import COL_NAMES, N_CELLS, ROW_NAMES, SIZE
from src.solver.modes.oc import CENTER, LAYOUT_RED, RED_CELLS, RedModel, prior

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
MY_FOOTER = "Saved under your Discord ID. /my-stats delete: True removes them."


def _games(n: int) -> str:
    return f"{n:,} game{'s' if n != 1 else ''}"


def _difference(running: Running, fmt: str = "+.1f") -> str:
    if running.standard_error is None:
        return f"{running.mean:{fmt}}; the ± needs 2 games"
    return f"{running.mean:{fmt}} ± {running.standard_error:{fmt.lstrip('+')}}"


def _clicked(counts: dict[str, int]) -> str:
    return " · ".join(f"{name.title()} {n:,}" for name, n in counts.items())


def oc_accuracy_text(totals: OcTotals) -> str:
    luck = totals.followed_luck
    if luck.n == 0:
        return "No games yet where every solver pick was followed."
    score = totals.followed_score.mean
    found = totals.followed_red_found
    return (
        f"In {_games(luck.n)} where every pick was followed: average "
        f"**{score:.1f}**, solver predicted **{score - luck.mean:.1f}** "
        f"({_difference(luck)}).\n"
        f"Red found in {found:,} of {luck.n:,} ({found / luck.n:.1%}); "
        f"predicted {PREDICTED_RED_FOUND:.2%}."
    )


def red_grid(red_cells: list[int]) -> str:
    width = len(f"{max(red_cells):,}") + 2
    lines = [" " + "".join(f"{c:>{width}}" for c in COL_NAMES)]
    for r, row in enumerate(ROW_NAMES):
        counts = [
            "-" if cell == CENTER else f"{red_cells[cell]:,}"
            for cell in range(r * SIZE, (r + 1) * SIZE)
        ]
        lines.append(row + "".join(f"{c:>{width}}" for c in counts))
    return "```\n" + "\n".join(lines) + "\n```"


def red_position_text(totals: OcTotals) -> str:
    n = totals.games
    ring = sum(totals.red_cells[i] for i in OUTER_RING)
    share = ring / n
    error = f" ± {math.sqrt(share * (1 - share) / n):.1%}" if 0 < ring < n else ""
    return (
        f"Outer ring in {ring:,} of {_games(n)} ({share:.1%}{error}). The solver "
        f"assumes {RING_SOLVER:.1%}; if every legal board were equally likely it "
        f"would be {RING_EVERY_BOARD:.1%}. Per cell, the solver's model expects "
        f"{n / len(RED_CELLS):.1f} each (never the center):\n"
        + red_grid(totals.red_cells)
    )


def oq_accuracy_text(totals: OqTotals) -> str:
    share, luck = totals.followed_share, totals.followed_luck
    if share.n == 0:
        return "No games yet where every solver pick was followed."
    text = (
        f"In {_games(share.n)} where every pick was followed: "
        f"{_difference(share, '.1%')} of the best score possible with hindsight."
    )
    if luck.n:
        text += (
            f"\nOnce exact search took over: {_difference(luck)} spheres against "
            f"its prediction ({_games(luck.n)})."
        )
    return text


def stats_embed(totals: Totals, title: str, footer: str) -> discord.Embed:
    oc, oq = totals.oc, totals.oq
    if oc.games + oq.games == 0:
        description = "No games yet. Turn on `/autoread` and play `$oc` or `$oq`."
    else:
        plural = "s" if oq.games != 1 else ""
        description = (
            f"From {oc.games:,} `$oc` and {oq.games:,} `$oq` game{plural} read by "
            "`/autoread`."
        )
    embed = discord.Embed(title=title, description=description, color=EMBED_COLOR)
    if oc.games + oq.games:
        gained = oc.spheres_gained + oq.spheres_gained
        picks = oc.picks + oq.picks
        followed = oc.picks_followed + oq.picks_followed
        embed.add_field(name="Spheres gained", value=f"{gained:,}")
        embed.add_field(
            name="Solver picks followed", value=f"{followed:,} of {picks:,}"
        )
    if oc.games:
        embed.add_field(
            name="$oc: spheres clicked", value=_clicked(oc.clicked), inline=False
        )
        embed.add_field(
            name="$oc: solver accuracy", value=oc_accuracy_text(oc), inline=False
        )
        embed.add_field(
            name="$oc: where red was", value=red_position_text(oc), inline=False
        )
    if oq.games:
        embed.add_field(
            name="$oq: spheres clicked", value=_clicked(oq.clicked), inline=False
        )
        embed.add_field(
            name="$oq: solver accuracy", value=oq_accuracy_text(oq), inline=False
        )
    embed.set_footer(text=footer)
    return embed


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


def register_stats(tree: app_commands.CommandTree, stats: StatsStore) -> None:
    @tree.command(
        name="global-stats",
        description="Solver stats from every player's auto-read $oc and $oq games",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def global_stats(interaction: discord.Interaction) -> None:
        embed = stats_embed(stats.all, "Global stats", GLOBAL_FOOTER)
        await interaction.response.send_message(embed=embed, view=credit_view())

    @tree.command(name="my-stats", description="Your stats from auto-read games")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(delete="Delete your saved stats. This can't be undone.")
    async def my_stats(interaction: discord.Interaction, delete: bool = False) -> None:
        user_id = interaction.user.id
        if delete:
            await interaction.response.send_message(
                delete_my_stats(stats, user_id), ephemeral=True
            )
            return
        totals = stats.players.get(user_id, Totals())
        await interaction.response.send_message(
            embed=stats_embed(totals, "Your stats", MY_FOOTER),
            view=credit_view(),
            ephemeral=True,
        )
