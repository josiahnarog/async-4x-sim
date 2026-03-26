"""Squadron-phase AI — orders for deployed fighter squadrons.

Two entry points:

  choose_launch_orders(battle, owner_id, profile, rng)
      -> list[tuple[carrier_id, squadron_id]]
      Called during the MOVE phase.  Returns which docked squadrons to launch.

  choose_squadron_orders(battle, owner_id, profile, rng)
      -> dict[SquadronID, SquadronOrder]
      Called during COMBAT_SMALL.  Returns orders for all deployed squadrons.

Squadron priority queue (highest to lowest):
  1. Recover if endurance is critically low.
  2. Intercept nearby enemy squadrons threatening our ships.
  3. Strike nearest enemy ship.
  4. Hold (no order) — stay put.
"""

from __future__ import annotations

import random

from sim.hexgrid import hex_distance
from tactical.battle_state import BattleState
from tactical.squadron_state import SquadronID
from tactical.turn_orders import InterceptOrder, RecoverOrder, StrikeOrder, SquadronOrder
from tactical.ai.profile import AIProfile



# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _best_recovery_carrier(
    sq_id: str,
    battle: BattleState,
    owner_id: str,
    recoveries_planned: dict[str, int],
) -> str | None:
    """Find the nearest friendly carrier that can accept a recovery.

    Checks:
      - has active launch bays (Bl) with capacity remaining
      - has at least one empty active hangar bay (Bh)
      - squadron can reach it within its effective MP
    """
    sq = battle.squadrons[sq_id]
    best_id: str | None = None
    best_dist = float("inf")

    for ship_id, ship in battle.ships.items():
        if ship.owner_id != owner_id or ship.systems is None:
            continue
        bl_cap = ship.systems.launch_bay_count()
        if bl_cap == 0:
            continue
        if recoveries_planned.get(ship_id, 0) >= bl_cap:
            continue
        has_empty_bh = any(
            s.is_active() and s.token == "Bh" and s.occupant is None
            for s in ship.systems
        )
        if not has_empty_bh:
            continue
        d = hex_distance(sq.pos, ship.pos)
        if d > sq.effective_mp:
            continue  # can't reach in one turn
        if d < best_dist:
            best_dist = d
            best_id = ship_id

    return best_id


def _nearest_enemy_squadron(
    sq_id: str, battle: BattleState, owner_id: str
) -> str | None:
    sq = battle.squadrons[sq_id]
    best_id: str | None = None
    best_dist = float("inf")
    for eid, esq in battle.squadrons.items():
        if esq.owner_id == owner_id or esq.is_destroyed() or not esq.is_deployed:
            continue
        d = hex_distance(sq.pos, esq.pos)
        if d < best_dist:
            best_dist = d
            best_id = eid
    return best_id


def _nearest_enemy_ship(
    sq_id: str, battle: BattleState, owner_id: str
) -> str | None:
    sq = battle.squadrons[sq_id]
    best_id: str | None = None
    best_dist = float("inf")
    for sid, ship in battle.ships.items():
        if ship.owner_id == owner_id:
            continue
        if ship.systems is not None and ship.systems.is_destroyed():
            continue
        d = hex_distance(sq.pos, ship.pos)
        if d < best_dist:
            best_dist = d
            best_id = sid
    return best_id


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def choose_launch_orders(
    battle: BattleState,
    owner_id: str,
    profile: AIProfile,
    rng: random.Random,
) -> list[tuple[str, str]]:
    """Return (carrier_id, squadron_id) pairs to launch this turn.

    Launches all docked squadrons immediately if any enemies exist.
    A tactical engagement has no safe moment to hold fighters in reserve.
    """
    has_enemies = any(
        s.owner_id != owner_id for s in battle.ships.values()
    )
    if not has_enemies:
        return []

    launches: list[tuple[str, str]] = []

    for ship_id, ship in battle.ships.items():
        if ship.owner_id != owner_id or ship.systems is None:
            continue
        bl_cap = ship.systems.launch_bay_count()
        if bl_cap == 0:
            continue

        docked = [
            sq_id
            for sq_id, sq in battle.squadrons.items()
            if not sq.is_deployed and sq.docked_at == ship_id
        ]
        for sq_id in docked[:bl_cap]:
            launches.append((ship_id, sq_id))

    return launches


def choose_squadron_orders(
    battle: BattleState,
    owner_id: str,
    profile: AIProfile,
    rng: random.Random,
) -> dict[SquadronID, SquadronOrder]:
    """Return a SquadronOrder for each deployed squadron owned by owner_id.

    Squadrons with no order hold position (absent from the returned dict).
    """
    orders: dict[SquadronID, SquadronOrder] = {}
    # Track recovery slots consumed this round so we don't exceed Bl capacity.
    recoveries_planned: dict[str, int] = {}

    for sq_id, sq in battle.squadrons.items():
        if sq.owner_id != owner_id or not sq.is_deployed or sq.is_destroyed():
            continue

        # --- Priority 1: recover if critically low on endurance ----------
        if sq.endurance <= profile.squadron_recover_threshold:
            carrier_id = _best_recovery_carrier(sq_id, battle, owner_id, recoveries_planned)
            if carrier_id is not None:
                orders[sq_id] = RecoverOrder(carrier_id=carrier_id)
                recoveries_planned[carrier_id] = recoveries_planned.get(carrier_id, 0) + 1
                continue

        # --- Priority 2: intercept nearby enemy squadrons ----------------
        enemy_sq_id = _nearest_enemy_squadron(sq_id, battle, owner_id)
        if enemy_sq_id is not None:
            enemy_sq = battle.squadrons[enemy_sq_id]
            dist = hex_distance(sq.pos, enemy_sq.pos)
            # Intercept if reachable within MP + intercept radius bonus.
            if dist <= sq.effective_mp + 1:
                orders[sq_id] = InterceptOrder(patrol_hex=sq.pos)
                continue

        # --- Priority 3: strike nearest enemy ship -----------------------
        enemy_ship_id = _nearest_enemy_ship(sq_id, battle, owner_id)
        if enemy_ship_id is not None:
            orders[sq_id] = StrikeOrder(target_id=enemy_ship_id)
            continue

        # --- Default: hold (no order) ------------------------------------

    return orders
