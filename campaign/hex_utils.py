"""Pure hex-grid math for the campaign layer.

Both strategic (sH) and tactical (TH) scales use identical axial coordinates —
the math is scale-agnostic.  Callers pass distances in whatever unit is
appropriate; the returned (q, r) pairs are in the same unit space.

Coordinate conventions
----------------------
* Flat-top axial (q, r).  Primary at (0, 0).
* Screen y increases downward (SVG convention).
* Compass bearings: 0° = north, clockwise.  Starfire bearing 1 = 0°.
* hex_dist from origin equals the Starfire sH distance for objects placed
  on a ring via nearest_ring_hex; WP/star snapping may differ by ≤ 1 hex.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Direction vectors for ring / disk traversal (flat-top axial)
# Index: 0=E, 1=SE, 2=SW, 3=W, 4=NW, 5=NE  (SVG y-down orientation)
# ---------------------------------------------------------------------------

AXIAL_DIRECTIONS: list[tuple[int, int]] = [
    (1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1),
]


# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------

def axial_to_screen(q: int | float, r: int | float) -> tuple[float, float]:
    """Flat-top axial (q, r) → continuous screen coords (x, y) in hex-units.

    Multiply by pixel_size to get pixel offsets from grid centre.
    """
    x = 1.5 * q
    y = math.sqrt(3) * (r + q * 0.5)
    return x, y


def screen_to_axial_frac(x: float, y: float) -> tuple[float, float]:
    """Continuous screen coords (hex-units) → fractional axial (q_f, r_f).

    Exact inverse of axial_to_screen.
    """
    sq3 = math.sqrt(3)
    q_f = (2.0 / 3.0) * x
    r_f = y / sq3 - x / 3.0
    return q_f, r_f


def cube_round(q_f: float, r_f: float) -> tuple[int, int]:
    """Round fractional axial coords to the nearest integer hex."""
    s_f = -q_f - r_f
    q, r, s = round(q_f), round(r_f), round(s_f)
    dq = abs(q - q_f)
    dr = abs(r - r_f)
    ds = abs(s - s_f)
    if dq > dr and dq > ds:
        q = -r - s
    elif dr > ds:
        r = -q - s
    return q, r


def hex_dist(q1: int, r1: int, q2: int = 0, r2: int = 0) -> int:
    """Hex-grid distance between two axial positions."""
    dq = q1 - q2
    dr = r1 - r2
    return max(abs(dq), abs(dr), abs(dq + dr))


# ---------------------------------------------------------------------------
# Bearing / angle ↔ axial
# ---------------------------------------------------------------------------

def bearing_dist_to_axial(bearing: int, distance: int) -> tuple[int, int]:
    """Starfire bearing (1–12) + distance (hex-units) → nearest axial hex.

    Bearing 1 = north (−y in SVG).  Each step = 30° clockwise.
    Works at any scale: pass sH distances for strategic, TH for tactical.
    Objects with non-hex-aligned bearings (e.g. bearing 2, 4, …) snap to
    the nearest hex; the returned hex_dist from origin may differ from the
    Starfire distance by up to 1 hex at intermediate bearings.
    """
    return angle_to_axial((bearing - 1) * 30.0, distance)


def angle_to_axial(angle_deg: float, distance: int | float) -> tuple[int, int]:
    """Compass angle (0 = north, CW) + distance (hex-units) → nearest axial hex."""
    rad = math.radians(angle_deg)
    x = distance * math.sin(rad)
    y = -distance * math.cos(rad)      # north = negative SVG-y
    return cube_round(*screen_to_axial_frac(x, y))


def axial_to_angle(q: int, r: int) -> float:
    """Axial position → compass angle in degrees (0 = north, clockwise).

    Returns a value in [0, 360).  Returns 0.0 for origin.
    """
    x, y = axial_to_screen(q, r)
    if x == 0.0 and y == 0.0:
        return 0.0
    return math.degrees(math.atan2(x, -y)) % 360.0


# ---------------------------------------------------------------------------
# Ring and disk enumeration
# ---------------------------------------------------------------------------

def hex_ring(center_q: int, center_r: int, radius: int) -> list[tuple[int, int]]:
    """All hexes at exactly `radius` hex-steps from (center_q, center_r).

    Returns 6 * radius hexes for radius >= 1, or [(center_q, center_r)] for 0.
    Traversal order: starts at the NW corner, walks clockwise.
    """
    if radius == 0:
        return [(center_q, center_r)]
    results: list[tuple[int, int]] = []
    # Start at direction[4] * radius from centre = (0, -radius) offset
    q = center_q + AXIAL_DIRECTIONS[4][0] * radius
    r = center_r + AXIAL_DIRECTIONS[4][1] * radius
    for i in range(6):
        dq, dr = AXIAL_DIRECTIONS[i]
        for _ in range(radius):
            results.append((q, r))
            q += dq
            r += dr
    return results


def hex_disk(center_q: int, center_r: int, radius: int) -> list[tuple[int, int]]:
    """All hexes within `radius` hex-steps of (center_q, center_r), inclusive."""
    results: list[tuple[int, int]] = []
    for q in range(center_q - radius, center_q + radius + 1):
        for r in range(center_r - radius, center_r + radius + 1):
            if hex_dist(q, r, center_q, center_r) <= radius:
                results.append((q, r))
    return results


def nearest_ring_hex(angle_deg: float, radius: int) -> tuple[int, int]:
    """Return the hex on hex_ring(0, 0, radius) angularly closest to angle_deg.

    'Closest' means smallest angular difference (compass degrees, both
    directions considered).  Tie-breaks are deterministic via ring order.
    Used to place planets, moons, and other orbital objects on their rings
    so that hex_dist from origin == radius (zone-colouring invariant).
    """
    if radius == 0:
        return (0, 0)

    def _angular_diff(a: float, b: float) -> float:
        d = abs(a - b) % 360.0
        return min(d, 360.0 - d)

    ring = hex_ring(0, 0, radius)
    return min(ring, key=lambda pos: _angular_diff(axial_to_angle(pos[0], pos[1]), angle_deg))


# ---------------------------------------------------------------------------
# Orbital helpers
# ---------------------------------------------------------------------------

def orbital_angle_at(angle_0: float, period: float, t: float) -> float:
    """Compass angle of an orbiting body at time t.

    angle_0  — initial compass angle (degrees) at t = 0.
    period   — orbital period in the same time unit as t.
    t        — elapsed time.

    Returns angle in [0, 360).  period = 0 means fixed (non-orbiting).
    """
    if period <= 0.0:
        return angle_0 % 360.0
    return (angle_0 + 360.0 * t / period) % 360.0


def hex_position_at(angle_0: float, period: float, distance: int, t: float) -> tuple[int, int]:
    """Axial hex of an orbiting body at time t.

    Snaps to the nearest ring hex for the body's orbital radius.
    """
    angle = orbital_angle_at(angle_0, period, t)
    return nearest_ring_hex(angle, distance)
