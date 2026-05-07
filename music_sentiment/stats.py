"""Compute the weekly award stats across users and format for Discord."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import mean, pstdev

from .lastfm import Scrobble


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
class MoodAward:
    user: str
    winner: float
    runner_up: float
    group_avg: float


@dataclass
class Awards:
    podium: list[tuple[str, int]] = field(default_factory=list)  # ranked by scrobbles
    total_scrobbles: int = 0
    total_listeners: int = 0
    period: tuple[int, int] | None = None  # (since, until) unix timestamps

    saddest: MoodAward | None = None
    happiest: MoodAward | None = None
    most_energetic: MoodAward | None = None
    most_chill: MoodAward | None = None
    most_chaotic: MoodAward | None = None

    most_obsessive: tuple[str, str, int, float] | None = None  # user, track, plays, share
    most_varied: tuple[str, int] | None = None  # user, unique artists
    group_anthem: tuple[str, int, int] | None = None  # track, distinct_listeners, total_plays


def _dim_leader(weeks: list[UserWeek], dim: str) -> MoodAward | None:
    means: dict[str, float] = {}
    for w in weeks:
        vals = w.dim_values(dim)
        if vals:
            means[w.user] = mean(vals)
    if not means:
        return None
    sorted_vals = sorted(means.values(), reverse=True)
    winner_user = max(means.items(), key=lambda x: x[1])[0]
    return MoodAward(
        user=winner_user,
        winner=sorted_vals[0],
        runner_up=sorted_vals[1] if len(sorted_vals) > 1 else 0.0,
        group_avg=sum(sorted_vals) / len(sorted_vals),
    )


def compute(
    weeks: list[UserWeek], period: tuple[int, int] | None = None
) -> Awards:
    listening = sorted(
        ((w.user, len(w.scrobbles)) for w in weeks),
        key=lambda x: x[1],
        reverse=True,
    )

    mood_stdevs: dict[str, float] = {}
    for w in weeks:
        sads = w.dim_values("sad")
        happies = w.dim_values("happy")
        nets = [h - s for h, s in zip(happies, sads)]
        if len(nets) > 1:
            mood_stdevs[w.user] = pstdev(nets)
    chaotic = None
    if mood_stdevs:
        sorted_vals = sorted(mood_stdevs.values(), reverse=True)
        u = max(mood_stdevs.items(), key=lambda x: x[1])[0]
        chaotic = MoodAward(
            user=u,
            winner=sorted_vals[0],
            runner_up=sorted_vals[1] if len(sorted_vals) > 1 else 0.0,
            group_avg=sum(sorted_vals) / len(sorted_vals),
        )

    obsessive = None
    best_share = 0.0
    for w in weeks:
        if not w.scrobbles:
            continue
        counts = Counter((s.artist, s.track) for s in w.scrobbles)
        (artist, track), plays = counts.most_common(1)[0]
        share = plays / len(w.scrobbles)
        if share > best_share and plays >= 3:
            best_share = share
            obsessive = (w.user, f"{artist} — {track}", plays, share)

    varied = max(
        ((w.user, len({s.artist for s in w.scrobbles})) for w in weeks if w.scrobbles),
        key=lambda x: x[1],
        default=None,
    )

    track_listeners: dict[tuple[str, str], set[str]] = {}
    track_plays: Counter[tuple[str, str]] = Counter()
    for w in weeks:
        seen_in_week: set[tuple[str, str]] = set()
        for s in w.scrobbles:
            if not s.artist or not s.track:
                continue
            key = (s.artist, s.track)
            track_plays[key] += 1
            seen_in_week.add(key)
        for key in seen_in_week:
            track_listeners.setdefault(key, set()).add(w.user)
    anthem = None
    shared = [
        (key, len(users), track_plays[key])
        for key, users in track_listeners.items()
        if len(users) >= 2
    ]
    if shared:
        shared.sort(key=lambda x: (x[1], x[2]), reverse=True)
        (artist, track), n_users, plays = shared[0]
        anthem = (f"{artist} — {track}", n_users, plays)

    return Awards(
        podium=listening,
        total_scrobbles=sum(n for _, n in listening),
        total_listeners=sum(1 for _, n in listening if n > 0),
        period=period,
        saddest=_dim_leader(weeks, "sad"),
        happiest=_dim_leader(weeks, "happy"),
        most_energetic=_dim_leader(weeks, "energy"),
        most_chill=_dim_leader(weeks, "chill"),
        most_chaotic=chaotic,
        most_obsessive=obsessive,
        most_varied=varied,
        group_anthem=anthem,
    )


def _dominance(winner: float, runner_up: float) -> str:
    if runner_up <= 0:
        return "solo scorer"
    ratio = winner / runner_up
    if ratio >= 2.5:
        return "runaway"
    if ratio >= 1.5:
        return "clear lead"
    if ratio >= 1.15:
        return "narrow lead"
    return "photo finish"


def _mood_line(emoji: str, label: str, key: str, a: MoodAward) -> str:
    tag = _dominance(a.winner, a.runner_up)
    return (
        f"{emoji} **{label}** — **{a.user}** · "
        f"{key} {a.winner:.2f} · {tag} · avg {a.group_avg:.2f}"
    )


def _format_period(period: tuple[int, int]) -> str:
    since, until = period
    s = datetime.fromtimestamp(since, tz=timezone.utc).strftime("%b %-d")
    u = datetime.fromtimestamp(until, tz=timezone.utc).strftime("%b %-d")
    return f"{s} – {u}"


_PODIUM_MEDALS = ("🥇", "🥈", "🥉")


def format_awards(a: Awards) -> str:
    if not a.podium or a.total_scrobbles == 0:
        return (
            "## 🎵 Weekly Music Awards\n"
            "The silence is deafening — nobody scrobbled this week."
        )

    lines: list[str] = ["## 🎵 Weekly Music Awards"]
    subtitle_bits = []
    if a.period:
        subtitle_bits.append(_format_period(a.period))
    subtitle_bits.append(f"{a.total_scrobbles:,} scrobbles")
    subtitle_bits.append(
        f"{a.total_listeners} listener" + ("s" if a.total_listeners != 1 else "")
    )
    lines.append(" · ".join(subtitle_bits))

    lines.append("")
    lines.append("### 🏆 Listening Leaderboard")
    for i, (user, n) in enumerate(a.podium):
        marker = _PODIUM_MEDALS[i] if i < len(_PODIUM_MEDALS) else f"`#{i + 1}`"
        suffix = " 💤" if n == 0 else ""
        lines.append(f"{marker} **{user}** — {n:,} scrobbles{suffix}")

    mood_lines: list[str] = []
    if a.happiest and a.happiest.winner > 0:
        mood_lines.append(_mood_line("😄", "Happiest", "happy", a.happiest))
    if a.saddest and a.saddest.winner > 0:
        mood_lines.append(_mood_line("😢", "Saddest", "sad", a.saddest))
    if a.most_energetic and a.most_energetic.winner > 0:
        mood_lines.append(_mood_line("🔥", "Most energetic", "energy", a.most_energetic))
    if a.most_chill and a.most_chill.winner > 0:
        mood_lines.append(_mood_line("🧘", "Most chill", "chill", a.most_chill))
    if a.most_chaotic:
        mood_lines.append(_mood_line("🎢", "Most chaotic mood", "σ", a.most_chaotic))
    if mood_lines:
        lines.append("")
        lines.append("### 🎭 Mood")
        lines.extend(mood_lines)

    extras: list[str] = []
    if a.most_obsessive:
        u, track, plays, share = a.most_obsessive
        extras.append(
            f"🔁 **Most obsessive** — **{u}** spun “{track}” "
            f"{plays}× ({share:.0%} of their week)"
        )
    if a.most_varied:
        u, n = a.most_varied
        extras.append(f"🌈 **Widest taste** — **{u}** explored {n} distinct artists")
    if a.group_anthem:
        track, n_users, plays = a.group_anthem
        extras.append(
            f"🎤 **Group anthem** — “{track}” shared by {n_users} listeners "
            f"({plays} plays)"
        )
    if extras:
        lines.append("")
        lines.append("### 🎯 Honorable Mentions")
        lines.extend(extras)

    return "\n".join(lines)
