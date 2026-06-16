from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"

LIVE_STATUSES = {"STATUS_IN_PROGRESS", "STATUS_HALFTIME", "STATUS_FIRST_HALF", "STATUS_SECOND_HALF"}
FINAL_STATUSES = {"STATUS_FULL_TIME", "STATUS_FINAL"}

# ESPN ships short channel labels; expand a few for readability.
BROADCAST_LABELS = {
    "Tele": "Telemundo",
    "Uni": "Univision",
    "UniMas": "UniMás",
}


@dataclass
class Team:
    name: str
    short: str
    logo: str | None
    score: str
    is_home: bool


@dataclass
class Broadcast:
    name: str
    kind: str  # "TV" or "STREAMING"


@dataclass
class Match:
    id: str
    kickoff_utc: datetime
    status_raw: str
    status_label: str
    detail: str
    short_detail: str
    home: Team
    away: Team
    venue: str | None
    venue_city: str | None = None
    venue_country: str | None = None
    notes: list[str] = field(default_factory=list)
    broadcasts: list[Broadcast] = field(default_factory=list)

    @property
    def is_live(self) -> bool:
        return self.status_raw in LIVE_STATUSES or self.status_raw.startswith("STATUS_") and "HALF" in self.status_raw

    @property
    def is_final(self) -> bool:
        return self.status_raw in FINAL_STATUSES

    @property
    def kickoff_date_utc(self) -> str:
        return self.kickoff_utc.strftime("%Y-%m-%d")


@dataclass
class Snapshot:
    fetched_at: datetime
    matches: list[Match]
    source_url: str
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


def _parse_event(event: dict) -> Match | None:
    try:
        comp = _safe(event, "competitions", 0, default={})
        competitors = _safe(comp, "competitors", default=[]) or []
        home_raw = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0] if competitors else {})
        away_raw = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})

        def to_team(raw: dict, is_home: bool) -> Team:
            team = raw.get("team", {}) or {}
            return Team(
                name=team.get("displayName") or team.get("name") or "—",
                short=team.get("abbreviation") or team.get("shortDisplayName") or "—",
                logo=team.get("logo"),
                score=str(raw.get("score", "") or ""),
                is_home=is_home,
            )

        date_str = event.get("date") or comp.get("date")
        kickoff = datetime.fromisoformat(date_str.replace("Z", "+00:00")) if date_str else datetime.now(timezone.utc)

        status = _safe(event, "status", "type", default={}) or {}
        notes_raw = _safe(comp, "notes", default=[]) or []
        notes = [n.get("headline") for n in notes_raw if n.get("headline")]

        broadcasts: list[Broadcast] = []
        seen: set[tuple[str, str]] = set()
        for g in _safe(comp, "geoBroadcasts", default=[]) or []:
            if (g.get("region") or "").lower() != "us":
                continue
            name = _safe(g, "media", "shortName") or _safe(g, "media", "name")
            kind = _safe(g, "type", "shortName") or "TV"
            if not name or (name, kind) in seen:
                continue
            seen.add((name, kind))
            broadcasts.append(Broadcast(name=BROADCAST_LABELS.get(name, name), kind=kind))
        broadcasts.sort(key=lambda b: (b.kind != "TV", b.name))

        return Match(
            id=str(event.get("id", "")),
            kickoff_utc=kickoff,
            status_raw=status.get("name", "STATUS_SCHEDULED"),
            status_label=status.get("description", "Scheduled"),
            detail=status.get("detail", ""),
            short_detail=status.get("shortDetail", ""),
            home=to_team(home_raw, True),
            away=to_team(away_raw, False),
            venue=_safe(comp, "venue", "fullName"),
            venue_city=_safe(comp, "venue", "address", "city"),
            venue_country=_safe(comp, "venue", "address", "country"),
            notes=notes,
            broadcasts=broadcasts,
        )
    except Exception:
        return None


class ESPNClient:
    def __init__(self, timeout: float = 8.0):
        self._timeout = timeout
        self._cache: Snapshot | None = None
        self._cache_ts: float = 0.0
        self._client = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "match-day-live/0.1"})

    async def close(self) -> None:
        await self._client.aclose()

    def _ttl_for(self, snapshot: Snapshot | None) -> float:
        if not snapshot:
            return 30.0
        if any(m.is_live for m in snapshot.matches):
            return 30.0
        now = datetime.now(timezone.utc)
        soonest = min((m.kickoff_utc for m in snapshot.matches if m.kickoff_utc > now), default=None)
        if soonest and (soonest - now) < timedelta(hours=1):
            return 60.0
        return 300.0

    async def get(self, force: bool = False) -> Snapshot:
        now_s = time.monotonic()
        if not force and self._cache and (now_s - self._cache_ts) < self._ttl_for(self._cache):
            return self._cache

        now_utc = datetime.now(timezone.utc)
        # Start a few days back so previous-day results are available (the /results
        # view), while still covering upcoming fixtures.
        start = (now_utc - timedelta(days=3)).strftime("%Y%m%d")
        end = (now_utc + timedelta(days=14)).strftime("%Y%m%d")
        url = f"{ESPN_BASE}?dates={start}-{end}&limit=300"
        try:
            r = await self._client.get(url)
            r.raise_for_status()
            data = r.json()
        except Exception:
            if self._cache:
                self._cache.stale = True
                return self._cache
            raise

        events = data.get("events", []) or []
        matches = [m for m in (_parse_event(e) for e in events) if m]
        matches.sort(key=lambda m: m.kickoff_utc)

        snapshot = Snapshot(fetched_at=datetime.now(timezone.utc), matches=matches, source_url=url)
        self._cache = snapshot
        self._cache_ts = now_s
        return snapshot
