"""Tiny JSON-file registry mapping Discord user IDs to Last.fm usernames."""
from __future__ import annotations

import json
from pathlib import Path

REGISTRY_PATH = Path("data/users.json")


def _load() -> dict[str, str]:
    if not REGISTRY_PATH.exists():
        return {}
    return json.loads(REGISTRY_PATH.read_text())


def _save(data: dict[str, str]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(data, indent=2))


def register(discord_id: int, lastfm_user: str) -> None:
    data = _load()
    data[str(discord_id)] = lastfm_user
    _save(data)


def unregister(discord_id: int) -> bool:
    data = _load()
    if str(discord_id) in data:
        del data[str(discord_id)]
        _save(data)
        return True
    return False


def all_users() -> dict[str, str]:
    return _load()
