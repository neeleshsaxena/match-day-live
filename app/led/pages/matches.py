from __future__ import annotations

import unicodedata
from datetime import datetime

from PIL import Image, ImageDraw

from app.espn import Match, Snapshot
from app.state import DisplayMode

from ..canvas import (
    ACCENT,
    BLACK,
    DIM,
    GRAY,
    GREEN,
    HEIGHT,
    RED,
    WHITE,
    WIDTH,
    YELLOW,
    big_text_width,
    draw_big,
    draw_big_centered,
    draw_centered,
    draw_hline,
    draw_text,
    filled_rect,
    font_small,
    new_canvas,
    pulse_color,
    scale_color,
    text_width,
)
from ..teams import colors_for


def pick_day_matches(snapshot: Snapshot, mode: DisplayMode, tz) -> list[Match]:
    today_key = datetime.now(tz).strftime("%Y-%m-%d")
    buckets: dict[str, list[Match]] = {}
    for m in snapshot.matches:
        local_key = m.kickoff_utc.astimezone(tz).strftime("%Y-%m-%d")
        buckets.setdefault(local_key, []).append(m)

    if mode == DisplayMode.NEXT:
        future = sorted(d for d in buckets if d > today_key)
        return buckets[future[0]] if future else []

    if today_key in buckets:
        return buckets[today_key]
    future = sorted(d for d in buckets if d > today_key)
    return buckets[future[0]] if future else []


def _short(label: str | None, fallback: str = "—") -> str:
    s = (label or fallback).strip().upper()
    return s[:3] if s else fallback


def _kickoff_countdown(match: Match, tz) -> tuple[str, tuple[int, int, int]]:
    """Return a compact 'in 3h 20m' / 'in 45m' / 'LIVE SOON' string + color."""
    from datetime import timezone as _tz
    now = datetime.now(_tz.utc)
    delta = match.kickoff_utc - now
    secs = int(delta.total_seconds())
    if secs <= 0:
        return ("kickoff", YELLOW)
    if secs < 60:
        return ("starting", YELLOW)
    if secs < 60 * 60:
        return (f"in {secs // 60}m", YELLOW)
    if secs < 24 * 60 * 60:
        hours = secs // 3600
        mins = (secs % 3600) // 60
        if mins == 0:
            return (f"in {hours}h", GRAY)
        return (f"in {hours}h {mins}m", GRAY)
    days = secs // (24 * 60 * 60)
    return (f"in {days}d", DIM)


_HALFTIME = "STATUS_HALFTIME"
_GOAL_PULSE_COLOR = (255, 220, 80)  # warm gold
_MAX_SCORER_LINE_CHARS = 10


def _ascii_upper(s: str) -> str:
    """Strip diacritics and uppercase. 'Mbappé' -> 'MBAPPE'."""
    norm = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in norm if not unicodedata.combining(c))
    return stripped.upper()


def _format_scorer_line(goal) -> str:
    """Compact 'MIN PLAYER' fit for a 60-px LED row at scale 1 of the 5x7 font."""
    minute = (goal.minute or "").replace("'", "").strip()[:5]
    raw = goal.player or ""
    # "K. Mbappé" -> "Mbappé"; "Erling Haaland" -> "Haaland"
    surname = raw.split(".")[-1].strip() if "." in raw else raw.split(" ")[-1].strip()
    name = _ascii_upper(surname)
    max_name = max(3, _MAX_SCORER_LINE_CHARS - len(minute) - 1)
    name = name[:max_name]
    return f"{minute} {name}".strip()


