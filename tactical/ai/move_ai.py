"""Move-phase AI — chooses destination and facing for each capital ship.

choose_move_orders(battle, owner_id, mp_capacities, profile, rng)
    -> dict[ShipID, tuple[Hex, Facing]]

Strategy: greedy 1-ply position evaluation.

For each ship, a set of candidate (dest, facing) pairs is generated around
each enemy ship at the weapon's preferred effective range.  Each candidate is
scored by:

    outgoing_firepower - evasion_weight * incoming_firepower + noise

where evasion_weight is modulated by profile.aggression.

The candidate with the highest score is chosen, subject to MP reachability.

NOTE: _score_candidate() computes per-hex expected damage/incoming-damage
      arrays that are architecturally identical to what a player-facing heat
      map would need.  The evaluator.expected_firepower_at() helper exposes
      the same data via a public API, making it straightforward to drive a
      board-wide heat map visualisation from this same logic in the future.
"""

from __future__ import annotations

import math
import random

from sim.hexgrid import Hex, greedy_path, hex_distance
from tactical.arcs import relative_bearing, REAR_BEARINGS, REAR_ARC_TO_HIT_BONUS
from tactical.battle_state import BattleState, ShipID
from tactical.facing import Facing
from tactical.ship_state import ShipState
from tactical.weapons import WEAPONS, WeaponType
from tactical.ai.profile import AIProfile


_WEAPON_BASES: frozenset[str] = frozenset(wt.value for wt in WeaponType)

# Maximum candidate positions to evaluate per ship (caps compute cost).
_MAX_CANDIDATES = 24


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _absolute_bearing(dq: int, dr: int) -> int:
    """Hex facing index (0-5) most closely aligned with vector (dq, dr).

    Mirrors tactical.arcs._absolute_bearing without importing the private name.
    """
    if dq == 0 and dr == 0:
        return 0
    dx = 1.5 * dq
    dy = -(math.sqrt(3) / 2 * dq + math.sqrt(3) * dr)
    angle = math.atan2(dy, dx)
    return round((angle + math.pi / 2) / (math.pi / 3)) % 6


def _facing_toward(src: Hex, dest: Hex) -> Facing:
    """Facing that most closely points src toward dest."""
    if src == dest:
        return Facing.N
    return Facing(_absolute_bearing(dest.q - src.q, dest.r - src.r))


def _move_cost(ship: ShipState, dest: Hex, dest_facing: Facing) -> int:
    """Minimum MP needed to reach dest at dest_facing.

    Mirrors the direct-hex formula in Encounter.stage_move so the AI's
    reachability checks agree with the encounter engine.
    """
    dist = hex_distance(ship.pos, dest)
    facing_delta = (int(dest_facing) - int(ship.facing)) % 6
    turns_needed = min(facing_delta, 6 - facing_delta)
    return max(dist, turns_needed * ship.turn_cost - ship.turn_charge)


def _preferred_range(ship: ShipState) -> int:
    """Range band where this ship's weapons deal the most expected damage.

    Queries each weapon system's RangeTable directly, so new weapons
    automatically influence positioning without any hardcoding.
    """
    if ship.systems is None:
        return 5
    best_range = 5
    best_ev = -1.0
    for r in range(1, 15):
        ev = 0.0
        for sys in ship.systems:
            if not sys.is_active() or sys.base not in _WEAPON_BASES:
                continue
            try:
                spec = WEAPONS[WeaponType(sys.base)]
            except (KeyError, ValueError):
                continue
            to_hit = spec.to_hit_at(r)
            damage = spec.damage.at(r)
            if to_hit is None or damage is None:
                continue
            ev += (to_hit / 10.0) * damage
        if ev > best_ev:
            best_ev = ev
            best_range = r
    return best_range


def _generate_candidates(
    ship: ShipState,
    cap: int,
    battle: BattleState,
) -> list[tuple[Hex, Facing]]:
    """Generate candidate (dest, facing) pairs for this ship.

    Candidates are positions at or near the ship's weapon-optimal range
    from each enemy ship, with facing aimed toward that enemy.  The current
    position with all 6 possible facings is also included (so the AI can
    choose to "turn in place" if that improves arc coverage).
    """
    occupied = battle.occupied_hexes(exclude=[ship.ship_id])
    enemy_ships = [s for s in battle.ships.values() if s.owner_id != ship.owner_id]

    if not enemy_ships:
        return [(ship.pos, ship.facing)]

    pref = _preferred_range(ship)
    seen: set[tuple[int, int, int]] = set()
    candidates: list[tuple[Hex, Facing]] = []

    def _add(dest: Hex, facing: Facing) -> None:
        key = (dest.q, dest.r, int(facing))
        if key in seen:
            return
        seen.add(key)
        if dest in occupied:
            return
        cost = _move_cost(ship, dest, facing)
        if cost > cap:
            return
        candidates.append((dest, facing))

    for enemy in enemy_ships:
        target_facing = _facing_toward(ship.pos, enemy.pos)

        # Try positions at preferred range ± 2 hexes around each enemy,
        # using the six axial "ring" directions.
        for r in range(max(1, pref - 2), pref + 3):
            for dq, dr in [
                (r, 0), (-r, 0), (0, r), (0, -r), (r, -r), (-r, r),
            ]:
                dest = Hex(enemy.pos.q + dq, enemy.pos.r + dr)
                facing = _facing_toward(dest, enemy.pos)
                _add(dest, facing)

    # When the enemy is beyond weapon range, add "advance toward enemy"
    # positions: walk the greedy path up to cap steps and sample the last
    # few reachable hexes so the AI closes the gap rather than standing still.
    for enemy in enemy_ships:
        if hex_distance(ship.pos, enemy.pos) > cap:
            path = greedy_path(ship.pos, enemy.pos, cap)
            for dest in path[-3:]:
                facing = _facing_toward(dest, enemy.pos)
                _add(dest, facing)

    # Always consider turning in place (all 6 facings at current position).
    for f in range(6):
        _add(ship.pos, Facing(f))

    return candidates[:_MAX_CANDIDATES]


