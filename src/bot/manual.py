import time
from datetime import timedelta

import discord
from discord import app_commands

from src.bot.auto import SLOW_REPLY_SECONDS, log
from src.bot.commands import OcService, send_board
from src.bot.oh import OhService, send_oh_board
from src.bot.oq import OqService, send_oq_board
from src.solver.board import BoardInputError, BoardState

# Flow, 2026-10-21: each user gets one /manual-input every 30 seconds, and a board
# the bot rejects doesn't count. Add a sphere and the other buttons on a board it
# sent aren't limited.
MANUAL_COOLDOWN_SECONDS = 30.0

GAMES = [
    app_commands.Choice(name="$oc", value="oc"),
    app_commands.Choice(name="$oq", value="oq"),
    app_commands.Choice(name="$oh", value="oh"),
]


class Cooldown:
    """When each user may next use a command. Users who are no longer waiting
    are dropped, so it only holds the users still waiting."""

    def __init__(self, seconds: float, clock=time.monotonic) -> None:
        self.seconds = seconds
        self.clock = clock
        self.next_use: dict[int, float] = {}

    def wait_for(self, user_id: int) -> float:
        """Seconds the user still has to wait. 0 means they may go now, and starts
        their next wait."""
        now = self.clock()
        self.next_use = {user: at for user, at in self.next_use.items() if at > now}
        if user_id in self.next_use:
            return self.next_use[user_id] - now
        self.next_use[user_id] = now + self.seconds
        return 0.0

    def cancel(self, user_id: int) -> None:
        """Undo the wait wait_for just started, so the user can try again now."""
        self.next_use.pop(user_id, None)


def register_manual(
    tree: app_commands.CommandTree,
    oc: OcService,
    oq: OqService,
    oh: OhService | None = None,
    cooldown: Cooldown | None = None,
) -> None:
    oh = oh if oh is not None else OhService(oc)
    cooldown = cooldown or Cooldown(MANUAL_COOLDOWN_SECONDS)

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
        wait = cooldown.wait_for(interaction.user.id)
        if wait:
            ready = discord.utils.format_dt(
                discord.utils.utcnow() + timedelta(seconds=wait), "R"
            )
            await interaction.response.send_message(
                f"You can use /manual-input again {ready}.", ephemeral=True
            )
            return
        received = time.perf_counter()
        sent_at = getattr(interaction, "created_at", None)
        late = (discord.utils.utcnow() - sent_at).total_seconds() if sent_at else 0.0
        sent = False
        try:
            sent = await _send(interaction, game.value, board)
        finally:
            if not sent:
                cooldown.cancel(interaction.user.id)
        took = time.perf_counter() - received
        if late + took >= SLOW_REPLY_SECONDS:
            log.info(
                "slow reply /manual-input $%s: Discord delivered it %.1fs after it "
                "was sent, then the bot took %.1fs to solve, draw and send",
                game.value,
                late,
                took,
            )

    async def _send(interaction: discord.Interaction, game: str, board: str) -> bool:
        if game == "oq":
            return await send_oq_board(interaction, oq, board)
        if game == "oh":
            return await send_oh_board(interaction, oh, board)
        try:
            state = BoardState.parse(board)
        except BoardInputError as err:
            await interaction.response.send_message(
                f"Couldn't read that board: {err}", ephemeral=True
            )
            return False
        return await send_board(interaction, oc, state)
