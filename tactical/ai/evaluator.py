"""BattleState evaluator — scores a state from one side's perspective.

evaluate(battle, owner_id, profile) -> float
    Positive = good for owner_id.  Magnitude is arbitrary but consistent
    within a session, so it can be used to compare candidate states.

Three components (weighted sum):
  1. Material score   — weighted active system count (my fleet − enemy fleet)
  2. Firepower score  — expected damage output at current range/arc
                        (my output − enemy output against me)
  3. Squadron score   — strength × endurance fraction (my squads − enemy squads)

The evaluation function is intentionally data-driven: it reasons from
WeaponSpec range tables and System base codes, not from hardcoded weapon
names or hull designations.  New weapons and hull types extend automatically.
"""

from __future__ import annotations

from sim.hexgrid import hex_distance
from tactical.arcs import relative_bearing, REAR_BEARINGS, REAR_ARC_TO_HIT_BONUS
from tactical.battle_state import BattleState
from tactical.weapons import WEAPONS, WeaponType
from tactical.ai.profile import AIProfile


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WEAPON_BASES: frozenset[str] = frozenset(wt.value for wt in WeaponType)

# Per-system-base material value weights.
# Weapons use the dynamic _weapon_value() helper instead.
_BASE_VALUE: dict[str, float] = {
    "S":  1.0,   # shield
    "A":  1.5,   # armour — more critical (protects inner systems)
    "I":  0.8,   # engine room system
    "D":  1.5,   # point defence
    "Bh": 3.0,   # hangar bay — high value (squadron capacity)
    "Bl": 1.2,   # launch bay
    "Q":  0.8,   # sensor (future)
    "F":  1.0,   # force beam (default weapon weight, overridden by _weapon_value)
}

# Evaluation component weights
_W_MATERIAL   = 1.0
_W_FIREPOWER  = 2.0
_W_SQUADRONS  = 0.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _weapon_value(base: str) -> float:
    """Estimated value of one active weapon system, derived from its spec.

    Uses expected damage at range 4 (a mid-board representative distance).
    This is the core of the data-driven approach: new weapons automatically
    get a sensible value without touching this file.

    NOTE: This is also the per-hex damage output function used internally.
    In the future, the same computation could power a player-facing heat map
    visualising firepower coverage across the board.
    """
    try:
        spec = WEAPONS[WeaponType(base)]
    except (KeyError, ValueError):
        return 1.0
    to_hit = spec.to_hit_at(4)
    damage = spec.damage.at(4)
    if to_hit is None or damage is None:
        return 0.5
    return (to_hit / 10.0) * damage * spec.rate_of_fire


def _system_value(base: str, charges: int = 0) -> float:
    """Value of one active system of the given base type."""
    if base in _WEAPON_BASES:
        return _weapon_value(base)
    if base == "Mg":
        # Magazine: marginal value per remaining shot
        return 0.02 * charges
    return _BASE_VALUE.get(base, 1.0)


# ---------------------------------------------------------------------------
# Component scorers
# ---------------------------------------------------------------------------

def _fleet_material(battle: BattleState, owner_id: str) -> float:
    """Weighted sum of all active systems for owner_id's ships."""
    total = 0.0
    for ship in battle.ships.values():
        if ship.owner_id != owner_id or ship.systems is None:
            continue
        # Capital ships (large hull) get a slight value bonus — they are
        # harder to replace than escorts.
        hull_bonus = 1.5 if (
            ship.hull_type is not None
            and ship.hull_type.designation in ("CA", "CV")
        ) else 1.0

        for sys in ship.systems:
            if sys.is_active():
                total += _system_value(sys.base, sys.charges) * hull_bonus
    return total


def expected_firepower_at(
    battle: BattleState,
    owner_id: str,
    *,
    from_hex=None,
    from_facing=None,
) -> float:
    """Expected damage output from owner_id's ships at their current (or given)
    position/facing, summed over all reachable enemy ships.

    from_hex / from_facing: if provided, evaluate as if the ships were at
    those positions instead of their actual positions.  Unused in the default
    evaluator but exposed for the move_ai position scorer and, in the future,
    for heat-map visualisation.
    """
    my_ships = [s for s in battle.ships.values() if s.owner_id == owner_id]
    enemy_ships = [s for s in battle.ships.values() if s.owner_id != owner_id]
    if not enemy_ships:
        return 0.0

    total = 0.0
    for ship in my_ships:
        if ship.systems is None:
            continue
        pos     = from_hex    if from_hex    is not None else ship.pos
        facing  = from_facing if from_facing is not None else int(ship.facing)

        for enemy in enemy_ships:
            dq = enemy.pos.q - pos.q
            dr = enemy.pos.r - pos.r
            rb = relative_bearing(facing, dq, dr)
            if rb in REAR_BEARINGS:
                continue  # blind spot — can't fire here

            dist = hex_distance(pos, enemy.pos)

            # Rear-arc bonus: if we are in the enemy's rear arc, our to-hit improves.
            edq = pos.q - enemy.pos.q
            edr = pos.r - enemy.pos.r
            e_rb = relative_bearing(int(enemy.facing), edq, edr)
            arc_bonus = REAR_ARC_TO_HIT_BONUS if e_rb in REAR_BEARINGS else 0

            for sys in ship.systems:
                if not sys.is_active() or sys.base not in _WEAPON_BASES:
                    continue
                try:
                    spec = WEAPONS[WeaponType(sys.base)]
                except (KeyError, ValueError):
                    continue
                to_hit = spec.to_hit_at(dist)
                damage = spec.damage.at(dist)
                if to_hit is None or damage is None:
                    continue
                effective_to_hit = min(10, to_hit + arc_bonus)
                total += (effective_to_hit / 10.0) * damage * spec.rate_of_fire

    return total


def _squadron_score(battle: BattleState, owner_id: str) -> float:
    """Score from deployed and docked squadrons (strength × endurance fraction)."""
    score = 0.0
    for sq in battle.squadrons.values():
        if sq.owner_id != owner_id or sq.is_destroyed():
            continue
        endurance_frac = sq.endurance / max(1, sq.max_endurance)
        base = sq.strength * endurance_frac
        # Slight bonus for being actively deployed
        score += base * (1.2 if sq.is_deployed else 1.0)
    return score


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate(battle: BattleState, owner_id: str, profile: AIProfile) -> float:
    """Score BattleState from owner_id's perspective.  Higher = better.

    Composed of three weighted terms:
      material  — net active-system value (favours survival)
      firepower — net expected damage output at current positions (favours
                  good positioning)
      squadrons — net squadron strength × endurance (favours a healthy
                  fighter wing)
    """
    all_sides = {s.owner_id for s in battle.ships.values()}
    enemy_sides = all_sides - {owner_id}

    my_material    = _fleet_material(battle, owner_id)
    enemy_material = sum(_fleet_material(battle, sid) for sid in enemy_sides)

    my_firepower    = expected_firepower_at(battle, owner_id)
    enemy_firepower = sum(expected_firepower_at(battle, sid) for sid in enemy_sides)

    my_squads    = _squadron_score(battle, owner_id)
    enemy_squads = sum(_squadron_score(battle, sid) for sid in enemy_sides)

    return (
        _W_MATERIAL  * (my_material   - enemy_material)
        + _W_FIREPOWER * (my_firepower  - enemy_firepower)
        + _W_SQUADRONS * (my_squads     - enemy_squads)
    )
