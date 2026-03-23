from __future__ import annotations

import math
from enum import Enum


class Arc(Enum):
    """Arc classification relative to a unit's facing direction.

    FRONT — relative bearings 0, 1, 5 (forward 180°). Firing permitted.
    REAR  — relative bearings 2, 3, 4 (rear 180°). Blind spot; firing is blocked.

    Relative bearing 0 = dead ahead, 3 = dead astern.
    Bearings increase clockwise: 0→1→2 is a right turn.
    """
    FRONT = "front"
    REAR  = "rear"   # dead astern (relative bearing 3) — 60° blind-spot cone


# How much the to-hit target number increases when the attacker is in the TARGET's
# rear arc. Positive = easier to hit (d10, hit if roll <= target).
REAR_ARC_TO_HIT_BONUS: int = 2

REAR_BEARINGS: frozenset[int] = frozenset({3})  # dead astern only (60° blind spot)


def _absolute_bearing(dq: int, dr: int) -> int:
    """Facing index (0-5) most closely aligned with vector (dq, dr).

    Converts axial hex delta to flat-top pixel space (r increases upward,
    canvas y increases downward), then maps pixel-space angle to facing index.

        dx = 1.5 * dq
        dy = -(sqrt(3)/2 * dq  +  sqrt(3) * dr)   [r negated for canvas y]

    Facing 0 (N) maps to angle -pi/2; each subsequent facing adds pi/3.
    """
    if dq == 0 and dr == 0:
        return 0
    dx = 1.5 * dq
    dy = -(math.sqrt(3) / 2 * dq + math.sqrt(3) * dr)
    angle = math.atan2(dy, dx)
    return round((angle + math.pi / 2) / (math.pi / 3)) % 6


def relative_bearing(from_facing: int, dq: int, dr: int) -> int:
    """Relative bearing (0-5) of the point (dq, dr) from a unit at `from_facing`.

    0 = dead ahead, 1 = 60° right, 2 = 120° right,
    3 = dead astern, 4 = 120° left, 5 = 60° left.
    """
    return (_absolute_bearing(dq, dr) - from_facing) % 6


def arc_of(observer_facing: int, dq: int, dr: int) -> Arc:
    """Which arc is the point (dq, dr) in, from the observer's perspective?"""
    rb = relative_bearing(observer_facing, dq, dr)
    return Arc.REAR if rb in REAR_BEARINGS else Arc.FRONT


def assert_can_fire(
    attacker_facing: int,
    attacker_pos: object,
    target_pos: object,
    attacker_id: str,
    target_id: str,
) -> int:
    """Validate that attacker can fire toward target (target not in blind spot).

    Returns the relative bearing on success.
    Raises ValueError if the target is in the attacker's rear arc.
    """
    dq = target_pos.q - attacker_pos.q  # type: ignore[attr-defined]
    dr = target_pos.r - attacker_pos.r  # type: ignore[attr-defined]
    rb = relative_bearing(attacker_facing, dq, dr)
    if rb in REAR_BEARINGS:
        raise ValueError(
            f"{attacker_id} cannot fire at {target_id}: "
            f"target is in blind spot (relative bearing {rb})"
        )
    return rb
