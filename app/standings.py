from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/soccer/fifa.world/standings"


@dataclass
class StandingsEntry:
    rank: int
    team_name: str
    team_short: str
    team_logo: str | None
    played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    goal_diff: int
    points: int


@dataclass
class StandingsGroup:
    name: str
    short: str
    entries: list[StandingsEntry] = field(default_factory=list)


@dataclass
class StandingsSnapshot:
    fetched_at: datetime
    groups: list[StandingsGroup]
    stale: bool = False


def _safe(obj: dict | list | None, *path, default=None):
    cur: Any = obj
    for p in path:
        if cur is None:
            return default
        try:
            cur = cur[p]
        except (KeyError, IndexError, TypeError):
            return default
    return cur if cur is not None else default


# ESPN names vary across leagues. Try several aliases per slot.
_STAT_ALIASES = {
    "played": ("gamesPlayed", "GP"),
    "wins": ("wins", "W"),
    "draws": ("ties", "draws", "D"),
    "losses": ("losses", "L"),
    "goals_for": ("pointsFor", "goalsFor", "GF"),
    "goals_against": ("pointsAgainst", "goalsAgainst", "GA"),
    "goal_diff": ("pointDifferential", "goalDifference", "GD"),
    "points": ("points", "PTS"),
    "rank": ("rank",),
}


def _read_stat(stats: list[dict], aliases: tuple[str, ...]) -> int:
    for s in stats:
        name = s.get("name") or s.get("abbreviation") or ""
        if name in aliases:
            raw = s.get("value")
            if raw is None:
                raw = s.get("displayValue", 0)
            try:
                return int(float(raw))
            except (TypeError, ValueError):
                return 0
    return 0


def _parse_entry(raw: dict, fallback_rank: int) -> StandingsEntry | None:
    try:
        team = raw.get("team", {}) or {}
        stats = raw.get("stats", []) or []
        rank = _read_stat(stats, _STAT_ALIASES["rank"]) or fallback_rank
        return StandingsEntry(
            rank=rank,
            team_name=team.get("displayName") or team.get("name") or "—",
            team_short=team.get("abbreviation") or team.get("shortDisplayName") or "—",
            team_logo=team.get("logos", [{}])[0].get("href") if team.get("logos") else team.get("logo"),
            played=_read_stat(stats, _STAT_ALIASES["played"]),
            wins=_read_stat(stats, _STAT_ALIASES["wins"]),
            draws=_read_stat(stats, _STAT_ALIASES["draws"]),
            losses=_read_stat(stats, _STAT_ALIASES["losses"]),
            goals_for=_read_stat(stats, _STAT_ALIASES["goals_for"]),
            goals_against=_read_stat(stats, _STAT_ALIASES["goals_against"]),
            goal_diff=_read_stat(stats, _STAT_ALIASES["goal_diff"]),
            points=_read_stat(stats, _STAT_ALIASES["points"]),
        )
    except Exception:
        return None


def _parse_group(raw: dict) -> StandingsGroup | None:
    try:
        name = raw.get("name") or raw.get("displayName") or "—"
        short = raw.get("abbreviation") or name.replace("Group ", "").strip() or "?"
        entries_raw = _safe(raw, "standings", "entries", default=[]) or []
        entries: list[StandingsEntry] = []
        for i, e in enumerate(entries_raw, start=1):
            parsed = _parse_entry(e, fallback_rank=i)
            if parsed:
                entries.append(parsed)
        entries.sort(key=lambda x: (x.rank if x.rank else 99, -x.points, -x.goal_diff))
        return StandingsGroup(name=name, short=short, entries=entries)
    except Exception:
        return None


class StandingsClient:
    def __init__(self, timeout: float = 8.0):
        self._cache: StandingsSnapshot | None = None
        self._cache_ts: float = 0.0
        self._ttl: float = 300.0
        self._client = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "match-day-live/0.1"})

    async def close(self) -> None:
        await self._client.aclose()

    async def get(self, force: bool = False) -> StandingsSnapshot:
        now_s = time.monotonic()
        if not force and self._cache and (now_s - self._cache_ts) < self._ttl:
            return self._cache

        try:
            r = await self._client.get(STANDINGS_URL)
            r.raise_for_status()
            data = r.json()
        except Exception:
            if self._cache:
                self._cache.stale = True
                return self._cache
            raise

        groups: list[StandingsGroup] = []
        for child in data.get("children", []) or []:
            g = _parse_group(child)
            if g:
                groups.append(g)
        groups.sort(key=lambda g: g.name)

        snapshot = StandingsSnapshot(fetched_at=datetime.now(timezone.utc), groups=groups)
        self._cache = snapshot
        self._cache_ts = now_s
        return snapshot
