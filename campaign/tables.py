"""All lookup tables for the campaign system generator.

Table distance values are stored in light-minutes (LM), the physical unit.
Functions that return or compare distances convert to/from sH using LM_PER_SH
at the boundary, so callers always work in sH.
"""

from __future__ import annotations

from campaign.models import AnomalyType, LM_PER_SH, PlanetType, SpectralClass, WPVisibility


# ---------------------------------------------------------------------------
# 1. System type — spectral class (1d100)
# ---------------------------------------------------------------------------
# Returns (SpectralClass | None, is_anomaly).
# None spectral class + is_anomaly=True → roll on ANOMALY_TABLE next.
# None spectral class + is_anomaly=False → no-planet star (Blue Giant, etc.)

def roll_spectral_class(roll: int) -> tuple[SpectralClass | None, bool]:
    """Map a 1d100 roll to a spectral class or anomaly flag.

    Returns (spectral_class, is_anomaly).
    """
    if roll <= 0:
        roll = 100
    if roll <= 5:
        return SpectralClass.BLUE_GIANT, False
    if roll <= 12:
        return SpectralClass.WHITE, False
    if roll <= 22:
        return SpectralClass.YELLOW_WHITE, False
    if roll <= 46:
        return SpectralClass.YELLOW, False
    if roll <= 66:
        return SpectralClass.ORANGE, False
    if roll <= 85:
        return SpectralClass.RED, False
    if roll <= 95:
        return SpectralClass.RED_DWARF, False
    if roll <= 98:
        return SpectralClass.WHITE_DWARF, False
    return SpectralClass.RED_GIANT, False


# ---------------------------------------------------------------------------
# 2. Anomaly type (1d100)
# ---------------------------------------------------------------------------

def roll_anomaly_type(roll: int) -> AnomalyType:
    if roll <= 0:
        roll = 100
    if roll <= 2:
        return AnomalyType.BLACKHOLE
    if roll <= 12:
        return AnomalyType.MAGNETAR
    if roll <= 30:
        return AnomalyType.QUATERNARY_SYSTEM
    if roll <= 40:
        return AnomalyType.LONG_DISTANCE_COMPANION
    if roll <= 60:
        return AnomalyType.PROTO_DISK
    if roll <= 75:
        return AnomalyType.GRAVITY_WAVE
    if roll <= 97:
        return AnomalyType.PULSAR
    return AnomalyType.ASTEROID_CLUSTER


# ---------------------------------------------------------------------------
# 3. Zone boundaries by spectral class (distances in LM)
# ---------------------------------------------------------------------------
# Each entry: {"rocky": (lo, hi), "gas": (lo, hi), "ice": (lo, hi),
#              "biosphere": (lo, hi) | None, "tidelock": (lo, hi)}

_ZONE_BOUNDS: dict[SpectralClass, dict] = {
    SpectralClass.WHITE: {
        "rocky":     (12,   600),
        "gas":       (612,  3360),
        "ice":       (3372, 4200),
        "biosphere": (240,  480),
        "tidelock":  (12,   60),
    },
    SpectralClass.YELLOW_WHITE: {
        "rocky":     (12,   300),
        "gas":       (312,  1560),
        "ice":       (1572, 3600),
        "biosphere": (120,  216),
        "tidelock":  (12,   48),
    },
    SpectralClass.YELLOW: {
        "rocky":     (12,   192),
        "gas":       (204,  996),
        "ice":       (1008, 3600),
        "biosphere": (72,   144),
        "tidelock":  (12,   36),
    },
    SpectralClass.ORANGE: {
        "rocky":     (12,   108),
        "gas":       (120,  456),
        "ice":       (468,  3000),
        "biosphere": (36,   60),
        "tidelock":  (12,   24),
    },
    SpectralClass.RED: {
        "rocky":     (12,   60),
        "gas":       (72,   216),
        "ice":       (228,  2400),
        "biosphere": (36,   48),
        "tidelock":  (12,   24),
    },
    SpectralClass.RED_DWARF: {
        "rocky":     (12,   36),
        "gas":       (48,   132),
        "ice":       (144,  2400),
        "biosphere": None,
        "tidelock":  (12,   12),
    },
}


