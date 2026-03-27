"""All lookup tables for the campaign system generator.

All distance values are in sH (strategic hexes) unless noted otherwise.
"""

from __future__ import annotations

from campaign.models import AnomalyType, PlanetType, SpectralClass, WPVisibility


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
# 3. Zone boundaries by spectral class (distances in sH)
# ---------------------------------------------------------------------------
# Each entry: {"rocky": (lo, hi), "gas": (lo, hi), "ice": (lo, hi),
#              "biosphere": (lo, hi) | None, "tidelock": (lo, hi)}

_ZONE_BOUNDS: dict[SpectralClass, dict] = {
    SpectralClass.WHITE: {
        "rocky":     (1,   50),
        "gas":       (51,  280),
        "ice":       (281, 350),
        "biosphere": (20,  40),
        "tidelock":  (1,   5),
    },
    SpectralClass.YELLOW_WHITE: {
        "rocky":     (1,   25),
        "gas":       (26,  130),
        "ice":       (131, 300),
        "biosphere": (10,  18),
        "tidelock":  (1,   4),
    },
    SpectralClass.YELLOW: {
        "rocky":     (1,   16),
        "gas":       (17,  83),
        "ice":       (84,  300),
        "biosphere": (6,   12),
        "tidelock":  (1,   3),
    },
    SpectralClass.ORANGE: {
        "rocky":     (1,   9),
        "gas":       (10,  38),
        "ice":       (39,  250),
        "biosphere": (3,   5),
        "tidelock":  (1,   2),
    },
    SpectralClass.RED: {
        "rocky":     (1,   5),
        "gas":       (6,   18),
        "ice":       (19,  200),
        "biosphere": (3,   4),
        "tidelock":  (1,   2),
    },
    SpectralClass.RED_DWARF: {
        "rocky":     (1,   3),
        "gas":       (4,   11),
        "ice":       (12,  200),
        "biosphere": None,
        "tidelock":  (1,   1),
    },
}


def get_zone_bounds(spectral_class: SpectralClass) -> dict | None:
    """Return zone boundary dict for a spectral class, or None if not applicable."""
    return _ZONE_BOUNDS.get(spectral_class)


def classify_orbit(spectral_class: SpectralClass, distance_sh: int) -> str:
    """Return the zone sub-type key for an orbit.

    Returns one of: "hot", "lwz", "cold_rocky", "gas", "ice", "beyond"
    """
    bounds = _ZONE_BOUNDS.get(spectral_class)
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
# 4. Orbit distance table  (A, B) → tuple of up to 9 sH distances
# ---------------------------------------------------------------------------
# Key: (A, B) where A = lowest 1d10 result, B = highest, B >= A+2.
# Value: tuple of orbit distances I–IX in sH; None marks absent orbits.