def _score_candidate(
    ship: ShipState,
    dest: Hex,
    facing: Facing,
    battle: BattleState,
    owner_id: str,
    profile: AIProfile,
) -> float:
    """Score a candidate position for one ship.

    Outgoing: expected damage this ship can deal from (dest, facing).
    Incoming: expected damage enemies can deal to us at dest.

    The evasion_weight controls how much the AI cares about avoiding
    incoming fire — aggressive AIs favour output over survival.

    This is also the core computation that would power a per-hex firepower
    heat map: call this with varying (dest, facing) to populate the map.
    """
    enemy_ships = [s for s in battle.ships.values() if s.owner_id != owner_id]

    outgoing = 0.0
    if ship.systems is not None:
        for enemy in enemy_ships:
            dq = enemy.pos.q - dest.q
            dr = enemy.pos.r - dest.r
            rb = relative_bearing(int(facing), dq, dr)
            if rb in REAR_BEARINGS:
                continue  # can't fire into blind spot

            dist = hex_distance(dest, enemy.pos)

            # Rear-arc bonus: are we behind the enemy?
            my_dq = dest.q - enemy.pos.q
            my_dr = dest.r - enemy.pos.r
            my_rb = relative_bearing(int(enemy.facing), my_dq, my_dr)
            arc_bonus = REAR_ARC_TO_HIT_BONUS if my_rb in REAR_BEARINGS else 0

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
                outgoing += (min(10, to_hit + arc_bonus) / 10.0) * damage * spec.rate_of_fire

    incoming = 0.0
    for enemy in enemy_ships:
        if enemy.systems is None:
            continue

        e_dq = dest.q - enemy.pos.q
        e_dr = dest.r - enemy.pos.r
        e_rb = relative_bearing(int(enemy.facing), e_dq, e_dr)
        if e_rb in REAR_BEARINGS:
            continue  # we'd be in their blind spot — they can't fire at us

        dist = hex_distance(enemy.pos, dest)

        # Rear-arc penalty: is the enemy behind us? They get a bonus.
        their_dq = enemy.pos.q - dest.q
        their_dr = enemy.pos.r - dest.r
        their_rb_from_us = relative_bearing(int(facing), their_dq, their_dr)
        arc_pen = REAR_ARC_TO_HIT_BONUS if their_rb_from_us in REAR_BEARINGS else 0

        for sys in enemy.systems:
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
            incoming += (min(10, to_hit + arc_pen) / 10.0) * damage * spec.rate_of_fire

    # Aggression scales how much the AI weights avoiding incoming fire.
    # Fully aggressive (1.0) → evasion weight = 0.7 (still considers it).
    # Fully defensive (0.0) → evasion weight = 1.0 (full cost).
    evasion_weight = 1.0 - 0.3 * profile.aggression

    # Approach bonus: when enemies are beyond weapon range the outgoing/incoming
    # terms are both zero and the score collapses to noise.  Add a small reward
    # for being close to preferred engagement range so the AI consistently
    # closes distance rather than wandering randomly.
    pref = _preferred_range(ship)
    approach = 0.0
    for enemy in enemy_ships:
        gap = max(0, hex_distance(dest, enemy.pos) - pref)
        approach -= 0.3 * profile.aggression * gap

    return outgoing - evasion_weight * incoming + approach


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def choose_move_orders(
    battle: BattleState,
    owner_id: str,
    mp_capacities: dict[ShipID, int],
    profile: AIProfile,
    rng: random.Random,
) -> dict[ShipID, tuple[Hex, Facing]]:
    """Return a (dest, facing) for each ship owned by owner_id.

    Ships with no better move than staying put are omitted from the result
    (they will receive no move order and remain in place).
    """
    orders: dict[ShipID, tuple[Hex, Facing]] = {}

    for ship_id, ship in battle.ships.items():
        if ship.owner_id != owner_id:
            continue
        cap = mp_capacities.get(ship_id, ship.mp)
        if cap == 0:
            continue

        candidates = _generate_candidates(ship, cap, battle)
        if not candidates:
            continue

        best_dest, best_facing = ship.pos, ship.facing
        best_score = -1e9

        for dest, facing in candidates:
            score = (
                _score_candidate(ship, dest, facing, battle, owner_id, profile)
                + rng.gauss(0, profile.noise)
            )
            if score > best_score:
                best_score = score
                best_dest, best_facing = dest, facing

        # Only emit an order if the chosen position differs from current.
        if best_dest == ship.pos and best_facing == ship.facing:
            continue

        orders[ship_id] = (best_dest, best_facing)

    return orders
