from __future__ import annotations

import asyncio
import os
import signal
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image

from app.espn import ESPNClient
from app.standings import StandingsClient
from app.state import DisplayMode, DisplayState

from .matrix import get_sink
from .pages import matches as matches_page
from .pages import standings as standings_page

LOCAL_TZ = datetime.now().astimezone().tzinfo or ZoneInfo("UTC")
FRAME_INTERVAL = float(os.environ.get("LED_FRAME_INTERVAL", "0.2"))
PAGE_HOLD_SECONDS = float(os.environ.get("LED_PAGE_HOLD", "5.0"))
TRANSITION_SECONDS = float(os.environ.get("LED_TRANSITION", "0.5"))
GOAL_FLASH_SECONDS = float(os.environ.get("LED_GOAL_FLASH", "3.0"))


class LedRunner:
    def __init__(self) -> None:
        self.espn = ESPNClient()
        self.standings = StandingsClient()
        self.state = DisplayState()
        self.sink = get_sink()
        self._page_idx = 0
        self._last_rotate = 0.0
        self._last_mode: DisplayMode | None = None
        # Transition state: snapshot of the previous frame + start time.
        self._last_img: Image.Image | None = None
        self._transition_from: Image.Image | None = None
        self._transition_start: float = 0.0
        # Goal-pulse tracking: per-match score cache + flash deadlines.
        self._score_cache: dict[str, tuple[str, str]] = {}
        self._goal_flash_until: dict[str, float] = {}

    async def close(self) -> None:
        await self.espn.close()
        await self.standings.close()

    def _start_transition(self) -> None:
        """Snapshot the most recently displayed frame to crossfade from."""
        if self._last_img is not None and TRANSITION_SECONDS > 0:
            self._transition_from = self._last_img.copy()
            self._transition_start = time.monotonic()

    def _apply_transition(self, fresh: Image.Image) -> Image.Image:
        if self._transition_from is None:
            return fresh
        elapsed = time.monotonic() - self._transition_start
        if elapsed >= TRANSITION_SECONDS:
            self._transition_from = None
            return fresh
        alpha = max(0.0, min(1.0, elapsed / TRANSITION_SECONDS))
        return Image.blend(self._transition_from, fresh, alpha)

    def _maybe_rotate(self, page_count: int) -> None:
        now = time.monotonic()
        if page_count <= 1:
            self._page_idx = 0
            return
        if now - self._last_rotate >= PAGE_HOLD_SECONDS:
            prev_idx = self._page_idx
            self._page_idx = (self._page_idx + 1) % page_count
            self._last_rotate = now
            if prev_idx != self._page_idx:
                self._start_transition()

    def _reset_rotation(self) -> None:
        self._page_idx = 0
        self._last_rotate = time.monotonic()

    def _update_goal_flashes(self, day_matches, tick: float) -> None:
        """Compare each match's current score with the previous frame's snapshot.
        First sighting of a match seeds the cache without flashing. A subsequent
        score change on a live match schedules a flash deadline."""
        for m in day_matches:
            cur = (m.home.score or "0", m.away.score or "0")
            prev = self._score_cache.get(m.id)
            self._score_cache[m.id] = cur
            if prev is not None and prev != cur and m.is_live:
                self._goal_flash_until[m.id] = tick + GOAL_FLASH_SECONDS

    async def _frame_for_matches(self, mode: DisplayMode, tick: float):
        snapshot = await self.espn.get()
        day_matches = matches_page.pick_day_matches(snapshot, mode, LOCAL_TZ)
        if not day_matches:
            return matches_page.render_empty("no fixtures")
        self._update_goal_flashes(day_matches, tick)
        self._maybe_rotate(len(day_matches))
        idx = self._page_idx % len(day_matches)
        current = day_matches[idx]
        flash_remaining = max(0.0, self._goal_flash_until.get(current.id, 0.0) - tick)
        return matches_page.render(
            current,
            LOCAL_TZ,
            idx,
            len(day_matches),
            tick=tick,
            goal_flash_remaining=flash_remaining,
        )

    async def _frame_for_standings(self, tick: float):
        snapshot = await self.standings.get()
        groups = snapshot.groups
        if not groups:
            return standings_page.render_empty()
        self._maybe_rotate(len(groups))
        idx = self._page_idx % len(groups)
        return standings_page.render(groups[idx], idx, len(groups), tick=tick)

    async def run(self) -> None:
        print(
            f"[led] sink={self.sink.__class__.__name__}  tz={LOCAL_TZ}  "
            f"frame={FRAME_INTERVAL}s  hold={PAGE_HOLD_SECONDS}s  fade={TRANSITION_SECONDS}s"
        )
        while True:
            try:
                mode = self.state.mode
                if mode != self._last_mode:
                    print(f"[led] mode -> {mode.value}")
                    self._start_transition()
                    self._reset_rotation()
                    self._last_mode = mode

                tick = time.monotonic()
                if mode == DisplayMode.STANDINGS:
                    fresh = await self._frame_for_standings(tick)
                else:
                    fresh = await self._frame_for_matches(mode, tick)

                out = self._apply_transition(fresh)
                self.sink.display(out)
                self._last_img = fresh
            except Exception as e:
                print(f"[led] frame error: {type(e).__name__}: {e}")

            await asyncio.sleep(FRAME_INTERVAL)


async def main() -> None:
    runner = LedRunner()

    stop = asyncio.Event()

    def _signal(*_):
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal)
        except NotImplementedError:
            pass

    task = asyncio.create_task(runner.run())
    await stop.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await runner.close()
    print("[led] stopped")


if __name__ == "__main__":
    asyncio.run(main())