def get_zone_bounds(spectral_class: SpectralClass) -> dict | None:
    """Return zone boundary dict for a spectral class with distances in sH.

    Converts the stored LM values to sH using LM_PER_SH so callers always
    work in the same unit as Planet.distance_sh.
    """
    raw = _ZONE_BOUNDS.get(spectral_class)
    if raw is None:
        return None
    result: dict = {}
    for key, val in raw.items():
        if val is None:
            result[key] = None
        else:
            lo_lm, hi_lm = val
            result[key] = (max(1, round(lo_lm / LM_PER_SH)),
                           round(hi_lm / LM_PER_SH))
    return result


def classify_orbit(spectral_class: SpectralClass, distance_sh: int) -> str:
    """Return the zone sub-type key for an orbit.

    Returns one of: "hot", "lwz", "cold_rocky", "gas", "ice", "beyond"
    """
    bounds = get_zone_bounds(spectral_class)   # already in sH
    if bounds is None:
        return "beyond"

    tl_lo, tl_hi = bounds["tidelock"]
    rk_lo, rk_hi = bounds["rocky"]
    gs_lo, gs_hi = bounds["gas"]
    ic_lo, ic_hi = bounds["ice"]
    bio            = bounds["biosphere"]

    if rk_lo <= distance_sh <= rk_hi:
        if tl_lo <= distance_sh <= tl_hi:
            return "hot"
        if bio is not None and bio[0] <= distance_sh <= bio[1]:
            return "lwz"
        return "cold_rocky"
    if gs_lo <= distance_sh <= gs_hi:
        return "gas"
    if ic_lo <= distance_sh <= ic_hi:
        return "ice"
    return "beyond"


# ---------------------------------------------------------------------------
# 4. Orbit distance table  (A, B) → tuple of up to 9 LM distances
# ---------------------------------------------------------------------------
# Key: (A, B) where A = lowest 1d10 result, B = highest, B >= A+2.
# Value: tuple of orbit distances I–IX in LM; None marks absent orbits.
# roll_orbit_distances() converts to sH before returning.

_ORBIT_TABLE: dict[tuple[int, int], tuple[int | None, ...]] = {
    (1, 3):  (12,   36,   60,  108,  204,   396,   780,  1548,  3084),
    (1, 4):  (12,   48,   84,  156,  300,   588,  1164,  2316,  None),
    (1, 5):  (12,   60,  108,  204,  396,   780,  1548,  3084,  None),
    (1, 6):  (12,   72,  132,  252,  492,   972,  1932,  None,  None),
    (1, 7):  (12,   84,  156,  300,  588,  1164,  2316,  None,  None),
    (1, 8):  (12,   96,  180,  348,  684,  1356,  2700,  None,  None),
    (1, 9):  (12,  108,  204,  396,  780,  1548,  3084,  None,  None),
    (1, 10): (12,  120,  228,  444,  876,  1740,  3468,  None,  None),
    (2, 4):  (24,   48,   72,  120,  216,   408,   792,  1560,  3096),
    (2, 5):  (24,   60,   96,  168,  312,   600,  1176,  2328,  None),
    (2, 6):  (24,   72,  120,  216,  408,   792,  1560,  3096,  None),
    (2, 7):  (24,   84,  144,  264,  504,   984,  1944,  None,  None),
    (2, 8):  (24,   96,  168,  312,  600,  1176,  2328,  None,  None),
    (2, 9):  (24,  108,  192,  360,  696,  1368,  2712,  None,  None),
    (2, 10): (24,  120,  216,  408,  792,  1560,  3096,  None,  None),
    (3, 5):  (36,   60,   84,  132,  228,   420,   804,  1572,  3108),
    (3, 6):  (36,   72,  108,  180,  324,   612,  1188,  2340,  None),
    (3, 7):  (36,   84,  132,  228,  420,   804,  1572,  3108,  None),
    (3, 8):  (36,   96,  156,  276,  516,   996,  1956,  None,  None),
    (3, 9):  (36,  108,  180,  324,  612,  1188,  2340,  None,  None),
    (3, 10): (36,  120,  204,  372,  708,  1380,  2724,  None,  None),
    (4, 6):  (48,   72,   96,  144,  240,   432,   816,  1584,  3120),
    (4, 7):  (48,   84,  120,  192,  336,   624,  1200,  2352,  None),
    (4, 8):  (48,   96,  144,  240,  432,   816,  1584,  3120,  None),
    (4, 9):  (48,  108,  168,  288,  528,  1008,  1968,  None,  None),
    (4, 10): (48,  120,  192,  336,  624,  1200,  2352,  None,  None),
    (5, 7):  (60,   84,  108,  156,  252,   444,   828,  1596,  3132),
    (5, 8):  (60,   96,  132,  204,  348,   636,  1212,  2364,  None),
    (5, 9):  (60,  108,  156,  252,  444,   828,  1596,  3132,  None),
    (5, 10): (60,  120,  180,  300,  540,  1020,  1980,  None,  None),
    (6, 8):  (72,   96,  120,  168,  264,   456,   840,  1608,  3144),
    (6, 9):  (72,  108,  144,  216,  360,   648,  1224,  2376,  None),
    (6, 10): (72,  120,  168,  264,  456,   840,  1608,  3144,  None),
    (7, 9):  (84,  108,  132,  180,  276,   468,   852,  1620,  3156),
    (7, 10): (84,  120,  156,  228,  372,   660,  1236,  2388,  None),
    (8, 10): (96,  120,  144,  192,  288,   480,   864,  1632,  3168),
}


