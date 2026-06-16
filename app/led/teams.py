"""Flag-derived accent colors per team for FIFA WC 2026 qualifiers.

Each entry is (primary, secondary). Primary = dominant flag color; secondary
= a complementary accent. Used to paint thin stripes under team labels so
each match card feels distinct at a glance.
"""
from __future__ import annotations

# Color presets for repeated flag patterns
_WHITE = (240, 240, 240)
_RED = (220, 32, 32)
_BLUE = (32, 80, 220)
_GREEN = (32, 180, 80)
_YELLOW = (255, 200, 32)
_BLACK = (16, 16, 16)
_ORANGE = (255, 120, 0)

TEAM_COLORS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    # CONCACAF
    "USA": (_RED, _BLUE),
    "MEX": (_GREEN, _RED),
    "CAN": (_RED, _WHITE),
    "CRC": (_RED, _BLUE),
    "PAN": (_RED, _BLUE),
    "JAM": (_GREEN, _YELLOW),
    "HON": (_BLUE, _WHITE),
    "HAI": (_RED, _BLUE),
    "SLV": (_BLUE, _WHITE),
    "CUR": (_BLUE, _YELLOW),
    # CONMEBOL
    "ARG": (_BLUE, _WHITE),
    "BRA": (_YELLOW, _GREEN),
    "URU": (_BLUE, _YELLOW),
    "COL": (_YELLOW, _BLUE),
    "CHI": (_RED, _BLUE),
    "ECU": (_YELLOW, _BLUE),
    "PAR": (_RED, _BLUE),
    "PER": (_RED, _WHITE),
    "VEN": (_YELLOW, _RED),
    "BOL": (_GREEN, _YELLOW),
    # UEFA
    "FRA": (_BLUE, _RED),
    "ESP": (_RED, _YELLOW),
    "GER": (_BLACK, _YELLOW),
    "ITA": (_GREEN, _RED),
    "ENG": (_WHITE, _RED),
    "POR": (_RED, _GREEN),
    "NED": (_ORANGE, _BLUE),
    "BEL": (_RED, _YELLOW),
    "POL": (_RED, _WHITE),
    "DEN": (_RED, _WHITE),
    "SWE": (_BLUE, _YELLOW),
    "NOR": (_RED, _BLUE),
    "CRO": (_RED, _WHITE),
    "SUI": (_RED, _WHITE),
    "AUT": (_RED, _WHITE),
    "CZE": (_BLUE, _RED),
    "SRB": (_RED, _BLUE),
    "HUN": (_RED, _GREEN),
    "SCO": (_BLUE, _WHITE),
    "WAL": (_RED, _GREEN),
    "IRL": (_GREEN, _ORANGE),
    "BIH": (_BLUE, _YELLOW),
    "TUR": (_RED, _WHITE),
    "GRE": (_BLUE, _WHITE),
    "UKR": (_BLUE, _YELLOW),
    # AFC
    "JPN": (_RED, _WHITE),
    "KOR": (_BLUE, _RED),
    "AUS": (_BLUE, _YELLOW),
    "IRN": (_GREEN, _RED),
    "KSA": (_GREEN, _WHITE),
    "QAT": (_RED, _WHITE),
    "UAE": (_RED, _GREEN),
    "IRQ": (_RED, _BLACK),
    "UZB": (_BLUE, _GREEN),
    # CAF
    "MAR": (_RED, _GREEN),
    "EGY": (_RED, _WHITE),
    "ALG": (_GREEN, _RED),
    "TUN": (_RED, _WHITE),
    "SEN": (_GREEN, _YELLOW),
    "CMR": (_GREEN, _YELLOW),
    "GHA": (_RED, _YELLOW),
    "NGA": (_GREEN, _WHITE),
    "CIV": (_ORANGE, _GREEN),
    "MLI": (_GREEN, _YELLOW),
    "RSA": (_GREEN, _YELLOW),
    # CONCACAF/Caribbean qualifiers seen in CONCACAF tournaments
    "CUW": (_BLUE, _YELLOW),
    "CPV": (_BLUE, _RED),
    "SUR": (_GREEN, _WHITE),
    "TRI": (_RED, _BLACK),
    "GUA": (_BLUE, _WHITE),
    "NCA": (_BLUE, _WHITE),
    "ATG": (_RED, _BLUE),
    "GRN": (_RED, _GREEN),
    "BAR": (_BLUE, _YELLOW),
    "BLZ": (_BLUE, _RED),
    "DOM": (_BLUE, _RED),
    "DMA": (_GREEN, _YELLOW),
    "VIN": (_BLUE, _YELLOW),
    "GUY": (_GREEN, _YELLOW),
    "PUR": (_RED, _BLUE),
    # OFC
    "NZL": (_BLUE, _WHITE),
}

# Fallback for unknown teams: a warm amber that's distinctive but neutral —
# strong enough to "pop" on a black LED background so an unknown team isn't a
# dim gray smear.
_FALLBACK = ((220, 140, 40), (140, 90, 30))

# A color is "too dark to read on a black LED panel" if its summed-channel
# brightness is below this threshold. Black flags (GER, BEL) fall back to
# their secondary color (yellow / red) which actually shows up.
_VISIBILITY_MIN = 90

# Floor for side-bar primary color brightness. If a flag's primary still
# falls below this after the swap, we scale it up so it reads on the panel.
_PRIMARY_MIN_BRIGHTNESS = 240


def _brightness(c: tuple[int, int, int]) -> int:
    return c[0] + c[1] + c[2]


def _boost_to_min(c: tuple[int, int, int], min_sum: int) -> tuple[int, int, int]:
    """Scale a color up so its summed channels reach at least `min_sum`."""
    b = _brightness(c)
    if b >= min_sum or b == 0:
        return c
    factor = min_sum / b
    return (
        min(255, int(c[0] * factor)),
        min(255, int(c[1] * factor)),
        min(255, int(c[2] * factor)),
    )


def colors_for(team_short: str | None) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    if not team_short:
        primary, secondary = _FALLBACK
    else:
        primary, secondary = TEAM_COLORS.get(team_short.upper(), _FALLBACK)
        # Swap if primary is too dark to read against black.
        if _brightness(primary) < _VISIBILITY_MIN and _brightness(secondary) >= _VISIBILITY_MIN:
            primary, secondary = secondary, primary
    # Ensure the visible-on-LED primary reaches a minimum brightness so dim
    # flag colors (deep navy etc.) still show up clearly.
    primary = _boost_to_min(primary, _PRIMARY_MIN_BRIGHTNESS)
    return primary, secondary
