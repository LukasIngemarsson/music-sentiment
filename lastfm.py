"""Last.fm API client — public read-only endpoints, app-level key only."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import aiohttp

BASE_URL = "https://ws.audioscrobbler.com/2.0/"


@dataclass
class Scrobble:
    artist: str
    track: str
    album: str
    timestamp: int  # unix seconds; 0 if "now playing"


class LastFMClient:
    def __init__(self, api_key: str | None = None, session: aiohttp.ClientSession | None = None):
        self.api_key = api_key or os.environ["LASTFM_API_KEY"]
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self):
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *_):
        if self._owns_session and self._session is not None:
            await self._session.close()

    async def _get(self, method: str, **params) -> dict:
        params = {"method": method, "api_key": self.api_key, "format": "json", **params}
        async with self._session.get(BASE_URL, params=params) as r:
            r.raise_for_status()
            return await r.json()

    async def recent_tracks(self, user: str, since: int, until: int | None = None) -> list[Scrobble]:
        """All scrobbles for `user` in [since, until]. Paginates until exhausted."""
        out: list[Scrobble] = []
        page = 1
        while True:
            params = {"user": user, "from": since, "limit": 200, "page": page}
            if until is not None:
                params["to"] = until
            data = await self._get("user.getrecenttracks", **params)
            tracks = data.get("recenttracks", {}).get("track", [])
            if isinstance(tracks, dict):
                tracks = [tracks]
            for t in tracks:
                if t.get("@attr", {}).get("nowplaying") == "true":
                    continue
                ts = int(t.get("date", {}).get("uts", 0))
                out.append(
                    Scrobble(
                        artist=t["artist"].get("#text", ""),
                        track=t.get("name", ""),
                        album=t.get("album", {}).get("#text", ""),
                        timestamp=ts,
                    )
                )
            attr = data.get("recenttracks", {}).get("@attr", {})
            total_pages = int(attr.get("totalPages", 1))
            if page >= total_pages:
                break
            page += 1
        return out

    async def user_exists(self, user: str) -> bool:
        try:
            await self._get("user.getinfo", user=user)
            return True
        except aiohttp.ClientResponseError:
            return False

    async def track_top_tags(self, artist: str, track: str) -> list[tuple[str, int]]:
        """Return [(tag_name_lower, count_0_to_100)] for a track. Empty if unknown."""
        try:
            data = await self._get("track.gettoptags", artist=artist, track=track, autocorrect=1)
        except aiohttp.ClientResponseError:
            return []
        tags = data.get("toptags", {}).get("tag", [])
        if isinstance(tags, dict):
            tags = [tags]
        out = []
        for t in tags:
            try:
                out.append((t["name"].lower(), int(t.get("count", 0))))
            except (KeyError, ValueError):
                continue
        return out

    async def artist_top_tags(self, artist: str) -> list[tuple[str, int]]:
        """Fallback when track-level tags are empty."""
        try:
            data = await self._get("artist.gettoptags", artist=artist, autocorrect=1)
        except aiohttp.ClientResponseError:
            return []
        tags = data.get("toptags", {}).get("tag", [])
        if isinstance(tags, dict):
            tags = [tags]
        out = []
        for t in tags:
            try:
                out.append((t["name"].lower(), int(t.get("count", 0))))
            except (KeyError, ValueError):
                continue
        return out


def week_window(now: int | None = None) -> tuple[int, int]:
    """Return (since, until) unix timestamps for the trailing 7 days."""
    now = now or int(time.time())
    return now - 7 * 24 * 3600, now
