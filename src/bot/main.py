import asyncio
import os
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv

from src.bot.auto import AutoTracker
from src.bot.commands import OcService, register
from src.bot.inspector import register_inspector
from src.bot.manual import register_manual
from src.bot.oq import OqService
from src.bot.stats_commands import register_stats
from src.bot.totals import StatsStore


class SolverBot(discord.Client):
    def __init__(
        self, guild_id: int | None, settings_path: Path, stats: StatsStore
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.service = OcService(settings_path)
        self.oq = OqService(self.service)
        self.stats = stats
        self.auto = AutoTracker(self.service, stats, self.oq)
        self.guild_id = guild_id
        self.warm_up_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        register(self.tree, self.service)
        register_manual(self.tree, self.service, self.oq)
        register_stats(self.tree, self.stats)
        register_inspector(self.tree)
        if self.guild_id is not None:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self.warm_up_task = asyncio.create_task(self.service.warm_up())

    async def on_message(self, message: discord.Message) -> None:
        await self.auto.on_message(message)

    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        await self.auto.on_message_edit(after)


def main() -> None:
    load_dotenv()
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN is missing. Put it in the .env file.")
    guild_id = os.environ.get("DISCORD_GUILD_ID")
    settings_path = Path(os.environ.get("SETTINGS_FILE", "settings.json"))
    stats = StatsStore(
        Path(os.environ.get("STATS_FILE", "stats.json")),
        Path(os.environ.get("MY_STATS_FILE", "my_stats.json")),
    )
    SolverBot(int(guild_id) if guild_id else None, settings_path, stats).run(token)


if __name__ == "__main__":
    main()
