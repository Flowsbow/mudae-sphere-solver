import asyncio
import re
import time
from dataclasses import dataclass, field

import discord

from src.bot.commands import BoardView, OcService, solve_and_draw
from src.bot.mudae_reader import (
    MUDAE_ID,
    MudaeBoard,
    NotAnOcBoardError,
    read_oc_board,
)
from src.solver.board import BoardState

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
        letters = self.service.letters_for.get(owner, False)
        server = message.guild.id if message.guild else None
        payouts = self.service.payouts_for(owner, server)
        embed, file, analysis = await solve_and_draw(
            self.service, board.state, letters, payouts
        )
        view = BoardView(
            self.service, board.state, owner, analysis, manual=False, payouts=payouts
        )
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
                await self._finish(after.id, game, board)
                return
            if board.state == game.view.state:
                return
            embed, file, analysis = await solve_and_draw(
                self.service, board.state, game.view.letters, game.view.payouts
            )
            game.view.advance(board.state, analysis)
            game.view.refresh()
            game.embed = embed
            game.reply = await game.reply.edit(
                embed=embed, attachments=[file], view=game.view
            )

    async def _finish(self, message_id: int, game: AutoGame, board: MudaeBoard) -> None:
        self.games.pop(message_id, None)
        view = game.view
        clicked_state = BoardState(
            tuple(
                color if cell in board.clicked else None
                for cell, color in enumerate(board.state.revealed)
            )
        )
        if board.clicked:
            view.advance(clicked_state)
            clicked = board.clicked
        else:
            clicked = frozenset(step.cell for step in view.history)
        embed, file = view.finish(board.state.revealed, clicked)
        view.refresh()
        game.reply = await game.reply.edit(embed=embed, attachments=[file], view=view)

    def _forget_old_games(self) -> None:
        now = time.monotonic()
        for message_id in [
            m for m, g in self.games.items() if now - g.started > GAME_MAX_AGE_SECONDS
        ]:
            self.games.pop(message_id, None)
