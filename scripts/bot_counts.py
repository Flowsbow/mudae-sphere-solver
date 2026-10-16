import asyncio
import os
from getpass import getpass

import discord
from dotenv import load_dotenv


async def counts(token: str) -> None:
    async with discord.Client(intents=discord.Intents.none()) as client:
        await client.login(token)
        guilds = [guild async for guild in client.fetch_guilds(limit=None)]
        app = await client.application_info()
    members = sum(guild.approximate_member_count or 0 for guild in guilds)
    print(f"Servers: {len(guilds)}")
    print(f"Members across servers: {members} (someone in two servers counts twice)")
    print(f"Account installs: {app.approximate_user_install_count}")


def main() -> None:
    load_dotenv()
    token = os.environ.get("DISCORD_TOKEN") or getpass("Bot token (hidden): ")
    try:
        asyncio.run(counts(token.strip()))
    except discord.LoginFailure:
        raise SystemExit("Discord rejected that token.") from None


if __name__ == "__main__":
    main()
