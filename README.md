# match-day-live

A FIFA World Cup 2026 scoreboard. Runs as both a web app and a 64×64 RGB LED
panel from the same code, sharing display mode through a small JSON state
file.

| Surface | Stack | Where |
|---|---|---|
| Web view | FastAPI + Jinja, port 5050 (Caddy → 80) | Raspberry Pi 3B over WiFi |
| LED panel | PIL → hzeller `rpi-rgb-led-matrix` | HUB75 64×64 panel + Adafruit Bonnet |
| Dev preview | PIL → PNG sink | Mac, served at `/led-preview` |

The web app and LED renderer are **two processes** that share `.state.json`.
Flipping the mode from the web UI (or the auth-protected `/admin`) updates
the file; the LED process notices via mtime and switches view within
~200 ms.

## Three display modes

| Mode | What it shows |
|---|---|
| `today` | Today's matches; auto-falls-back to the next match day if today is empty |
| `next` | Strictly the next scheduled match day (skips today even if it has matches) |
| `standings` | Group standings, rotating A → L every ~5 s |

## Architecture (5-layer)

```
                              ┌────────────► browser
                              │
   ESPN unofficial API ──┐    │
   (no key, free)        │    │
                         ▼    │
   ┌──────────────────────────┴───┐
   │  data clients (espn, standings, cached, schema-tolerant)   │
   └──────────────────────────────┘
                         │
                         ▼
   ┌──────────────────────────────┐
   │  DisplayState ── .state.json (mtime-synced between processes)
   └──────────────┬──────────┬─────┘
                  │          │
       ┌──────────▼──┐   ┌───▼──────────────────┐
       │  Web        │   │  LED runner          │
       │  (FastAPI)  │   │  (asyncio loop)      │
       │             │   │                      │
       │  Jinja HTML │   │  PIL Image           │
       └─────────────┘   └──┬───────────────────┘
                            │
                ┌───────────┼─────────────┐
                ▼                         ▼
            PNG sink                HzellerSink
            (Mac dev)               (Pi prod)
```

The split mirrors the canonical
`mlb-led-scoreboard` / `robbydyer/sports` / `ChuckBuilds/LEDMatrix` pattern,
so the data layer is shared and the display layer is swappable.

## Data source

ESPN's unofficial scoreboard API:
- `site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard`
- `site.api.espn.com/apis/v2/sports/soccer/fifa.world/standings`

No key, no rate-limit auth headers. Polite client behavior:

| Match state | Refresh cadence |
|---|---|
| Live | 30 s |
| Within 1 hour of kickoff | 60 s |
| Otherwise | 300 s |
| Standings | 300 s |

## Run locally (Mac)

Requires Python 3.9+. Pi runs 3.13; ideally match it.

```bash
# Set up venv + deps
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Terminal 1 — web app
./run.sh        # → http://localhost:5050

# Terminal 2 — LED renderer (PNG sink, no hardware needed)
.venv/bin/python -m app.led

# Browser
open http://localhost:5050/                  # public web view + mode buttons
open http://localhost:5050/led-preview       # live 64×64 LED preview
open http://localhost:5050/admin             # admin (HTTP Basic auth)
```

The admin password is auto-generated on first start and written to
`.admin_password` (mode 0600). Override with `ADMIN_PASSWORD=…` env var.

## Run on Pi

Two systemd services:

| Service | Listens on | Purpose |
|---|---|---|
| `match-day-live.service` | `0.0.0.0:5050` | FastAPI |
| `caddy.service` | `0.0.0.0:80` | Reverse proxy for friendly URL (`http://matchday.local`) |
| `match-day-led.service` *(Phase 2)* | n/a | Drives the HUB75 panel |

mDNS aliases (Avahi) give each project on the Pi its own `.local` name
routed by Caddy to the right internal port.

## Project layout

