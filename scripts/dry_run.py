"""Local dry-run: compute /weekly awards against data/users.json and print.

Usage:
    python scripts/dry_run.py              # just print the awards
    python scripts/dry_run.py --verbose    # also print per-user breakdown
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

import users
from lastfm import LastFMClient, week_window
from sentiment import DIMENSIONS, TagSentimentCache, score_tags
from stats import UserWeek, compute, format_awards, DISPLAY_SCALE

load_dotenv()


async def resolve_sentiment(lfm, cache, unique):
    """Returns (scores_map, tags_map) where tags_map is (artist,track)->[(tag,count)]."""
    scores_out = {}
    tags_out = {}
    artist_cache = {}
    for artist, track in unique:
        key = (artist.lower(), track.lower())
        hit = cache.get(artist, track)
        if hit is not None:
            scores_out[key] = hit
            tags_out[key] = cache.get_tags(artist, track)
            continue
        tags = await lfm.track_top_tags(artist, track)
        if not tags:
            if artist not in artist_cache:
                artist_cache[artist] = await lfm.artist_top_tags(artist)
            tags = artist_cache[artist]
        scores = score_tags(tags)
        cache.put(artist, track, scores, tags)
        scores_out[key] = scores
        tags_out[key] = tags
    return scores_out, tags_out


def print_user_breakdown(week: UserWeek, tags_map: dict, top_n: int = 8) -> None:
    print(f"\n─── {week.user} ─────────────────────────────────")
    print(f"  scrobbles: {len(week.scrobbles)}")
    print(f"  distinct artists: {len({s.artist for s in week.scrobbles})}")

    dim_means = {}
    for dim in DIMENSIONS:
        vals = week.dim_values(dim)
        if vals:
            raw = mean(vals)
            dim_means[dim] = raw
            scaled = min(1.0, raw * DISPLAY_SCALE)
            hit_rate = sum(1 for v in vals if v > 0) / len(vals)
            print(f"  {dim:>7}: raw {raw:.3f} → display {scaled:.2f}  ({hit_rate:.0%} of tracks had a {dim} tag)")

    counts = Counter((s.artist, s.track) for s in week.scrobbles)
    top_tracks = counts.most_common(top_n)
    print(f"  top {len(top_tracks)} tracks:")
    for (artist, track), plays in top_tracks:
        key = (artist.lower(), track.lower())
        tags = tags_map.get(key, [])[:5]
        scores = week.track_sentiment.get(key, {})
        nonzero = {d: f"{v:.2f}" for d, v in scores.items() if v > 0}
        tag_str = ", ".join(f"{n}({c})" for n, c in tags) if tags else "—"
        score_str = ", ".join(f"{d}={v}" for d, v in nonzero.items()) if nonzero else "—"
        print(f"    {plays:>3}× {artist} — {track}")
        print(f"        tags: {tag_str}")
        print(f"        scores: {score_str}")


async def main(verbose: bool):
    reg = users.all_users()
    if not reg:
        print("No users in data/users.json")
        return

    since, until = week_window()
    weeks: list[UserWeek] = []
    all_tags: dict[str, dict] = {}
    cache = TagSentimentCache()
    try:
        async with LastFMClient() as lfm:
            for discord_id, lfm_user in reg.items():
                print(f"fetching {lfm_user}...", flush=True)
                try:
                    scrobbles = await lfm.recent_tracks(lfm_user, since=since, until=until)
                except Exception as e:
                    print(f"  failed: {e}")
                    continue
                print(f"  {len(scrobbles)} scrobbles")
                unique = {(s.artist, s.track) for s in scrobbles if s.artist and s.track}
                sentiment, tags_map = await resolve_sentiment(lfm, cache, unique)
                week = UserWeek(user=lfm_user, scrobbles=scrobbles, track_sentiment=sentiment)
                weeks.append(week)
                all_tags[lfm_user] = tags_map
    finally:
        cache.save()

    if verbose:
        for w in weeks:
            print_user_breakdown(w, all_tags[w.user])

    print("\n" + "=" * 48)
    print(format_awards(compute(weeks)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", "-v", action="store_true", help="print per-user breakdown")
    args = ap.parse_args()
    asyncio.run(main(args.verbose))
