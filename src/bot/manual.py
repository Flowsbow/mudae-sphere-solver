import time

import discord
from discord import app_commands

from src.bot.auto import SLOW_REPLY_SECONDS, log
from src.bot.commands import OcService, send_board
from src.bot.oh import OhService, send_oh_board
from src.bot.oq import OqService, send_oq_board
from src.solver.board import BoardInputError, BoardState

GAMES = [
    app_commands.Choice(name="$oc", value="oc"),
    app_commands.Choice(name="$oq", value="oq"),
    app_commands.Choice(name="$oh", value="oh"),
]


def register_manual(
    tree: app_commands.CommandTree,
    oc: OcService,
    oq: OqService,
    oh: OhService | None = None,
) -> None:
    oh = oh if oh is not None else OhService(oc)

    @tree.command(
        name="manual-input",
        description="Type a $oc, $oq or $oh board and get the best next click",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        game="Which sphere game",
        board="Revealed cells, e.g. D4R B2T ($oc), C3B B4G A1T ($oq) or A3B B2T* "
        "($oh, * = clicked). Skip for a new game.",
    )
    @app_commands.choices(game=GAMES)
    async def manual_input(
        interaction: discord.Interaction,
        game: app_commands.Choice[str],
        board: str = "",
    ) -> None:
        received = time.perf_counter()
        sent_at = getattr(interaction, "created_at", None)
        late = (discord.utils.utcnow() - sent_at).total_seconds() if sent_at else 0.0
        await _send(interaction, game.value, board)
        took = time.perf_counter() - received
        if late + took >= SLOW_REPLY_SECONDS:
            log.info(
                "slow reply /manual-input $%s: Discord delivered it %.1fs after it "
                "was sent, then the bot took %.1fs to solve, draw and send",
                game.value,
                late,
                took,
            )

    async def _send(interaction: discord.Interaction, game: str, board: str) -> None:
        if game == "oq":
            await send_oq_board(interaction, oq, board)
            return
        if game == "oh":
            await send_oh_board(interaction, oh, board)
            return
        try:
            state = BoardState.parse(board)
        except BoardInputError as err:
            await interaction.response.send_message(
                f"Couldn't read that board: {err}", ephemeral=True
            )
            return
        await send_board(interaction, oc, state)
