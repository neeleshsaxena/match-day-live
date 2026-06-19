from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary"

LIVE_STATUSES = {"STATUS_IN_PROGRESS", "STATUS_HALFTIME", "STATUS_FIRST_HALF", "STATUS_SECOND_HALF"}
FINAL_STATUSES = {"STATUS_FULL_TIME", "STATUS_FINAL"}

# ESPN ships short channel labels; expand a few for readability.
BROADCAST_LABELS = {
    "Tele": "Telemundo",
    "Uni": "Univision",
    "UniMas": "UniMás",
}


@dataclass
class Goal:
    minute: str          # "23'", "45+2'", "90+5'" — ESPN's displayValue
    player: str          # short name e.g. "K. Mbappé", fallback to displayName
    is_penalty: bool = False
    is_own_goal: bool = False
    side: str = ""       # "home" or "away" — set at parse time

    @property
    def minute_sort_key(self) -> int:
        """Return a sortable integer from the minute string for ordering."""
        m = (self.minute or "").replace("'", "").strip()
        if not m:
            return 0
        if "+" in m:
            base, extra = m.split("+", 1)
            try:
                return int(base.strip()) * 100 + int(extra.strip())
            except ValueError:
                return 0
        try:
            return int(m) * 100
        except ValueError:
            return 0


@dataclass
class Team:
    name: str
    short: str
    logo: str | None
    score: str
    is_home: bool
    team_id: str = ""
    goals: list[Goal] = field(default_factory=list)


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

    @property
    def latest_goal(self):
        """Most recent goal across both teams, by minute. None if scoreless."""
        all_goals = list(self.home.goals) + list(self.away.goals)
        if not all_goals:
            return None
        return max(all_goals, key=lambda g: g.minute_sort_key)


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
                team_id=str(team.get("id", "")),
            )

        date_str = event.get("date") or comp.get("date")
        kickoff = datetime.fromisoformat(date_str.replace("Z", "+00:00")) if date_str else datetime.now(timezone.utc)

        status = _safe(event, "status", "type", default={}) or {}
        notes_raw = _safe(comp, "notes", default=[]) or []
        notes = [n.get("headline") for n in notes_raw if n.get("headline")]

        home = to_team(home_raw, True)
        away = to_team(away_raw, False)

        # Goal events live inside competitions[0].details. Each entry has
        # type.text == "Goal" for scoring plays. Map by team.id back to home/away.
        for d in _safe(comp, "details", default=[]) or []:
            if (_safe(d, "type", "text") or "").lower() != "goal":
                continue
            minute = _safe(d, "clock", "displayValue") or ""
            scorer_team_id = str(_safe(d, "team", "id") or "")
            athletes = _safe(d, "athletesInvolved", default=[]) or []
            player_name = ""
            if athletes:
                a0 = athletes[0]
                player_name = a0.get("shortName") or a0.get("displayName") or ""
            goal = Goal(
                minute=minute,
                player=player_name or "—",
                is_penalty=bool(d.get("penaltyKick")),
                is_own_goal=bool(d.get("ownGoal")),
            )
            if scorer_team_id == home.team_id:
                goal.side = "home"
                home.goals.append(goal)
            elif scorer_team_id == away.team_id:
                goal.side = "away"
                away.goals.append(goal)

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
            home=home,
            away=away,
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
        # Per-match scorer cache keyed by event_id.
        # Value: (fetched_monotonic, is_final_at_fetch, home_goals, away_goals)
        self._scorers_cache: dict[str, tuple[float, bool, list[Goal], list[Goal]]] = {}
        self._client = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "match-day-live/0.1"})

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_event_scorers(
        self,
        event_id: str,
        home_team_id: str,
        away_team_id: str,
        is_final: bool = False,
        force: bool = False,
    ) -> tuple[list[Goal], list[Goal]]:
        """Fetch ESPN summary for one event and parse keyEvents into goals.

        keyEvents is more complete than scoreboard.details (it includes goal
        sub-types like "Goal - Volley", "Goal - Header", "Own Goal", etc.).
        Cached per event id with a short TTL while live (60 s) and a long TTL
        once final (10 min, since the data won't change)."""
        cached = self._scorers_cache.get(event_id)
        if cached and not force:
            ts, was_final, hg, ag = cached
            ttl = 600.0 if was_final else 60.0
            if time.monotonic() - ts < ttl:
                return hg, ag

        url = f"{ESPN_SUMMARY}?event={event_id}"
        try:
            r = await self._client.get(url)
            r.raise_for_status()
            data = r.json()
        except Exception:
            if cached:
                return cached[2], cached[3]
            raise

        home_goals: list[Goal] = []
        away_goals: list[Goal] = []
        for ev in data.get("keyEvents") or []:
            if not ev.get("scoringPlay"):
                continue
            type_text = (_safe(ev, "type", "text") or "").strip()
            type_text_low = type_text.lower()
            # Filter out non-goal scoring plays just in case (e.g. soccer summary keyEvents
            # only marks goals as scoringPlay, but stay defensive).
            if "goal" not in type_text_low and "penalty" not in type_text_low:
                continue
            minute = _safe(ev, "clock", "displayValue") or ""
            scorer_team_id = str(_safe(ev, "team", "id") or "")
            participants = _safe(ev, "participants", default=[]) or []
            player = ""
            if participants:
                a = participants[0].get("athlete") or {}
                player = a.get("shortName") or a.get("displayName") or ""
            short_text = (ev.get("shortText") or "").lower()
            is_penalty = "penalty" in type_text_low or "(penalty)" in short_text
            is_own_goal = "own goal" in type_text_low or "own goal" in short_text
            g = Goal(
                minute=minute,
                player=player or "—",
                is_penalty=is_penalty,
                is_own_goal=is_own_goal,
            )
            if scorer_team_id == home_team_id:
                g.side = "home"
                home_goals.append(g)
            elif scorer_team_id == away_team_id:
                g.side = "away"
                away_goals.append(g)

        self._scorers_cache[event_id] = (time.monotonic(), is_final, home_goals, away_goals)
        return home_goals, away_goals

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
