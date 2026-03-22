"""Sensor suite and fog-of-war detection rules for tactical combat.

Detection table (diff = sensor_level - cloak_level, clamped to [-3, 3]):
    diff \ range  <1000  <100  <20  <10  <5
         3:        2      3     3    3    3
         2:        1      2     3    3    3
         1:        1      1     2    3    3
         0:        0      1     1    2    3
        -1:        0      0     1    1    2
        -2:        0      0     0    1    1
        -3:        0      0     0    0    1

Detection levels:
    0 = undetected
    1 = presence + major_status flags
    2 = class + system_count
    3 = full detail
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tactical.battle_state import BattleState
    from tactical.ship_state import ShipState

BASE_SENSOR_LEVEL = 0
BASE_CLOAK_LEVEL = 0

# Detection table: rows are diff indices [-3, -2, -1, 0, 1, 2, 3] → index = diff + 3
# Columns: range<1000 (idx 0), <100 (idx 1), <20 (idx 2), <10 (idx 3), <5 (idx 4)
_DETECTION_TABLE = [
    # diff=-3
    [0, 0, 0, 0, 1],
    # diff=-2
    [0, 0, 0, 1, 1],
    # diff=-1
    [0, 0, 1, 1, 2],
    # diff=0
    [0, 1, 1, 2, 3],
    # diff=1
    [1, 1, 2, 3, 3],
    # diff=2
    [1, 2, 3, 3, 3],
    # diff=3
    [2, 3, 3, 3, 3],
]


def _y_tier(mods: str) -> int:
    """Return the tier of a Y system based on its modifier string.

    "" → 1 (basic sensors)
    "i" → 2 (improved sensors)
    "a" → 3 (advanced sensors)
    anything else → 1
    """
    if mods == "i":
        return 2
    if mods == "a":
        return 3
    return 1


def sensor_level(ship: "ShipState") -> int:
    """Return the effective sensor level for a ship.

    Uses the best active Y system tier. Multiple Y systems of the same tier
    do not stack. Returns BASE_SENSOR_LEVEL (0) if no active Y systems.
    """
    if ship.systems is None:
        return BASE_SENSOR_LEVEL
    best = BASE_SENSOR_LEVEL
    for sys in ship.systems:
        if sys.base == "Y" and sys.is_active():
            tier = _y_tier(sys.mods)
            if tier > best:
                best = tier
    return best


def cloak_level(ship: "ShipState") -> int:
    """Return the effective cloak level for a ship.

    Counts active Clk systems (hook for future use; currently always 0 if
    no Clk systems present). Returns BASE_CLOAK_LEVEL (0) if none active.
    """
    if ship.systems is None:
        return BASE_CLOAK_LEVEL
    count = sum(1 for sys in ship.systems if sys.token == "Clk" and sys.is_active())
    return count


def detection_level(sensor_lvl: int, cloak_lvl: int, hex_range: int) -> int:
    """Look up detection level from the table.

    Args:
        sensor_lvl: observer's sensor level
        cloak_lvl: target's cloak level
        hex_range: distance in hexes between observer and target

    Returns:
        Detection level 0-3.
    """
    if hex_range >= 1000:
        return 0

    diff = sensor_lvl - cloak_lvl
    diff = max(-3, min(3, diff))  # clamp to [-3, 3]
    row = _DETECTION_TABLE[diff + 3]

    # Check smallest threshold first (range<5 → col 4, <10 → col 3, etc.)
    if hex_range < 5:
        col = 4
    elif hex_range < 10:
        col = 3
    elif hex_range < 20:
        col = 2
    elif hex_range < 100:
        col = 1
    else:
        col = 0

    return row[col]


def major_status_flags(ship: "ShipState") -> list[str]:
    """Return major status flags visible at detection level 1.

    Flags:
        "SHIELDS DOWN"      — no active S systems
        "STREAMING ATMO"    — no active A systems
        "ENGINES DAMAGED"   — some I systems destroyed (but not all)
        "ENGINES DISABLED"  — all I systems destroyed
    """
    if ship.systems is None:
        return []

    flags: list[str] = []

    # Shield check
    has_shield = any(s.base == "S" and s.is_active() for s in ship.systems)
    if not has_shield:
        flags.append("SHIELDS DOWN")

    # Armor check
    has_armor = any(s.base == "A" and s.is_active() for s in ship.systems)
    if not has_armor:
        flags.append("STREAMING ATMO")

    # Engine check
    all_engines = [s for s in ship.systems if s.base == "I"]
    active_engines = [s for s in all_engines if s.is_active()]
    if all_engines:
        if len(active_engines) == 0:
            flags.append("ENGINES DISABLED")
        elif len(active_engines) < len(all_engines):
            flags.append("ENGINES DAMAGED")

    return flags


def compute_detections(
    battle: "BattleState",
    observer_side: str,
) -> dict[str, int]:
    """Compute detection levels for all enemy units from the observer's perspective.

    For every enemy ship and deployed enemy squadron, compute the best detection
    level from any non-destroyed friendly ship or any deployed friendly squadron.

    Own units are not included in the output (they're always level 3 by definition).

    Args:
        battle: current battle state
        observer_side: the side doing the observing

    Returns:
        Dict mapping unit_id → best detection level (0-3).
    """
    from sim.hexgrid import hex_distance

    result: dict[str, int] = {}

    # Collect friendly observers: non-destroyed friendly ships and deployed friendly squadrons.
    friendly_ships = [
        (sid, ship)
        for sid, ship in battle.ships.items()
        if ship.owner_id == observer_side
        and (ship.systems is None or not ship.systems.is_destroyed())
    ]
    friendly_squadrons = [
        (sqid, sq)
        for sqid, sq in battle.squadrons.items()
        if sq.owner_id == observer_side and sq.is_deployed
    ]

    # Check enemy ships
    for sid, ship in battle.ships.items():
        if ship.owner_id == observer_side:
            continue

        best = 0

        # From friendly ships (use their sensor level)
        for _, obs_ship in friendly_ships:
            obs_sensor = sensor_level(obs_ship)
            tgt_cloak = cloak_level(ship)
            dist = hex_distance(obs_ship.pos, ship.pos)
            lvl = detection_level(obs_sensor, tgt_cloak, dist)
            if lvl > best:
                best = lvl
            if best == 3:
                break

        # From deployed friendly squadrons (use BASE_SENSOR_LEVEL)
        if best < 3:
            for _, obs_sq in friendly_squadrons:
                tgt_cloak = cloak_level(ship)
                dist = hex_distance(obs_sq.pos, ship.pos)
                lvl = detection_level(BASE_SENSOR_LEVEL, tgt_cloak, dist)
                if lvl > best:
                    best = lvl
                if best == 3:
                    break

        result[sid] = best

    # Check enemy deployed squadrons
    for sqid, sq in battle.squadrons.items():
        if sq.owner_id == observer_side:
            continue
        if not sq.is_deployed:
            continue

        best = 0

        # From friendly ships
        for _, obs_ship in friendly_ships:
            obs_sensor = sensor_level(obs_ship)
            dist = hex_distance(obs_ship.pos, sq.pos)
            lvl = detection_level(obs_sensor, BASE_CLOAK_LEVEL, dist)
            if lvl > best:
                best = lvl
            if best == 3:
                break

        # From deployed friendly squadrons
        if best < 3:
            for _, obs_sq in friendly_squadrons:
                dist = hex_distance(obs_sq.pos, sq.pos)
                lvl = detection_level(BASE_SENSOR_LEVEL, BASE_CLOAK_LEVEL, dist)
                if lvl > best:
                    best = lvl
                if best == 3:
                    break

        result[sqid] = best

    return result


def update_knowledge(
    old: dict[str, int],
    current: dict[str, int],
) -> dict[str, int]:
    """Update a side's knowledge dict with new sensor readings.

    Rules:
        - If current level == 0 for a unit → reset to 0 (lost contact).
        - If current level > 0 → max(old, current).
        - Units not in current are left unchanged in old.

    Args:
        old: previous knowledge dict {unit_id → detection_level}
        current: freshly computed detections for this turn

    Returns:
        Updated knowledge dict.
    """
    result = dict(old)
    for unit_id, lvl in current.items():
        if lvl == 0:
            result[unit_id] = 0
        else:
            result[unit_id] = max(result.get(unit_id, 0), lvl)
    return result
