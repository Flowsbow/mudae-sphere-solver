import asyncio
import os

import discord
from discord import app_commands
from dotenv import load_dotenv

from src.bot.commands import OcService, register


class SolverBot(discord.Client):
    def __init__(self, guild_id: int | None) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.service = OcService()
        self.guild_id = guild_id
        self.warm_up_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        register(self.tree, self.service)
        if self.guild_id is not None:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self.warm_up_task = asyncio.create_task(self.service.warm_up())


def main() -> None:
    load_dotenv()
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN is missing. Put it in the .env file.")
    guild_id = os.environ.get("DISCORD_GUILD_ID")
    SolverBot(int(guild_id) if guild_id else None).run(token)


if __name__ == "__main__":
    main()
