"""Compute the weekly award stats across users."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import mean, pstdev

from lastfm import Scrobble


# Raw mean scores are small because many tracks contribute 0 (no tag match).
# Multiply for display so numbers read in a natural 0–1-ish range. This is
# pure presentation — it does not change rankings.
DISPLAY_SCALE = 1.0


@dataclass
class UserWeek:
    user: str
    scrobbles: list[Scrobble]
    # per-(artist_lower, track_lower) sentiment dict keyed by dimension
    track_sentiment: dict[tuple[str, str], dict[str, float]]

    def dim_values(self, dim: str) -> list[float]:
        out: list[float] = []
        for s in self.scrobbles:
            sc = self.track_sentiment.get((s.artist.lower(), s.track.lower()))
            if sc is not None:
                out.append(sc.get(dim, 0.0))
        return out


@dataclass
class Awards:
    most_listened: tuple[str, int] | None
    # mood awards are (winner, winner_val, runner_up_val, group_avg)
    saddest: tuple[str, float, float, float] | None
    happiest: tuple[str, float, float, float] | None
    most_energetic: tuple[str, float, float, float] | None
    most_chill: tuple[str, float, float, float] | None
    most_obsessive: tuple[str, str, int, float] | None  # user, track, plays, share
    most_chaotic: tuple[str, float, float, float] | None
    most_varied: tuple[str, int] | None  # unique artists


def _dim_leader(weeks: list[UserWeek], dim: str) -> tuple[str, float, float, float] | None:
    means: dict[str, float] = {}
    for w in weeks:
        vals = w.dim_values(dim)
        if vals:
            means[w.user] = mean(vals)
    if not means:
        return None
    sorted_means = sorted(means.values(), reverse=True)
    winner_user = max(means.items(), key=lambda x: x[1])[0]
    winner_val = sorted_means[0]
    runner_up = sorted_means[1] if len(sorted_means) > 1 else 0.0
    group_avg = sum(sorted_means) / len(sorted_means)
    return (winner_user, winner_val, runner_up, group_avg)


def compute(weeks: list[UserWeek]) -> Awards:
    most_listened = max(
        ((w.user, len(w.scrobbles)) for w in weeks if w.scrobbles),
        key=lambda x: x[1],
        default=None,
    )

    saddest = _dim_leader(weeks, "sad")
    happiest = _dim_leader(weeks, "happy")
    most_energetic = _dim_leader(weeks, "energy")
    most_chill = _dim_leader(weeks, "chill")

    mood_stdevs: dict[str, float] = {}
    for w in weeks:
        sads = w.dim_values("sad")
        happies = w.dim_values("happy")
        nets = [h - s for h, s in zip(happies, sads)]
        if len(nets) > 1:
            mood_stdevs[w.user] = pstdev(nets)
    if mood_stdevs:
        sorted_stdevs = sorted(mood_stdevs.values(), reverse=True)
        chaotic_user = max(mood_stdevs.items(), key=lambda x: x[1])[0]
        most_chaotic = (
            chaotic_user,
            sorted_stdevs[0],
            sorted_stdevs[1] if len(sorted_stdevs) > 1 else 0.0,
            sum(sorted_stdevs) / len(sorted_stdevs),
        )
    else:
        most_chaotic = None

    most_obsessive = None
    best_share = 0.0
    for w in weeks:
        if not w.scrobbles:
            continue
        counts = Counter((s.artist, s.track) for s in w.scrobbles)
        (artist, track), plays = counts.most_common(1)[0]
        share = plays / len(w.scrobbles)
        if share > best_share and plays >= 3:
            best_share = share
            most_obsessive = (w.user, f"{artist} — {track}", plays, share)

    most_varied = max(
        ((w.user, len({s.artist for s in w.scrobbles})) for w in weeks if w.scrobbles),
        key=lambda x: x[1],
        default=None,
    )

    return Awards(
        most_listened=most_listened,
        saddest=saddest,
        happiest=happiest,
        most_energetic=most_energetic,
        most_chill=most_chill,
        most_obsessive=most_obsessive,
        most_chaotic=most_chaotic,
        most_varied=most_varied,
    )


def _fmt(v: float) -> str:
    return f"{v * DISPLAY_SCALE:.2f}"


def _dominance(winner: float, runner_up: float) -> str:
    """Characterize how decisive the win was."""
    if runner_up <= 0:
        return "solo scorer"
    ratio = winner / runner_up
    if ratio >= 2.5:
        return "dominant"
    if ratio >= 1.5:
        return "clear lead"
    if ratio >= 1.15:
        return "narrow lead"
    return "tight race"


def _mood_line(emoji: str, label: str, award: tuple[str, float, float, float], key: str) -> str:
    u, w, r, avg = award
    tag = _dominance(w, r)
    return (
        f"{emoji} {label}: **{u}** — {key} {_fmt(w)}  "
        f"_(next: {_fmt(r)} · avg: {_fmt(avg)} · {tag})_"
    )


def format_awards(a: Awards) -> str:
    lines = ["**Weekly Music Awards**"]
    if a.most_listened:
        u, n = a.most_listened
        lines.append(f"🎧 Most listened: **{u}** — {n} scrobbles")
    if a.saddest and a.saddest[1] > 0:
        lines.append(_mood_line("😢", "Saddest vibes", a.saddest, "sad"))
    if a.happiest and a.happiest[1] > 0:
        lines.append(_mood_line("😄", "Happiest vibes", a.happiest, "happy"))
    if a.most_energetic and a.most_energetic[1] > 0:
        lines.append(_mood_line("⚡", "Most energetic", a.most_energetic, "energy"))
    if a.most_chill and a.most_chill[1] > 0:
        lines.append(_mood_line("🧘", "Most chill", a.most_chill, "chill"))
    if a.most_obsessive:
        u, track, plays, share = a.most_obsessive
        lines.append(f"🔁 Most obsessive: **{u}** — {plays}× *{track}* ({share:.0%} of their week)")
    if a.most_chaotic:
        lines.append(_mood_line("🎢", "Most chaotic mood", a.most_chaotic, "σ"))
    if a.most_varied:
        u, n = a.most_varied
        lines.append(f"🌈 Widest taste: **{u}** — {n} distinct artists")
    if len(lines) == 1:
        lines.append("_No data this week — did anyone actually listen to anything?_")
    return "\n".join(lines)
