from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

LED_PREVIEW_PATH = Path(os.environ.get("LED_PREVIEW_PATH", "/tmp/led-preview.png"))

from .auth import admin_required
from .espn import ESPNClient, Match, Snapshot
from .standings import StandingsClient, StandingsGroup, StandingsSnapshot
from .state import DisplayMode, DisplayState

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
LOCAL_TZ = datetime.now().astimezone().tzinfo or ZoneInfo("UTC")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.espn = ESPNClient()
    app.state.standings = StandingsClient()
    app.state.display = DisplayState()
    yield
    await app.state.espn.close()
    await app.state.standings.close()


app = FastAPI(title="match-day-live", lifespan=lifespan)


# ─── matches ──────────────────────────────────────────────────────────────────


def _group_by_local_date(matches: list[Match]) -> dict[str, list[Match]]:
    buckets: dict[str, list[Match]] = {}
    for m in matches:
        local_key = m.kickoff_utc.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")
        buckets.setdefault(local_key, []).append(m)
    return buckets


def _pick_today_or_next(snapshot: Snapshot) -> tuple[str | None, list[Match], str]:
    """Today's matches if any; otherwise the next scheduled day. Default mode."""
    today_local = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    buckets = _group_by_local_date(snapshot.matches)
    if today_local in buckets:
        return today_local, buckets[today_local], "today"
    future_days = sorted(d for d in buckets if d > today_local)
    if future_days:
        d = future_days[0]
        return d, buckets[d], "next"
    return None, [], "none"


def _pick_next_only(snapshot: Snapshot) -> tuple[str | None, list[Match], str]:
    """Strictly the next match day after today (skips today even if it has matches)."""
    today_local = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    buckets = _group_by_local_date(snapshot.matches)
    future_days = sorted(d for d in buckets if d > today_local)
    if future_days:
        d = future_days[0]
        return d, buckets[d], "next"
    return None, [], "none"


def _pick_previous(snapshot: Snapshot) -> tuple[str | None, list[Match], str]:
    """The most recent past match day before today (the previous day's results)."""
    today_local = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    buckets = _group_by_local_date(snapshot.matches)
    past_days = sorted((d for d in buckets if d < today_local), reverse=True)
    if past_days:
        d = past_days[0]
        return d, buckets[d], "previous"
    return None, [], "none"


def _fmt_match(m: Match) -> dict:
    kickoff_local = m.kickoff_utc.astimezone(LOCAL_TZ)
    return {
        "id": m.id,
        "home_name": m.home.name,
        "home_short": m.home.short,
        "home_logo": m.home.logo,
        "home_score": m.home.score,
        "away_name": m.away.name,
        "away_short": m.away.short,
        "away_logo": m.away.logo,
        "away_score": m.away.score,
        "kickoff_local": kickoff_local.strftime("%H:%M"),
        "kickoff_full": kickoff_local.strftime("%a %d %b %Y · %H:%M %Z"),
        "status_raw": m.status_raw,
        "status_label": m.status_label,
        "detail": m.detail,
        "short_detail": m.short_detail,
        "venue": m.venue,
        "venue_city": m.venue_city,
        "venue_country": m.venue_country,
        "venue_location": ", ".join(p for p in (m.venue_city, m.venue_country) if p),
        "is_live": m.is_live,
        "is_final": m.is_final,
        "is_scheduled": not (m.is_live or m.is_final),
        "notes": m.notes,
        "broadcasts": [{"name": b.name, "kind": b.kind} for b in m.broadcasts],
    }


def _fmt_group(g: StandingsGroup) -> dict:
    return {
        "name": g.name,
        "short": g.short,
        "entries": [
            {
                "rank": e.rank,
                "team_name": e.team_name,
                "team_short": e.team_short,
                "team_logo": e.team_logo,
                "played": e.played,
                "wins": e.wins,
                "draws": e.draws,
                "losses": e.losses,
                "gf": e.goals_for,
                "ga": e.goals_against,
                "gd": e.goal_diff,
                "points": e.points,
            }
            for e in g.entries
        ],
    }


# ─── display routes ───────────────────────────────────────────────────────────


@app.get("/")
async def index(request: Request):
    display: DisplayState = request.app.state.display
    if display.mode == DisplayMode.STANDINGS:
        return await _render_standings(request)
    picker = _pick_next_only if display.mode == DisplayMode.NEXT else _pick_today_or_next
    return await _render_matches(
        request,
        picker=picker,
        display_mode_value=display.mode.value,
        forced_next=display.mode == DisplayMode.NEXT,
    )


@app.get("/results")
async def results(request: Request):
    """Previous day's match results — a manual, standalone view."""
    return await _render_matches(
        request,
        picker=_pick_previous,
        display_mode_value="results",
        is_results=True,
    )


