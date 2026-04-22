"""Tag-based sentiment scoring from Last.fm tags.

Each tag maps to one or more affective dimensions. Per-track score is the
max-weighted tag hit (Last.fm tag counts are 0–100 popularity). Per-user
score is the mean across all scrobbles, weighted by play frequency.
"""
from __future__ import annotations

import json
from pathlib import Path

CACHE_PATH = Path("data/lastfm_tags.json")

# Each entry: tag substring → {dimension: weight}. Substring match so e.g.
# "melancholic" catches "melancholy". Weights are roughly unit-scale.
TAG_MAP: dict[str, dict[str, float]] = {
    # sadness
    "sad": {"sad": 1.0},
    "melancho": {"sad": 0.9},
    "depress": {"sad": 1.0},
    "bittersweet": {"sad": 0.6},
    "heartbreak": {"sad": 0.8},
    "breakup": {"sad": 0.7},
    "lonely": {"sad": 0.7},
    "somber": {"sad": 0.7},
    "sombre": {"sad": 0.7},
    "sorrow": {"sad": 0.9},
    "emo": {"sad": 0.5},
    "tragic": {"sad": 0.7},
    # happiness
    "happy": {"happy": 1.0},
    "upbeat": {"happy": 0.8, "energy": 0.5},
    "cheerful": {"happy": 0.9},
    "feel good": {"happy": 0.9},
    "feelgood": {"happy": 0.9},
    "joyful": {"happy": 1.0},
    "uplifting": {"happy": 0.8},
    "summer": {"happy": 0.4},
    "fun": {"happy": 0.5},
    # energy
    "energetic": {"energy": 1.0},
    "hype": {"energy": 1.0},
    "banger": {"energy": 0.9},
    "aggressive": {"energy": 0.9},
    "intense": {"energy": 0.8},
    "hard": {"energy": 0.6},
    "heavy": {"energy": 0.7},
    "pumped": {"energy": 0.8},
    "dance": {"energy": 0.6, "happy": 0.3},
    # chill (its own positive dimension)
    "chill": {"chill": 0.9},
    "chillout": {"chill": 1.0},
    "relax": {"chill": 0.9},
    "mellow": {"chill": 0.8},
    "calm": {"chill": 0.8},
    "ambient": {"chill": 0.7},
    "dreamy": {"chill": 0.6},
    "sleep": {"chill": 0.9},
    "lo-fi": {"chill": 0.8},
    "lofi": {"chill": 0.8},
    # dark (proxy for sad-adjacent)
    "dark": {"sad": 0.4},
    "moody": {"sad": 0.5},
    # genre → mood priors (weaker weights; only fire when stronger mood tags absent)
    "country": {"happy": 0.3},
    "bro-country": {"happy": 0.3, "energy": 0.2},
    "folk": {"chill": 0.3},
    "singer-songwriter": {"chill": 0.3, "sad": 0.2},
    "acoustic": {"chill": 0.4},
    "classical": {"chill": 0.4},
    "jazz": {"chill": 0.3},
    "soul": {"happy": 0.2, "chill": 0.2},
    "neo-soul": {"chill": 0.3},
    "rnb": {"chill": 0.2},
    "r&b": {"chill": 0.2},
    "dream pop": {"chill": 0.5},
    "shoegaze": {"chill": 0.4, "sad": 0.2},
    "vaporwave": {"chill": 0.6},
    "bedroom pop": {"chill": 0.5},
    "hip-hop": {"energy": 0.3},
    "hip hop": {"energy": 0.3},
    "rap": {"energy": 0.3},
    "trap": {"energy": 0.4},
    "drill": {"energy": 0.6},
    "gangsta rap": {"energy": 0.5},
    "boom bap": {"energy": 0.3},
    "phonk": {"energy": 0.5},
    "rock": {"energy": 0.3},
    "classic rock": {"energy": 0.3},
    "punk": {"energy": 0.6},
    "hardcore": {"energy": 0.8},
    "metal": {"energy": 0.7},
    "nu metal": {"energy": 0.8},
    "nu-metal": {"energy": 0.8},
    "rapcore": {"energy": 0.7},
    "grunge": {"energy": 0.4, "sad": 0.3},
    "emo": {"sad": 0.5},
    "screamo": {"energy": 0.7, "sad": 0.4},
    "electronic": {"energy": 0.3},
    "house": {"energy": 0.5, "happy": 0.3},
    "techno": {"energy": 0.6},
    "tropical house": {"happy": 0.3, "chill": 0.3},
    "electro-swing": {"energy": 0.4, "happy": 0.3},
    "swing": {"energy": 0.3, "happy": 0.3},
    "disco": {"happy": 0.5, "energy": 0.4},
    "funk": {"happy": 0.4, "energy": 0.3},
    "reggae": {"chill": 0.5, "happy": 0.3},
    "indie pop": {"happy": 0.2},
    "power pop": {"happy": 0.3, "energy": 0.4},
}

DIMENSIONS = ("sad", "happy", "energy", "chill")


# Order needles by length descending so "nu metal" beats "metal", "dream pop"
# beats "pop", etc. (substring match would otherwise pick the generic one).
_NEEDLES_BY_LENGTH = sorted(TAG_MAP.items(), key=lambda kv: -len(kv[0]))


def score_tags(tags: list[tuple[str, int]]) -> dict[str, float]:
    """Score a single track's tag list. Returns {dimension: score in [0,1]-ish}."""
    scores = {d: 0.0 for d in DIMENSIONS}
    if not tags:
        return scores
    for tag_name, count in tags:
        weight = count / 100.0  # Last.fm tag counts are 0–100
        for needle, dims in _NEEDLES_BY_LENGTH:
            if needle in tag_name:
                for dim, w in dims.items():
                    # Take the strongest signal per dimension rather than summing.
                    contrib = w * weight
                    if abs(contrib) > abs(scores[dim]):
                        scores[dim] = contrib
                break
    return scores


class TagSentimentCache:
    """Persistent cache of per-track sentiment + raw tags."""

    def __init__(self):
        # {key: {"scores": {...}, "tags": [[name, count], ...]}}
        self._cache: dict[str, dict] = {}
        if CACHE_PATH.exists():
            raw = json.loads(CACHE_PATH.read_text())
            # Back-compat: old cache was {key: scores_dict}; upgrade lazily.
            for k, v in raw.items():
                if isinstance(v, dict) and "scores" in v:
                    self._cache[k] = v
                else:
                    self._cache[k] = {"scores": v, "tags": []}

    @staticmethod
    def _key(artist: str, track: str) -> str:
        return f"{artist.lower()}\x1f{track.lower()}"

    def get(self, artist: str, track: str) -> dict[str, float] | None:
        entry = self._cache.get(self._key(artist, track))
        return entry["scores"] if entry else None

    def get_tags(self, artist: str, track: str) -> list[tuple[str, int]]:
        entry = self._cache.get(self._key(artist, track))
        if not entry:
            return []
        return [(n, c) for n, c in entry.get("tags", [])]

    def put(
        self,
        artist: str,
        track: str,
        scores: dict[str, float],
        tags: list[tuple[str, int]] | None = None,
    ) -> None:
        self._cache[self._key(artist, track)] = {
            "scores": scores,
            "tags": [[n, c] for n, c in (tags or [])],
        }

    def save(self) -> None:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(self._cache))
