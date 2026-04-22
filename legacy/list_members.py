"""One-off: dump all members of DISCORD_GUILD_ID as `username: id`.

Requires the Server Members Intent enabled in the Developer Portal.
Run: python legacy/list_members.py
"""

import asyncio
import os
import sys

import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])

intents = discord.Intents.default()
intents.members = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    guild = client.get_guild(GUILD_ID) or await client.fetch_guild(GUILD_ID)
    print(f"# {guild.name} - {guild.member_count} members\n", file=sys.stderr)
    async for member in guild.fetch_members(limit=None):
        if member.bot:
            continue
        print(f"{member.display_name}\t{member.name}\t{member.id}")
    await client.close()


asyncio.run(client.start(TOKEN))
