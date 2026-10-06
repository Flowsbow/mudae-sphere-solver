import asyncio
import re
import time
from dataclasses import dataclass, field, replace

import discord

from src.bot.commands import BoardView, OcService, solve_and_draw
from src.bot.mudae_reader import (
    MUDAE_ID,
    OQ_RULES,
    MudaeBoard,
    NotAnOcBoardError,
    NotAnOqBoardError,
    is_sphere_board,
    read_oc_board,
    read_oq_board,
)
from src.bot.oq import OqBoardView, OqService
from src.bot.rewards import (
    EMOJI_LABEL,
    REWARDS_PLACEHOLDER,
    ChannelLog,
    created_ms,
    parse_rewards,
)
from src.bot.totals import OQ_LABELS, OcResult, OqResult, StatsStore
from src.solver.board import BoardState, Color
from src.solver.ev import InconsistentBoardError
from src.solver.modes.oq import PURPLE, RED
from src.solver.stats import game_stats

# "$oc" or "$oq" with Mudae's default "$" prefix, optionally followed by an
# argument ("$oc 2" in Flow's 2026-09-26 screenshot). Servers can change the prefix.
GAME_COMMAND = re.compile(r"^\$o([cq])(\s|$)", re.IGNORECASE)
# Chosen 2026-09-29: a Mudae board this soon after someone types $oc is theirs.
PENDING_SECONDS = 30
# Chosen 2026-09-29: forget games this old; a game lasts 2 minutes.
GAME_MAX_AGE_SECONDS = 15 * 60

Result = OcResult | OqResult


@dataclass
class AutoGame:
    view: BoardView | OqBoardView
    reply: discord.Message
    started: float
    channel_id: int
    server_id: int | None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def oc_result(view: BoardView, cells: tuple[Color | None, ...]) -> OcResult:
    stats = game_stats(view.history, view.payouts, view.expected)
    return OcResult(
        clicks=tuple(step.color.name for step in stats.steps),
        spheres_gained=0,
        picks=stats.judged,
        picks_followed=stats.followed,
        score=stats.score,
        expected=stats.expected,
        red_cell=cells.index(Color.RED),
    )


def oq_label(code: int, rainbow: bool) -> str:
    if code == RED:
        return "RAINBOW" if rainbow else "RED"
    return "PURPLE" if code == PURPLE else OQ_LABELS[code]


def oq_result(view: OqBoardView) -> OqResult:
    stats = view.final_stats
    return OqResult(
        clicks=tuple(oq_label(view.codes[c], view.rainbow) for c in view.history),
        spheres_gained=0,
        picks=stats.judged,
        picks_followed=stats.followed,
        score=stats.score,
        best=stats.best,
        expected=stats.expected,
    )


