"""Utilities for transitioning campaign intercepts into tactical encounters."""

from __future__ import annotations

import math
import random
from typing import Optional

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.facing import Facing, FACING_OFFSETS

from campaign.models import CampaignShip, Engagement, EngagementStatus, Galaxy, MoveLeg

# ---------------------------------------------------------------------------
# Configurable battle-setup constants (change here to tune globally)
# ---------------------------------------------------------------------------

TACTICAL_SEPARATION: int = 30  # hexes between the two sides' centre lines
LATERAL_SPACING:     int = 3   # hexes between ships on the same side


# ---------------------------------------------------------------------------
# Facing helpers
# ---------------------------------------------------------------------------

def facing_from_direction(dq: int, dr: int) -> Facing:
    """Map a movement direction vector to the nearest Facing.

    Uses cosine similarity against each of the six unit hex directions.
    Returns Facing.N when the vector is zero (stationary ship).
    """
    if dq == 0 and dr == 0:
        return Facing.N
    mag = math.sqrt(dq * dq + dr * dr)
    best_f   = Facing.N
    best_cos = -2.0
    for f_val, (fq, fr) in enumerate(FACING_OFFSETS):
        f_mag = math.sqrt(fq * fq + fr * fr)
        cos_a = (dq * fq + dr * fr) / (mag * f_mag)
        if cos_a > best_cos:
            best_cos = cos_a
            best_f   = Facing(f_val)
    return best_f


def ship_facing_from_route(ship: CampaignShip) -> Facing:
    """Derive tactical facing from the ship's most recent MoveLeg direction."""
    for leg in reversed(ship.route):
        if isinstance(leg, MoveLeg):
            return facing_from_direction(
                leg.to_q - leg.from_q,
                leg.to_r - leg.from_r,
            )
    return Facing.N


# ---------------------------------------------------------------------------
# Scatter placement
# ---------------------------------------------------------------------------

def _place_side(
    ships:    list[CampaignShip],
    base_q:   int,
    base_r:   int,
    perp_dq:  int,
    perp_dr:  int,
    facing:   Facing,
) -> dict[str, tuple[Hex, Facing]]:
    """Spread ships in a lateral line centred on (base_q, base_r)."""
    result: dict[str, tuple[Hex, Facing]] = {}
    n = len(ships)
    for i, ship in enumerate(ships):
        offset = i - (n - 1) / 2        # centre the line around base
        q = round(base_q + offset * perp_dq * LATERAL_SPACING)
        r = round(base_r + offset * perp_dr * LATERAL_SPACING)
        result[ship.ship_id] = (Hex(q, r), facing)
    return result


def build_battle_positions(
    side_a:     list[CampaignShip],
    side_b:     list[CampaignShip],
    facing_a:   Facing,
    separation: int = TACTICAL_SEPARATION,
) -> dict[str, tuple[Hex, Facing]]:
    """Return {ship_id: (Hex, Facing)} placing both sides SEPARATION hexes apart.

    Side A is placed at -half along facing_a (they approach from behind), side B
    at +half facing the opposite direction.  Ships on each side are spread
    perpendicular to the direction of travel by LATERAL_SPACING hexes.
    The separation constant is intentionally exposed so callers can override it.
    """
    fq, fr     = FACING_OFFSETS[int(facing_a)]
    facing_b   = Facing((int(facing_a) + 3) % 6)
    # One step clockwise from facing_a gives the perpendicular spread direction
    perp_val   = (int(facing_a) + 1) % 6
    pq, pr     = FACING_OFFSETS[perp_val]

    half = separation // 2
    a_pos = _place_side(side_a, round(-fq * half), round(-fr * half), pq, pr, facing_a)
    b_pos = _place_side(side_b, round( fq * half), round( fr * half), pq, pr, facing_b)
    return {**a_pos, **b_pos}


# ---------------------------------------------------------------------------
# BattleState builder
# ---------------------------------------------------------------------------

def build_battle_from_engagement(
    engagement: Engagement,
    galaxy:     Galaxy,
    separation: int = TACTICAL_SEPARATION,
) -> tuple[BattleState, random.Random]:
    """Build a ready-to-start BattleState from an Engagement.

    Ships are scattered across the tactical grid at the given separation
    (default TACTICAL_SEPARATION) facing the direction they were travelling
    on the campaign map.
    """
    all_ships = {
        s.ship_id: s
        for node in galaxy.systems.values()
        for s in node.ships
    }
    eng_ships = [all_ships[sid] for sid in engagement.ship_ids if sid in all_ships]

    # Split into two sides by owner
    sides: dict[str, list[CampaignShip]] = {}
    for s in eng_ships:
        sides.setdefault(s.owner, []).append(s)

    owner_ids = list(sides.keys())
    side_a    = sides.get(owner_ids[0], [])
    side_b    = sides.get(owner_ids[1], []) if len(owner_ids) > 1 else []

    # Side A's facing drives the layout; use first ship's last MoveLeg
    facing_a  = ship_facing_from_route(side_a[0]) if side_a else Facing.N
    positions = build_battle_positions(side_a, side_b, facing_a, separation)

    ship_states = {}
    for camp_ship in eng_ships:
        hex_pos, facing = positions[camp_ship.ship_id]
        ship_states[camp_ship.ship_id] = camp_ship.instance.to_ship_state(
            ship_id=camp_ship.ship_id,
            owner_id=camp_ship.owner,
            pos=hex_pos,
            facing=facing,
        )

    return BattleState(ships=ship_states, squadrons={}), random.Random()


# ---------------------------------------------------------------------------
# Auto-resolve stub
# ---------------------------------------------------------------------------

def auto_resolve_stub(
    engagement: Engagement,
    galaxy:     Galaxy,
    rng:        random.Random,
) -> dict:
    """Coin-flip auto-resolution placeholder.

    Randomly picks a winning side; all losing ships are destroyed.
    Returns a summary dict with keys: winner, loser, destroyed, survivors.
    """
    all_ships = {
        s.ship_id: s
        for node in galaxy.systems.values()
        for s in node.ships
    }
    eng_ships = [all_ships[sid] for sid in engagement.ship_ids if sid in all_ships]

    sides: dict[str, list[CampaignShip]] = {}
    for s in eng_ships:
        sides.setdefault(s.owner, []).append(s)

    owner_ids    = list(sides.keys())
    winner_owner = rng.choice(owner_ids)
    loser_owner  = next((o for o in owner_ids if o != winner_owner), winner_owner)

    return {
        "winner":    winner_owner,
        "loser":     loser_owner,
        "destroyed": [s.ship_id for s in sides.get(loser_owner, [])],
        "survivors": [s.ship_id for s in sides.get(winner_owner, [])],
    }