def render(
    match: Match,
    tz,
    page_idx: int = 0,
    page_count: int = 1,
    tick: float = 0.0,
    goal_flash_remaining: float = 0.0,
) -> Image.Image:
    img = new_canvas()
    draw = ImageDraw.Draw(img)
    font = font_small()

    home = _short(match.home.short or match.home.name)
    away = _short(match.away.short or match.away.name)
    home_primary, home_secondary = colors_for(home)
    away_primary, away_secondary = colors_for(away)

    # FULL-HEIGHT side bars: home on left edge, away on right edge.
    # 2 px wide, top reserved (rows 0-3) for a brighter "cap" so it reads as
    # a flag-style ribbon. Content lives between x=4 and x=59.
    bar_w = 2
    filled_rect(draw, 0, 0, bar_w - 1, HEIGHT - 1, scale_color(home_primary, 0.75))
    filled_rect(draw, 0, 0, bar_w - 1, 3, home_primary)
    filled_rect(draw, WIDTH - bar_w, 0, WIDTH - 1, HEIGHT - 1, scale_color(away_primary, 0.75))
    filled_rect(draw, WIDTH - bar_w, 0, WIDTH - 1, 3, away_primary)

    # Row 3–10: team labels — home on left, away on right (content area: x in 4..59)
    content_left = bar_w + 2
    content_right = WIDTH - bar_w - 2
    draw_text(draw, (content_left, 3), home, fill=WHITE, font=font)
    away_w = text_width(draw, away, font)
    draw_text(draw, (content_right - away_w, 3), away, fill=WHITE, font=font)

    # Row 12: divider (inset to respect side bars)
    draw_hline(draw, 12, fill=DIM, x0=content_left, x1=content_right + 1)

    # Rows 14–33: BIG centered score or kickoff time
    is_scheduled = not (match.is_live or match.is_final)
    is_halftime = match.status_raw == _HALFTIME
    if is_scheduled:
        kickoff = match.kickoff_utc.astimezone(tz)
        time_str = kickoff.strftime("%H:%M")
        draw_big_centered(draw, 18, time_str, fill=YELLOW, scale=2)
    else:
        home_s = (match.home.score or "0")[:2]
        away_s = (match.away.score or "0")[:2]
        score_str = f"{home_s}-{away_s}"
        if goal_flash_remaining > 0:
            # Pulse between gold and white during a goal flash, decaying as the
            # remaining time gets shorter.
            decay = min(1.0, goal_flash_remaining / 3.0)
            color = pulse_color(_GOAL_PULSE_COLOR, tick, period=0.4, min_factor=0.7, max_factor=1.0)
            # Subtle gold ring above + below the score during the flash
            ring_alpha = decay
            ring = scale_color(_GOAL_PULSE_COLOR, 0.5 + 0.5 * ring_alpha)
            filled_rect(draw, content_left, 14, content_right, 14, ring)
            filled_rect(draw, content_left, 34, content_right, 34, ring)
        elif is_halftime:
            color = YELLOW
        elif match.is_live:
            color = WHITE
        else:
            color = GRAY
        draw_big_centered(draw, 18, score_str, fill=color, scale=2)

    # Row 36: subtle dim divider before status row (inset)
    draw_hline(draw, 36, fill=DIM, x0=content_left + 2, x1=content_right - 1)

    # Rows 38–44: latest goal scorer (if any). Left-aligned for home goals,
    # right-aligned for away goals — mirrors team label placement at top.
    last_goal = match.latest_goal if not is_scheduled else None
    if last_goal:
        line = _format_scorer_line(last_goal)
        line_y = 38
        text_w = big_text_width(line, scale=1)
        if last_goal.side == "home":
            line_x = content_left
        else:
            line_x = content_right - text_w + 1
        draw_big(draw, (line_x, line_y), line, fill=WHITE, scale=1)

    # Rows 44–55: status zone (constrained to content area)
    status_x = content_left
    if is_halftime:
        # HT badge — yellow, slow pulse
        ht_pulse = pulse_color(YELLOW, tick, period=1.8, min_factor=0.5, max_factor=1.0)
        draw.ellipse([status_x, 47, status_x + 4, 51], fill=ht_pulse)
        draw_text(draw, (status_x + 9, 46), "HT", fill=YELLOW, font=font)
        ht_label = (match.short_detail or "halftime").strip()[:7]
        if ht_label.upper() not in {"HT", "HALFTIME", "HALF"}:
            draw_text(draw, (status_x + 22, 46), ht_label, fill=GRAY, font=font)
    elif match.is_live:
        dot_color = pulse_color(RED, tick, period=1.0, min_factor=0.35, max_factor=1.0)
        draw.ellipse([status_x, 47, status_x + 4, 51], fill=dot_color)
        ring = pulse_color((255, 80, 80), tick, period=1.0, min_factor=0.0, max_factor=0.3)
        draw.ellipse([status_x - 1, 46, status_x + 5, 52], outline=ring)
        status_txt = (match.short_detail or match.status_label or "")[:9]
        draw_text(draw, (status_x + 9, 46), status_txt, fill=WHITE, font=font)
    elif match.is_final:
        ft = "FT"
        ft_w = text_width(draw, ft, font)
        filled_rect(draw, status_x, 46, status_x + ft_w + 4, 56, DIM)
        draw_text(draw, (status_x + 2, 47), ft, fill=GRAY, font=font)
        tail = (match.short_detail or "").strip()
        if tail and tail.upper() not in {"FT", "FULL", "FULL TIME", "FINAL"}:
            draw_text(draw, (status_x + ft_w + 7, 47), tail[:8], fill=GRAY, font=font)
    else:
        # Scheduled — show countdown to kickoff (renders to bottom-status row)
        countdown_text, countdown_color = _kickoff_countdown(match, tz)
        draw_centered(draw, 46, countdown_text, fill=countdown_color, font=font)

    # Row 60–62: page dots, only if more than one match (within content area)
    if page_count > 1:
        dot_y = 60
        gap = 5
        total_w = page_count * gap - 2
        start_x = (WIDTH - total_w) // 2
        for i in range(page_count):
            x = start_x + i * gap
            if i == page_idx:
                draw.ellipse([x, dot_y, x + 2, dot_y + 2], fill=ACCENT)
            else:
                draw.ellipse([x, dot_y, x + 2, dot_y + 2], fill=(70, 85, 105))

    return img


def render_empty(reason: str = "No matches") -> Image.Image:
    img = new_canvas()
    draw = ImageDraw.Draw(img)
    draw_big_centered(draw, 12, "WC", fill=ACCENT, scale=2)
    draw_big_centered(draw, 30, "26", fill=ACCENT, scale=2)
    draw_centered(draw, 50, reason[:11], fill=GRAY)
    return img


def render_day_header(label: str) -> Image.Image:
    img = new_canvas()
    draw = ImageDraw.Draw(img)
    draw_centered(draw, 12, "NEXT", fill=YELLOW)
    draw_centered(draw, 26, label[:11], fill=WHITE)
    return img