class AutoTracker:
    def __init__(
        self,
        service: OcService,
        stats: StatsStore | None = None,
        oq: OqService | None = None,
    ) -> None:
        self.service = service
        self.oq = oq if oq is not None else OqService(service)
        self.stats = stats if stats is not None else StatsStore()
        # Channel -> (player, when they typed it, "oc" or "oq").
        self.pending: dict[int, tuple[int, float, str]] = {}
        self.games: dict[int, AutoGame] = {}
        self.log = ChannelLog()
        self.rewards_text: dict[int, str] = {}
        # Rewards message ID -> (player, game) for finished games whose rewards
        # message hasn't caught up with every click yet.
        self.awaiting: dict[int, tuple[int, Result]] = {}

    def owner_of(self, board_message: discord.Message, game: str) -> int | None:
        metadata = getattr(board_message, "interaction_metadata", None)
        if metadata is not None and metadata.user.id in self.service.auto_users:
            return metadata.user.id
        pending = self.pending.get(board_message.channel.id)
        if pending is None or pending[2] != game:
            return None
        del self.pending[board_message.channel.id]
        user_id, when, _ = pending
        if time.monotonic() - when > PENDING_SECONDS:
            return None
        return user_id

    async def on_message(self, message: discord.Message) -> None:
        command = GAME_COMMAND.match(message.content)
        if message.author.id in self.service.auto_users and command:
            game = f"o{command[1].lower()}"
            self.pending[message.channel.id] = (
                message.author.id,
                time.monotonic(),
                game,
            )
            return
        if message.author.id != MUDAE_ID:
            return
        self._forget_old(message.id)
        if message.content == REWARDS_PLACEHOLDER:
            self.log.add_rewards(message.channel.id, message.id)
            self.rewards_text[message.id] = message.content
            return
        if is_sphere_board(message):
            self.log.add_board(message.channel.id, message.id)
        if OQ_RULES in message.content:
            await self._start_oq(message)
        else:
            await self._start_oc(message)

    async def _start_oc(self, message: discord.Message) -> None:
        try:
            board = read_oc_board(message)
        except NotAnOcBoardError:
            return
        if board.finished:
            return
        owner = self.owner_of(message, "oc")
        if owner is None:
            return
        letters = self.service.letters_for.get(owner, False)
        server = message.guild.id if message.guild else None
        payouts = self.service.payouts_for(owner, server)
        embed, file, analysis = await solve_and_draw(
            self.service, board.state, letters, payouts
        )
        view = BoardView(
            self.service, board.state, owner, analysis, manual=False, payouts=payouts
        )
        await self._reply(message, view, embed, file)

    async def _start_oq(self, message: discord.Message) -> None:
        try:
            board = read_oq_board(message)
        except NotAnOqBoardError:
            return
        if board.finished:
            return
        owner = self.owner_of(message, "oq")
        if owner is None:
            return
        server = message.guild.id if message.guild else None
        payouts = self.oq.payouts_for(owner, server)
        view = OqBoardView(self.oq, board.codes, owner, payouts, manual=False)
        try:
            embed, file = await view.update(board.codes)
        except InconsistentBoardError:
            return
        await self._reply(message, view, embed, file)

    async def _reply(
        self,
        message: discord.Message,
        view: BoardView | OqBoardView,
        embed: discord.Embed,
        file: discord.File,
    ) -> None:
        reply = await message.reply(
            embed=embed, file=file, view=view, mention_author=False
        )
        view.message = reply
        server = message.guild.id if message.guild else None
        self.games[message.id] = AutoGame(
            view, reply, time.monotonic(), message.channel.id, server
        )

    async def on_message_edit(self, after: discord.Message) -> None:
        if after.id in self.rewards_text:
            self.rewards_text[after.id] = after.content
            self._try_record(after.id)
            return
        game = self.games.get(after.id)
        if game is None:
            return
        if isinstance(game.view, OqBoardView):
            await self._oq_edit(after, game)
        else:
            await self._oc_edit(after, game)

    async def _oc_edit(self, after: discord.Message, game: AutoGame) -> None:
        try:
            board = read_oc_board(after)
        except NotAnOcBoardError:
            return
        async with game.lock:
            # Another edit may have finished this game while we waited.
            if self.games.get(after.id) is not game:
                return
            if board.finished:
                await self._finish_oc(after.id, game, board)
                return
            if board.state == game.view.state:
                return
            embed, file, analysis = await solve_and_draw(
                self.service, board.state, game.view.letters, game.view.payouts
            )
            game.view.advance(board.state, analysis)
            game.view.refresh()
            game.reply = await game.reply.edit(
                embed=embed, attachments=[file], view=game.view
            )

    async def _finish_oc(
        self, message_id: int, game: AutoGame, board: MudaeBoard
    ) -> None:
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
        # Recorded before the reply edit, so a failed edit can't lose the game.
        self._await_rewards(message_id, game, oc_result(view, board.state.revealed))
        game.reply = await game.reply.edit(embed=embed, attachments=[file], view=view)

    async def _oq_edit(self, after: discord.Message, game: AutoGame) -> None:
        try:
            board = read_oq_board(after)
        except NotAnOqBoardError:
            return
        view = game.view
        async with game.lock:
            if self.games.get(after.id) is not game:
                return
            if board.codes == view.codes and not board.finished:
                return
            if board.rainbow and not view.rainbow:
                payouts = self.oq.payouts_for(view.owner_id, game.server_id, True)
                view.use_rainbow(payouts)
            try:
                embed, file = await view.update(
                    board.codes, final=board.finished, layout=board.layout
                )
            except InconsistentBoardError:
                return
            if board.finished:
                self.games.pop(after.id, None)
                self._await_rewards(after.id, game, oq_result(view))
            game.reply = await game.reply.edit(
                embed=embed, attachments=[file], view=view
            )

    def _await_rewards(self, board_id: int, game: AutoGame, result: Result) -> None:
        rewards_id = self.log.rewards_for(game.channel_id, board_id)
        if rewards_id is not None:
            self.awaiting[rewards_id] = (game.view.owner_id, result)
            self._try_record(rewards_id)

    def _try_record(self, rewards_id: int) -> None:
        waiting = self.awaiting.get(rewards_id)
        if waiting is None:
            return
        owner, result = waiting
        rewards = parse_rewards(self.rewards_text.get(rewards_id, ""))
        if len(rewards) < len(result.clicks):
            return
        del self.awaiting[rewards_id]
        if [EMOJI_LABEL.get(r.emoji) for r in rewards] != list(result.clicks):
            return
        gained = sum(r.spheres for r in rewards)
        self.stats.record(owner, replace(result, spheres_gained=gained))

    def _forget_old(self, newest_id: int) -> None:
        now = time.monotonic()
        for message_id in [
            m for m, g in self.games.items() if now - g.started > GAME_MAX_AGE_SECONDS
        ]:
            self.games.pop(message_id, None)
        cutoff = created_ms(newest_id) - GAME_MAX_AGE_SECONDS * 1000
        self.log.forget_before(cutoff)
        for log in (self.rewards_text, self.awaiting):
            for message_id in [m for m in log if created_ms(m) < cutoff]:
                del log[message_id]