```
app/
├── espn.py              # ESPN scoreboard client (async, cached, schema-tolerant)
├── standings.py         # ESPN group-standings client
├── state.py             # DisplayState — JSON-backed, cross-process mtime sync
├── auth.py              # HTTP Basic auth for /admin (auto-generates password)
├── main.py              # FastAPI routes, public mode buttons, LED preview endpoint
├── templates/
│   ├── index.html       # Match view + mode-switch strip
│   ├── standings.html   # Standings view + mode-switch strip
│   ├── admin.html       # Auth-protected control panel
│   └── _mode_controls.html  # Shared 3-button include
└── led/
    ├── canvas.py        # Drawing helpers, 5×7 pixel font, color manipulation
    ├── matrix.py        # PNGSink (Mac) / HzellerSink (Pi) auto-detect
    ├── teams.py         # Flag accent colors keyed by team abbreviation
    ├── runner.py        # Main async loop: data → state → render → sink
    └── pages/
        ├── matches.py   # 64×64 match card (big score, live dot, countdown)
        └── standings.py # 64×64 group standings (top-2 advance, page dots)
```

## Configuration (env vars)

| Var | Default | What it controls |
|---|---|---|
| `PORT` | `5050` | Web app HTTP port |
| `ADMIN_PASSWORD` | auto-generated | Override admin login |
| `LED_FRAME_INTERVAL` | `0.2` | Seconds between LED frames (5 fps default) |
| `LED_PAGE_HOLD` | `5.0` | Seconds to hold each page before rotating |
| `LED_TRANSITION` | `0.5` | Crossfade duration between pages (`0` to disable) |
| `LED_GOAL_FLASH` | `3.0` | Seconds the score pulses gold after a goal |
| `LED_PREVIEW_PATH` | `/tmp/led-preview.png` | Where the PNG sink writes |
| `LED_PREVIEW_SCALE` | `8` | PNG upscale factor for browser visibility |
| `LED_SINK` | auto | Force `png` to use PNGSink even when `rgbmatrix` is importable |
| `LED_GPIO_SLOWDOWN` | `2` | hzeller GPIO slowdown (Pi 3B sweet spot) |
| `LED_BRIGHTNESS` | `60` | hzeller brightness 0–100 |

## LED design notes

The 64×64 panel is the design constraint. Every choice falls out of "what
reads at 2 m":

- **5×7 pixel font** (custom in `canvas.py`) for the score — small but
  scoreboard-crisp at scale 2.
- **2 px vertical side bars** in flag colors on left/right edges — instant
  home/away identity from any angle.
- **Pulsing red dot + minute mark** for live matches; **yellow HT badge** for
  halftime; **gold goal flash** for 3 s when a score increments.
- **Countdown to kickoff** ("in 3h 20m") for scheduled matches.
- **Group letter big + "GROUP" tiny** for standings header; rank badges
  green / yellow / red for advance / bubble / out.
- **Crossfade** between page rotations and mode changes (Image.blend).

## Prior art

- [hzeller/rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) — the HUB75 driver this project is designed against
- [robbydyer/sports](https://github.com/robbydyer/sports) — multi-page rotation pattern
- [ChuckBuilds/LEDMatrix](https://github.com/ChuckBuilds/LEDMatrix) — Pi + Adafruit Bonnet integration reference

## Hardware

Phase 1 (this repo) runs on Mac for development and on Pi for the web data
layer. Phase 2 adds:

| Part | Source |
|---|---|
| 64×64 HUB75 RGB panel, P3 pitch | Adafruit #4732 |
| RGB Matrix Bonnet for Pi | Adafruit #3211 |
| 5 V 4 A PSU | Adafruit #1466 |

The Pi 3B's built-in WiFi handles ESPN polling comfortably (~1 MB/h).

## License

[MIT](LICENSE) — do whatever you want, no warranty.

ESPN data is fetched from a public, unofficial API. This project is not
affiliated with or endorsed by ESPN or FIFA.
