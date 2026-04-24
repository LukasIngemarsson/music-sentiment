"""GitHub Actions entrypoint: build weekly awards and post to Discord webhook."""

import asyncio
import os

import aiohttp
from dotenv import load_dotenv

from . import users
from .lastfm import LastFMClient, week_window
from .sentiment import TagSentimentCache, score_tags
from .stats import UserWeek, compute, format_awards

load_dotenv()


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
        return "Nobody's registered yet."

    since, until = week_window()
    weeks: list[UserWeek] = []
    cache = TagSentimentCache()
    try:
        async with LastFMClient() as lfm:
            for _discord_id, lfm_user in reg.items():
                try:
                    scrobbles = await lfm.recent_tracks(
                        lfm_user, since=since, until=until
                    )
                except Exception as e:
                    print(f"[weekly] failed to fetch {lfm_user}: {e}")
                    continue
                unique = {
                    (s.artist, s.track) for s in scrobbles if s.artist and s.track
                }
                sentiment = await _resolve_sentiment(lfm, cache, unique)
                weeks.append(
                    UserWeek(
                        user=lfm_user,
                        scrobbles=scrobbles,
                        track_sentiment=sentiment,
                    )
                )
    finally:
        cache.save()

    return format_awards(compute(weeks))


async def _post_webhook(content: str) -> None:
    webhook = os.environ["DISCORD_WEBHOOK_URL"]
    async with aiohttp.ClientSession() as session:
        async with session.post(webhook, json={"content": content}) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Webhook post failed ({resp.status}): {body}")


async def main() -> None:
    msg = await _build_weekly_message()
    dry_run = os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes", "on"}
    if dry_run:
        print(msg)
        print("DRY_RUN enabled; not posting to Discord.")
        return
    await _post_webhook(msg)
    print("[weekly_post] posted")


def run() -> None:
    asyncio.run(main())
