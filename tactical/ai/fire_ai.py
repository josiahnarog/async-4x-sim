"""Fire-phase AI — chooses targets for each capital ship.

choose_fire_orders(battle, owner_id, profile, rng)
    -> dict[ShipID, ShipFireOrder | None]

Strategy: greedy 1-ply.  For each ship, score every legal target as:

    expected_damage × target_priority + Gaussian(0, profile.noise)

and pick the highest.  No lookahead needed for the fire phase because
fire does not move units — the position is already fixed at this point,
so one-shot optimisation is sufficient.

Target priority gives extra weight to carriers (high-value, fragile) and
to targets that are already damaged (finish them before they repair).
"""

from __future__ import annotations

import random

from sim.hexgrid import hex_distance
from tactical.arcs import relative_bearing, REAR_BEARINGS, REAR_ARC_TO_HIT_BONUS, mount_type, bearing_blocked
from tactical.ship_catalog import system_hull_spaces
from tactical.battle_state import BattleState, ShipID
from tactical.turn_orders import ShipFireOrder
from tactical.weapons import WEAPONS, WeaponType
from tactical.ai.profile import AIProfile


_WEAPON_BASES: frozenset[str] = frozenset(wt.value for wt in WeaponType)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _target_priority(target_ship, profile: AIProfile) -> float:
    """Priority multiplier for a target.  Higher = shoot this first."""
    if target_ship.systems is None:
        return 1.0
    # Carriers are high-value targets.
    if target_ship.systems.active_count("Bh") > 0:
        return profile.carrier_value
    return 1.0


def _expected_damage(attacker, target, dist: int) -> float:
    """Expected damage output from attacker to target at dist.

    Accounts for:
      - each active weapon system on the attacker
      - the rear-arc to-hit bonus if the attacker is behind the target
      - range dropoff via each weapon's RangeTable
    """
    if attacker.systems is None:
        return 0.0

    # Rear-arc bonus: attacker in target's rear arc → +2 to-hit.
    edq = attacker.pos.q - target.pos.q
    edr = attacker.pos.r - target.pos.r
    e_rb = relative_bearing(int(target.facing), edq, edr)
    arc_bonus = REAR_ARC_TO_HIT_BONUS if e_rb in REAR_BEARINGS else 0

    rb = relative_bearing(
        int(attacker.facing),
        target.pos.q - attacker.pos.q,
        target.pos.r - attacker.pos.r,
    )
    ship_hs = sum(system_hull_spaces(s.token) for s in attacker.systems)

    total = 0.0
    for sys in attacker.systems:
        if not sys.is_active() or sys.base not in _WEAPON_BASES:
            continue
        try:
            spec = WEAPONS[WeaponType(sys.base)]
        except (KeyError, ValueError):
            continue
        whs = system_hull_spaces(sys.token)
        if bearing_blocked(rb, mount_type(whs, ship_hs)):
            continue
        to_hit = spec.to_hit_at(dist)
        damage = spec.damage.at(dist)
        if to_hit is None or damage is None:
            continue
        effective_to_hit = min(10, to_hit + arc_bonus)
        total += (effective_to_hit / 10.0) * damage * spec.rate_of_fire

    return total


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def choose_fire_orders(
    battle: BattleState,
    owner_id: str,
    profile: AIProfile,
    rng: random.Random,
) -> dict[ShipID, ShipFireOrder | None]:
    """Return a fire order (or None = explicit pass) for each owned ship.

    Ships with no legal targets, or with destroyed/missing systems, pass.
    """
    enemy_ship_ids = [
        sid for sid, s in battle.ships.items()
        if s.owner_id != owner_id
    ]
    orders: dict[ShipID, ShipFireOrder | None] = {}

    for ship_id, ship in battle.ships.items():
        if ship.owner_id != owner_id:
            continue
        if ship.systems is None or ship.systems.is_destroyed():
            orders[ship_id] = None
            continue

        best_target: ShipID | None = None
        best_score = -1e9

        for t_id in enemy_ship_ids:
            target = battle.ships[t_id]

            # Blind-spot check: target must be in the attacker's front arc.
            dq = target.pos.q - ship.pos.q
            dr = target.pos.r - ship.pos.r
            rb = relative_bearing(int(ship.facing), dq, dr)
            if rb in REAR_BEARINGS:
                continue

            dist = hex_distance(ship.pos, target.pos)
            ev = _expected_damage(ship, target, dist)
            if ev <= 0:
                continue  # no weapon can reach — don't waste ammo
            score = ev * _target_priority(target, profile) + rng.gauss(0, profile.noise)
            if score > best_score:
                best_score = score
                best_target = t_id

        orders[ship_id] = ShipFireOrder(target_id=best_target) if best_target else None

    return orders