_ORBIT_TABLE: dict[tuple[int, int], tuple[int | None, ...]] = {
    (1, 3):  (1,  3,   5,   9,  17,  33,  65, 129, 257),
    (1, 4):  (1,  4,   7,  13,  25,  49,  97, 193, None),
    (1, 5):  (1,  5,   9,  17,  33,  65, 129, 257, None),
    (1, 6):  (1,  6,  11,  21,  41,  81, 161, None, None),
    (1, 7):  (1,  7,  13,  25,  49,  97, 193, None, None),
    (1, 8):  (1,  8,  15,  29,  57, 113, 225, None, None),
    (1, 9):  (1,  9,  17,  33,  65, 129, 257, None, None),
    (1, 10): (1, 10,  19,  37,  73, 145, 289, None, None),
    (2, 4):  (2,  4,   6,  10,  18,  34,  66, 130, 258),
    (2, 5):  (2,  5,   8,  14,  26,  50,  98, 194, None),
    (2, 6):  (2,  6,  10,  18,  34,  66, 130, 258, None),
    (2, 7):  (2,  7,  12,  22,  42,  82, 162, None, None),
    (2, 8):  (2,  8,  14,  26,  50,  98, 194, None, None),
    (2, 9):  (2,  9,  16,  30,  58, 114, 226, None, None),
    (2, 10): (2, 10,  18,  34,  66, 130, 258, None, None),
    (3, 5):  (3,  5,   7,  11,  19,  35,  67, 131, 259),
    (3, 6):  (3,  6,   9,  15,  27,  51,  99, 195, None),
    (3, 7):  (3,  7,  11,  19,  35,  67, 131, 259, None),
    (3, 8):  (3,  8,  13,  23,  43,  83, 163, None, None),
    (3, 9):  (3,  9,  15,  27,  51,  99, 195, None, None),
    (3, 10): (3, 10,  17,  31,  59, 115, 227, None, None),
    (4, 6):  (4,  6,   8,  12,  20,  36,  68, 132, 260),
    (4, 7):  (4,  7,  10,  16,  28,  52, 100, 196, None),
    (4, 8):  (4,  8,  12,  20,  36,  68, 132, 260, None),
    (4, 9):  (4,  9,  14,  24,  44,  84, 164, None, None),
    (4, 10): (4, 10,  16,  28,  52, 100, 196, None, None),
    (5, 7):  (5,  7,   9,  13,  21,  37,  69, 133, 261),
    (5, 8):  (5,  8,  11,  17,  29,  53, 101, 197, None),
    (5, 9):  (5,  9,  13,  21,  37,  69, 133, 261, None),
    (5, 10): (5, 10,  15,  25,  45,  85, 165, None, None),
    (6, 8):  (6,  8,  10,  14,  22,  38,  70, 134, 262),
    (6, 9):  (6,  9,  12,  18,  30,  54, 102, 198, None),
    (6, 10): (6, 10,  14,  22,  38,  70, 134, 262, None),
    (7, 9):  (7,  9,  11,  15,  23,  39,  71, 135, 263),
    (7, 10): (7, 10,  13,  19,  31,  55, 103, 199, None),
    (8, 10): (8, 10,  12,  16,  24,  40,  72, 136, 264),
}


def roll_orbit_distances(d1: int, d2: int) -> tuple[int | None, ...] | None:
    """Return orbit distance tuple for a pair of 1d10 results.

    Automatically orders d1/d2 as (lo, hi).  Returns None if the gap is < 2
    (caller should re-roll).
    """
    a, b = min(d1, d2), max(d1, d2)
    if b - a < 2:
        return None
    return _ORBIT_TABLE.get((a, b))


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

# (max_roll_inclusive, distance_sH)
_WP_DISTANCE_ROWS: list[tuple[int, int]] = [
    (1,  1),  (2,  2),  (3,  3),  (4,  4),  (5,  5),
    (7,  6),  (9,  7),  (11, 8),  (13, 9),  (15, 10),
    (18, 11), (21, 12), (24, 13), (27, 14), (30, 15),
    (34, 16), (38, 17), (42, 18), (46, 19), (50, 20),
    (55, 21), (60, 22), (65, 23), (70, 24), (75, 25),
    (80, 26), (85, 27), (90, 28), (95, 29), (100, 30),
]


def roll_wp_distance(roll: int) -> int:
    """Map a 1d100 roll to a WP distance in sH."""
    if roll <= 0:
        roll = 100
    for threshold, dist in _WP_DISTANCE_ROWS:
        if roll <= threshold:
            return dist
    return 30


# ---------------------------------------------------------------------------
# 8. WP visibility (1d10)
# ---------------------------------------------------------------------------

def roll_wp_visibility(roll: int) -> WPVisibility:
    if roll <= 6:
        return WPVisibility.OPEN
    if roll <= 8:
        return WPVisibility.CONCEALED
    if roll == 9:
        return WPVisibility.HIDDEN
    return WPVisibility.SECRET


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
