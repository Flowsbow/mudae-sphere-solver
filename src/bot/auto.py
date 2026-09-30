import asyncio
import re
import time
from dataclasses import dataclass, field

import discord

from src.bot.commands import BoardView, OcService, solve_and_draw
from src.bot.mudae_reader import MUDAE_ID, NotAnOcBoardError, read_oc_board

# "$oc" with Mudae's default "$" prefix, optionally followed by an argument
# ("$oc 2" in Flow's 2026-09-26 screenshot). Servers can change Mudae's prefix.
OC_COMMAND = re.compile(r"^\$oc(\s|$)", re.IGNORECASE)
# Chosen 2026-09-29: a Mudae board this soon after someone types $oc is theirs.
PENDING_SECONDS = 30
# Chosen 2026-09-29: forget games this old; a $oc game lasts 2 minutes.
GAME_MAX_AGE_SECONDS = 15 * 60


@dataclass
class AutoGame:
    view: BoardView
    reply: discord.Message
    embed: discord.Embed
    started: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class AutoTracker:
    def __init__(self, service: OcService) -> None:
        self.service = service
        self.pending: dict[int, tuple[int, float]] = {}
        self.games: dict[int, AutoGame] = {}

    def owner_of(self, board_message: discord.Message) -> int | None:
        metadata = getattr(board_message, "interaction_metadata", None)
        if metadata is not None and metadata.user.id in self.service.auto_users:
            return metadata.user.id
        pending = self.pending.pop(board_message.channel.id, None)
        if pending is None:
            return None
        user_id, when = pending
        if time.monotonic() - when > PENDING_SECONDS:
            return None
        return user_id

    async def on_message(self, message: discord.Message) -> None:
        if message.author.id in self.service.auto_users and OC_COMMAND.match(
            message.content
        ):
            self.pending[message.channel.id] = (message.author.id, time.monotonic())
            return
        if message.author.id != MUDAE_ID:
            return
        try:
            board = read_oc_board(message)
        except NotAnOcBoardError:
            return
        if board.finished:
            return
        owner = self.owner_of(message)
        if owner is None:
            return
        self._forget_old_games()
        view = BoardView(self.service, board.state, owner)
        embed, file = await solve_and_draw(self.service, board.state, view.letters)
        reply = await message.reply(
            embed=embed, file=file, view=view, mention_author=False
        )
        view.message = reply
        self.games[message.id] = AutoGame(view, reply, embed, time.monotonic())

    async def on_message_edit(self, after: discord.Message) -> None:
        game = self.games.get(after.id)
        if game is None:
            return
        try:
            board = read_oc_board(after)
        except NotAnOcBoardError:
            return
        async with game.lock:
            if board.finished:
                await self._finish(after.id, game)
                return
            if board.state == game.view.state:
                return
            embed, file = await solve_and_draw(
                self.service, board.state, game.view.letters
            )
            game.view.state = board.state
            game.view.refresh()
            game.embed = embed
            game.reply = await game.reply.edit(
                embed=embed, attachments=[file], view=game.view
            )

    async def _finish(self, message_id: int, game: AutoGame) -> None:
        self.games.pop(message_id, None)
        game.view.stop()
        for item in game.view.children:
            item.disabled = True
        embed = game.embed.copy()
        embed.title = "Game over"
        embed.description = "The board shows the solver's last recommendation."
        await game.reply.edit(embed=embed, view=game.view)

    def _forget_old_games(self) -> None:
        now = time.monotonic()
        for message_id in [
            m for m, g in self.games.items() if now - g.started > GAME_MAX_AGE_SECONDS
        ]:
            self.games.pop(message_id, None)