def roll_orbit_distances(d1: int, d2: int) -> tuple[int | None, ...] | None:
    """Return orbit distance tuple (in sH) for a pair of 1d10 results.

    Automatically orders d1/d2 as (lo, hi).  Returns None if the gap is < 2
    (caller should re-roll).  LM values from the table are divided by
    LM_PER_SH and rounded to the nearest integer sH.
    """
    a, b = min(d1, d2), max(d1, d2)
    if b - a < 2:
        return None
    lm_tuple = _ORBIT_TABLE.get((a, b))
    if lm_tuple is None:
        return None
    return tuple(
        max(1, round(v / LM_PER_SH)) if v is not None else None
        for v in lm_tuple
    )


# ---------------------------------------------------------------------------
# 5. Planet mass + type by zone sub-type (1d100)
# ---------------------------------------------------------------------------
# Returns (mass: int | None, planet_type: PlanetType | None)
# None planet_type → no planet in this orbit.

def roll_planet(roll: int, zone_sub: str) -> tuple[int | None, PlanetType | None]:
    """Determine planet mass and type from a 1d100 roll and zone sub-type.

    zone_sub: "hot" | "lwz" | "cold_rocky" | "gas" | "ice"
    """
    if roll <= 0:
        roll = 100

    if roll <= 2:
        return None, None  # No planet

    if roll <= 5:
        return None, PlanetType.AST  # Asteroid belt regardless of zone

    # Determine mass band
    if roll <= 25:
        mass = 1
    elif roll <= 75:
        mass = 2
    else:
        mass = 3

    planet_type: PlanetType
    if zone_sub == "hot":
        if mass == 1:
            planet_type = PlanetType.H
        else:
            planet_type = PlanetType.V
    elif zone_sub == "lwz":
        if mass == 1:
            planet_type = PlanetType.B
        elif mass == 2:
            planet_type = PlanetType.T
        else:
            planet_type = PlanetType.ST
    elif zone_sub == "cold_rocky":
        planet_type = PlanetType.B
    elif zone_sub == "gas":
        if mass == 1:
            planet_type = PlanetType.B
        else:
            planet_type = PlanetType.G
    elif zone_sub == "ice":
        if mass == 1:
            planet_type = PlanetType.F
        else:
            planet_type = PlanetType.I
    else:
        return None, None  # "beyond" — no planet

    return mass, planet_type


# ---------------------------------------------------------------------------
# 6. WP quantity (1d100 + optional Nexus 1d10)
# ---------------------------------------------------------------------------

