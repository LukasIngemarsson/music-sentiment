"""Discord bot entry point."""
from __future__ import annotations

import asyncio
import datetime as dt
import os

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

import users
from lastfm import LastFMClient, week_window
from sentiment import TagSentimentCache, score_tags
from stats import UserWeek, compute, format_awards

load_dotenv()

TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = os.environ.get("DISCORD_GUILD_ID")
GUILD = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None

WEEKLY_CHANNEL_ID = int(os.environ["WEEKLY_CHANNEL_ID"]) if os.environ.get("WEEKLY_CHANNEL_ID") else None
WEEKLY_POST_WEEKDAY = int(os.environ.get("WEEKLY_POST_WEEKDAY", "6"))  # 0=Mon, 6=Sun
WEEKLY_POST_HOUR_UTC = int(os.environ.get("WEEKLY_POST_HOUR_UTC", "19"))

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@tree.command(name="register", description="Link your Discord account to a Last.fm username")
@app_commands.describe(lastfm_username="Your Last.fm username")
async def register_cmd(interaction: discord.Interaction, lastfm_username: str):
    await interaction.response.defer(ephemeral=True)
    async with LastFMClient() as lfm:
        if not await lfm.user_exists(lastfm_username):
            await interaction.followup.send(f"Can't find Last.fm user `{lastfm_username}`.", ephemeral=True)
            return
    users.register(interaction.user.id, lastfm_username)
    await interaction.followup.send(f"Linked to Last.fm user `{lastfm_username}`.", ephemeral=True)


@tree.command(name="unregister", description="Remove your Last.fm link")
async def unregister_cmd(interaction: discord.Interaction):
    ok = users.unregister(interaction.user.id)
    await interaction.response.send_message(
        "Unlinked." if ok else "You weren't registered.", ephemeral=True
    )


@tree.command(name="who", description="Show who's registered")
async def who_cmd(interaction: discord.Interaction):
    reg = users.all_users()
    if not reg:
        await interaction.response.send_message("Nobody's registered yet. Use `/register`.")
        return
    lines = [f"<@{did}> → `{name}`" for did, name in reg.items()]
    await interaction.response.send_message(
        "\n".join(lines), allowed_mentions=discord.AllowedMentions.none()
    )


async def _resolve_sentiment(
    lfm: LastFMClient,
    cache: TagSentimentCache,
    unique_tracks: set[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, float]]:
    out: dict[tuple[str, str], dict[str, float]] = {}
    artist_cache: dict[str, list[tuple[str, int]]] = {}
    for artist, track in unique_tracks:
        hit = cache.get(artist, track)
        if hit is not None:
            out[(artist.lower(), track.lower())] = hit
            continue
        tags = await lfm.track_top_tags(artist, track)
        if not tags:
            if artist not in artist_cache:
                artist_cache[artist] = await lfm.artist_top_tags(artist)
            tags = artist_cache[artist]
        scores = score_tags(tags)
        cache.put(artist, track, scores, tags)
        out[(artist.lower(), track.lower())] = scores
    return out


async def _build_weekly_message() -> str:
    reg = users.all_users()
    if not reg:
        return "Nobody's registered yet. Use `/register`."

    since, until = week_window()
    weeks: list[UserWeek] = []
    cache = TagSentimentCache()
    try:
        async with LastFMClient() as lfm:
            for discord_id, lfm_user in reg.items():
                try:
                    scrobbles = await lfm.recent_tracks(lfm_user, since=since, until=until)
                except Exception as e:
                    print(f"[weekly] failed to fetch {lfm_user}: {e}")
                    continue
                unique = {(s.artist, s.track) for s in scrobbles if s.artist and s.track}
                sentiment = await _resolve_sentiment(lfm, cache, unique)
                weeks.append(
                    UserWeek(user=f"<@{discord_id}>", scrobbles=scrobbles, track_sentiment=sentiment)
                )
    finally:
        cache.save()

    return format_awards(compute(weeks))


@tasks.loop(time=dt.time(hour=WEEKLY_POST_HOUR_UTC, minute=0, tzinfo=dt.timezone.utc))
async def weekly_autopost():
    if dt.datetime.now(dt.timezone.utc).weekday() != WEEKLY_POST_WEEKDAY:
        return
    if WEEKLY_CHANNEL_ID is None:
        return
    channel = client.get_channel(WEEKLY_CHANNEL_ID) or await client.fetch_channel(WEEKLY_CHANNEL_ID)
    msg = await _build_weekly_message()
    await channel.send(msg, allowed_mentions=discord.AllowedMentions.none())
    print("[weekly_autopost] posted")


@weekly_autopost.before_loop
async def _before_autopost():
    await client.wait_until_ready()


@client.event
async def on_ready():
    if GUILD:
        tree.copy_global_to(guild=GUILD)
        await tree.sync(guild=GUILD)
    else:
        await tree.sync()
    if WEEKLY_CHANNEL_ID and not weekly_autopost.is_running():
        weekly_autopost.start()
        print(f"Autopost scheduled for weekday {WEEKLY_POST_WEEKDAY} @ {WEEKLY_POST_HOUR_UTC:02d}:00 UTC")
    print(f"Logged in as {client.user}")


def main():
    asyncio.run(client.start(TOKEN))


if __name__ == "__main__":
    main()