async def _render_matches(
    request: Request,
    *,
    picker,
    display_mode_value: str,
    forced_next: bool = False,
    is_results: bool = False,
):
    snapshot: Snapshot = await request.app.state.espn.get()
    day, matches, day_kind = picker(snapshot)
    fetched_local = snapshot.fetched_at.astimezone(LOCAL_TZ)
    day_label = ""
    if day:
        day_dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
        day_label = day_dt.strftime("%A, %d %B %Y")
    any_live = any(m.is_live for m in matches)
    return TEMPLATES.TemplateResponse(
        "index.html",
        {
            "request": request,
            "matches": [_fmt_match(m) for m in matches],
            "day_kind": day_kind,
            "day_label": day_label,
            "fetched_label": fetched_local.strftime("%H:%M:%S"),
            "stale": snapshot.stale,
            "tz_name": str(LOCAL_TZ),
            "any_live": any_live,
            "display_mode": display_mode_value,
            "forced_next": forced_next,
            "is_results": is_results,
            # Past results don't change, so the results view is static (no meta-refresh
            # and no mode-poll); the live/upcoming views keep auto-refreshing.
            "auto_refresh": 0 if is_results else (15 if any_live else 60),
            "poll_state": not is_results,
        },
    )


@app.get("/refresh")
async def refresh(request: Request, to: str = "/"):
    """Force a fresh fetch from ESPN (bypass cache), then return to the view."""
    await request.app.state.espn.get(force=True)
    await request.app.state.standings.get(force=True)
    target = to if to in {"/", "/results"} else "/"
    return RedirectResponse(url=target, status_code=303)


async def _render_standings(request: Request):
    snapshot: StandingsSnapshot = await request.app.state.standings.get()
    fetched_local = snapshot.fetched_at.astimezone(LOCAL_TZ)
    return TEMPLATES.TemplateResponse(
        "standings.html",
        {
            "request": request,
            "groups": [_fmt_group(g) for g in snapshot.groups],
            "fetched_label": fetched_local.strftime("%H:%M:%S"),
            "stale": snapshot.stale,
            "display_mode": "standings",
        },
    )


# ─── JSON APIs ────────────────────────────────────────────────────────────────


@app.get("/api/state")
async def api_state(request: Request):
    return {"mode": request.app.state.display.mode.value}


@app.get("/api/matches")
async def api_matches(request: Request):
    snapshot = await request.app.state.espn.get()
    mode = request.app.state.display.mode
    picker = _pick_next_only if mode == DisplayMode.NEXT else _pick_today_or_next
    day, matches, day_kind = picker(snapshot)
    return JSONResponse(
        {
            "fetched_at": snapshot.fetched_at.isoformat(),
            "stale": snapshot.stale,
            "display_mode": mode.value,
            "day_kind": day_kind,
            "day": day,
            "matches": [_fmt_match(m) for m in matches],
        }
    )


@app.get("/api/standings")
async def api_standings(request: Request):
    snapshot = await request.app.state.standings.get()
    return JSONResponse(
        {
            "fetched_at": snapshot.fetched_at.isoformat(),
            "stale": snapshot.stale,
            "groups": [_fmt_group(g) for g in snapshot.groups],
        }
    )


@app.get("/api/raw")
async def api_raw(request: Request):
    snapshot = await request.app.state.espn.get()
    return JSONResponse(
        {
            "fetched_at": snapshot.fetched_at.isoformat(),
            "source_url": snapshot.source_url,
            "stale": snapshot.stale,
            "total_matches": len(snapshot.matches),
            "matches": [
                {
                    "id": m.id,
                    "kickoff_utc": m.kickoff_utc.isoformat(),
                    "status": m.status_raw,
                    "detail": m.detail,
                    "home": {"name": m.home.name, "score": m.home.score},
                    "away": {"name": m.away.name, "score": m.away.score},
                    "venue": m.venue,
                }
                for m in snapshot.matches
            ],
        }
    )


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ─── LED dev preview ──────────────────────────────────────────────────────────