def roll_wp_count(roll100: int, category: str, roll10: int = 0) -> int:
    """Return WP count from a 1d100 roll and system category.

    If roll100 maps to "Nexus", roll10 (1d10) is used for the final count.
    category: "starless" | "without_planets" | "with_planets"
    """
    # (max_roll_inclusive, wp_count | "nexus")
    _TABLE: dict[str, list[tuple[int, int | str]]] = {
        "starless": [
            (1,   1), (19,  2), (58,  3), (77,  4), (97,  5), (100, "nexus"),
        ],
        "without_planets": [
            (9,   1), (29,  2), (67,  3), (87,  4), (97,  5), (100, "nexus"),
        ],
        "with_planets": [
            (19,  1), (38,  2), (77,  3), (96,  4), (97,  5), (100, "nexus"),
        ],
    }
    _NEXUS_TABLE: dict[str, list[tuple[int, int]]] = {
        "starless":        [(3, 6), (5, 7), (7, 8), (9, 9), (10, 10)],
        "without_planets": [(4, 6), (6, 7), (8, 8), (9, 9), (10, 10)],
        "with_planets":    [(5, 6), (7, 7), (8, 8), (9, 9), (10, 10)],
    }

    rows = _TABLE.get(category, _TABLE["with_planets"])
    for threshold, value in rows:
        if roll100 <= threshold:
            if value == "nexus":
                nexus_rows = _NEXUS_TABLE.get(category, _NEXUS_TABLE["with_planets"])
                for t, count in nexus_rows:
                    if roll10 <= t:
                        return count
                return 10
            return value  # type: ignore[return-value]
    return 5  # fallback


# ---------------------------------------------------------------------------
# 7. WP distance (1d100 → sH)
# ---------------------------------------------------------------------------

# (max_roll_inclusive, distance_LM) — converted to sH by roll_wp_distance
_WP_DISTANCE_ROWS: list[tuple[int, int]] = [
    (1,   12), (2,   24), (3,   36), (4,   48), (5,   60),
    (7,   72), (9,   84), (11,  96), (13, 108), (15, 120),
    (18, 132), (21, 144), (24, 156), (27, 168), (30, 180),
    (34, 192), (38, 204), (42, 216), (46, 228), (50, 240),
    (55, 252), (60, 264), (65, 276), (70, 288), (75, 300),
    (80, 312), (85, 324), (90, 336), (95, 348), (100, 360),
]


def roll_wp_distance(roll: int) -> int:
    """Map a 1d100 roll to a WP distance in sH (converted from stored LM value)."""
    if roll <= 0:
        roll = 100
    for threshold, dist_lm in _WP_DISTANCE_ROWS:
        if roll <= threshold:
            return max(1, round(dist_lm / LM_PER_SH))
    return max(1, round(360 / LM_PER_SH))


# ---------------------------------------------------------------------------
# 8. WP visibility (1d10)
# ---------------------------------------------------------------------------

def roll_wp_visibility(roll: int) -> WPVisibility:
    if roll <= 6:
        return WPVisibility.OPEN
    return WPVisibility.CLOSED


# ---------------------------------------------------------------------------
# 9. Moon count modifier by planet type and mass
# ---------------------------------------------------------------------------

def moon_count_modifier(planet_type: PlanetType, mass: int | None) -> int:
    """Return the modifier added to a 1d100 roll for moon count determination."""
    _ROCKY_TYPES = {PlanetType.F, PlanetType.B, PlanetType.H,
                    PlanetType.V, PlanetType.T, PlanetType.ST}
    mod = 0
    if planet_type in _ROCKY_TYPES and mass is not None:
        if mass == 1:
            mod += -50
        elif mass == 2:
            mod += -10
        # mass 3: +0
    if planet_type in {PlanetType.H, PlanetType.F}:
        mod += -15
    if planet_type == PlanetType.V:
        mod += -35
    if planet_type == PlanetType.I:
        mod += +35
    if planet_type == PlanetType.G:
        mod += +50
    return mod


def roll_moon_count(roll: int, planet_type: PlanetType, mass: int | None) -> int:
    """Return the number of moons from a modified 1d100 roll."""
    modified = roll + moon_count_modifier(planet_type, mass)
    if modified < 1:
        return 0
    if modified <= 55:
        return 1
    if modified <= 85:
        return 2
    if modified <= 105:
        return 3
    if modified <= 126:
        return 4
    return 5
