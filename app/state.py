from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from threading import Lock

STATE_FILE = Path(__file__).resolve().parent.parent / ".state.json"


class DisplayMode(str, Enum):
    TODAY = "today"
    NEXT = "next"
    STANDINGS = "standings"


# Legacy values from earlier iterations of the app.
_LEGACY_ALIASES = {"matches": DisplayMode.TODAY}


class DisplayState:
    """Persistent display mode shared across processes via .state.json.

    Reads pick up out-of-process writes (e.g. web app sets mode -> LED runner
    sees it) by checking the file's mtime each access.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._mode: DisplayMode = DisplayMode.TODAY
        self._mtime: float = 0.0
        self._load()

    def _load(self) -> None:
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text())
            raw = data.get("mode", DisplayMode.TODAY.value)
            self._mode = _LEGACY_ALIASES.get(raw) or DisplayMode(raw)
            self._mtime = STATE_FILE.stat().st_mtime
        except Exception:
            pass

    def _refresh_if_changed(self) -> None:
        try:
            mtime = STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0.0
        except OSError:
            return
        if mtime != self._mtime:
            self._load()

    def _save(self) -> None:
        STATE_FILE.write_text(json.dumps({"mode": self._mode.value}))
        try:
            self._mtime = STATE_FILE.stat().st_mtime
        except OSError:
            pass

    @property
    def mode(self) -> DisplayMode:
        with self._lock:
            self._refresh_if_changed()
            return self._mode

    def set_mode(self, mode: DisplayMode) -> DisplayMode:
        with self._lock:
            self._mode = mode
            self._save()
            return self._mode