@app.get("/api/led-preview")
async def api_led_preview():
    """Serve the most recent frame the LED runner wrote to disk."""
    if not LED_PREVIEW_PATH.exists():
        raise HTTPException(status_code=404, detail="no preview yet — is the LED runner running?")
    return FileResponse(LED_PREVIEW_PATH, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/led-preview", response_class=HTMLResponse)
async def led_preview_page():
    """LED panel preview — auto-refreshing image with a glowing bezel."""
    return """<!doctype html>
<html><head><meta charset="utf-8"><title>LED preview · match-day-live</title>
<style>
:root {
  --bg: #07090d;
  --bg2: #0c1218;
  --panel: #131a23;
  --border: #243140;
  --text: #e8eef5;
  --muted: #8a9aae;
  --accent: #ffb347;
  --live: #2ee07a;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: radial-gradient(ellipse at top, var(--bg2), var(--bg));
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  gap: 22px;
  padding: 40px 20px;
}
header {
  display: flex; align-items: center; gap: 12px;
  font-size: 13px; letter-spacing: 0.4px;
}
header .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--live); box-shadow: 0 0 8px var(--live); }
header strong { font-weight: 600; }
header .sub { color: var(--muted); }

.stage {
  position: relative;
  padding: 22px;
  border-radius: 18px;
  background: linear-gradient(135deg, #1a232e 0%, #0e1520 100%);
  border: 1px solid var(--border);
  box-shadow:
    0 0 0 1px rgba(255,179,71,0.08),
    0 30px 60px -20px rgba(0,0,0,0.6),
    inset 0 1px 0 rgba(255,255,255,0.03);
}
.stage::before {
  content: "";
  position: absolute; inset: 6px;
  border-radius: 12px;
  pointer-events: none;
  box-shadow: inset 0 0 24px rgba(0,0,0,0.6);
}
img.led {
  display: block;
  image-rendering: pixelated;
  image-rendering: crisp-edges;
  border-radius: 6px;
  width: min(80vw, 520px);
  height: min(80vw, 520px);
  background: #000;
}

.meta {
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  font-size: 12px; color: var(--muted);
}
.meta .mode {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 999px;
  background: var(--panel); border: 1px solid var(--border);
  color: var(--text); font-weight: 500;
}
.meta .mode .pill-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent); box-shadow: 0 0 6px var(--accent);
}
.meta .links { display: flex; gap: 14px; }
.meta .links a { color: var(--muted); text-decoration: none; }
.meta .links a:hover { color: var(--accent); }

.fps {
  font-variant-numeric: tabular-nums;
  font-size: 11px; color: var(--muted);
}
</style></head>
<body>
  <header>
    <span class="dot"></span>
    <strong>match-day-live</strong>
    <span class="sub">· LED panel preview · 64 × 64</span>
  </header>

  <div class="stage">
    <img id="led" class="led" src="/api/led-preview?t=0" alt="LED panel preview" />
  </div>

  <div class="meta">
    <span class="mode"><span class="pill-dot"></span> mode: <span id="mode">…</span></span>
    <span class="fps" id="fps">— fps</span>
    <span class="links">
      <a href="/" target="_blank">web view ↗</a>
      <a href="/admin" target="_blank">admin ↗</a>
      <a href="/api/state" target="_blank">/api/state</a>
    </span>
  </div>

<script>
const el = document.getElementById('led');
const modeEl = document.getElementById('mode');
const fpsEl = document.getElementById('fps');

let frames = 0, lastReport = performance.now();
setInterval(() => {
  el.src = '/api/led-preview?t=' + Date.now();
  frames++;
  const now = performance.now();
  if (now - lastReport > 1000) {
    const fps = (frames * 1000 / (now - lastReport)).toFixed(1);
    fpsEl.textContent = fps + ' fps preview';
    frames = 0;
    lastReport = now;
  }
}, 250);

setInterval(async () => {
  try {
    const r = await fetch('/api/state', { cache: 'no-store' });
    const d = await r.json();
    if (d.mode) modeEl.textContent = d.mode;
  } catch (_) {}
}, 1500);
</script>
</body></html>"""


# ─── admin ────────────────────────────────────────────────────────────────────


@app.get("/admin")
async def admin(request: Request, _: str = Depends(admin_required)):
    display: DisplayState = request.app.state.display
    return TEMPLATES.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "current_mode": display.mode.value,
        },
    )


def _apply_mode(request: Request, mode_str: str, redirect_to: str) -> RedirectResponse:
    try:
        new_mode = DisplayMode(mode_str)
    except ValueError:
        return RedirectResponse(url=redirect_to, status_code=303)
    request.app.state.display.set_mode(new_mode)
    return RedirectResponse(url=redirect_to, status_code=303)


@app.post("/admin/mode")
async def admin_set_mode(
    request: Request,
    mode: str = Form(...),
    _: str = Depends(admin_required),
):
    return _apply_mode(request, mode, "/admin")


@app.post("/mode")
async def public_set_mode(
    request: Request,
    mode: str = Form(...),
):
    """Public mode switcher — no auth. LAN users can flip Today/Next/Standings.
    See tasks/webapp-public-mode-controls.md for the threat model decision."""
    return _apply_mode(request, mode, "/")
