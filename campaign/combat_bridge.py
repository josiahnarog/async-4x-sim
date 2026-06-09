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

TACTICAL_SEPARATION: int = 30  # hexes — fastest ship starts at SEPARATION//2 from centre
LATERAL_SPACING:     int = 3   # hexes between ships on the same side
MIN_ENEMY_SEPARATION: int = 6  # minimum hexes enforced between ships on opposing sides


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
    """Derive tactical facing from the ship's most recent MoveLeg direction.

    The campaign SVG renderer uses y = +sqrt(3)*r (y-down), while the tactical
    canvas renderer uses y = -sqrt(3)*r (y-up).  Negating dr converts a campaign
    movement vector to the equivalent visual direction in the tactical coordinate
    system.
    """
    for leg in reversed(ship.route):
        if isinstance(leg, MoveLeg):
            return facing_from_direction(
                leg.to_q - leg.from_q,
                -(leg.to_r - leg.from_r),   # r-axis is flipped between SVG and canvas
            )
    return Facing.N


# ---------------------------------------------------------------------------
# Trajectory-based placement
# ---------------------------------------------------------------------------

def _hex_dist(qa: int, ra: int, qb: int, rb: int) -> int:
    dq, dr = qa - qb, ra - rb
    return max(abs(dq), abs(dr), abs(dq + dr))


def _deconflict(
    result: dict[str, tuple[Hex, Facing]],
    sides:  dict[str, list[CampaignShip]],
) -> None:
    """Push apart any ships from different sides that are too close.

    Triggered only when same-direction ships land at the same (or near)
    hex due to equal speeds.  Uses intercept_target to identify pursuer vs
    leader; falls back to a symmetric nudge when neither side is chasing.
    """
    side_list = list(sides.items())
    for i in range(len(side_list)):
        for j in range(i + 1, len(side_list)):
            for sa in side_list[i][1]:
                for sb in side_list[j][1]:
                    ha, fa = result[sa.ship_id]
                    hb, fb = result[sb.ship_id]
                    dist = _hex_dist(ha.q, ha.r, hb.q, hb.r)
                    if dist >= MIN_ENEMY_SEPARATION:
                        continue

                    # Determine pursuer (the one whose intercept_target is the other)
                    if sa.intercept_target == sb.ship_id:
                        pursuer, leader = sa, sb
                    elif sb.intercept_target == sa.ship_id:
                        pursuer, leader = sb, sa
                    else:
                        # Symmetric nudge: push each apart along sa's facing
                        fq, fr = FACING_OFFSETS[int(fa)]
                        nudge = (MIN_ENEMY_SEPARATION - dist) // 2 + 1
                        result[sa.ship_id] = (Hex(ha.q - fq * nudge, ha.r - fr * nudge), fa)
                        result[sb.ship_id] = (Hex(hb.q + fq * nudge, hb.r + fr * nudge), fb)
                        continue

                    # Pursuer retreats along its own facing; leader stays
                    ph, pf = result[pursuer.ship_id]
                    fq, fr = FACING_OFFSETS[int(pf)]
                    nudge = MIN_ENEMY_SEPARATION - dist + 2
                    result[pursuer.ship_id] = (Hex(ph.q - fq * nudge, ph.r - fr * nudge), pf)


def build_battle_positions(
    sides:      dict[str, list[CampaignShip]],
    separation: int = TACTICAL_SEPARATION,
) -> dict[str, tuple[Hex, Facing]]:
    """Return {ship_id: (Hex, Facing)} placing ships from their strategic trajectories.

    Each ship is placed at distance  d = speed × T  from the tactical map origin,
    offset *opposite* to its heading, so all ships converge on the origin
    simultaneously if they hold course.

    T is chosen so that the fastest ship starts exactly  separation // 2  hexes
    from the origin; slower ships start proportionally closer.

      - Head-on:  ships approach from opposite sides, arrive at centre together.
      - Oblique:  each enters from its own edge, trajectories cross near centre.
      - Pursuit:  both face the same direction; the faster pursuer starts further
                  back, the slower leader is already closer to centre.

    Ships on the same side are spread laterally (perpendicular to that side's
    dominant facing) to avoid stacking.  A final deconfliction pass separates
    any ships from opposing sides that would otherwise overlap (rare same-speed
    pursuit case).
    """
    half = separation // 2

    all_ships = [s for ships in sides.values() for s in ships]
    if not all_ships:
        return {}

    max_speed = max((s.instance.active_speed for s in all_ships), default=1) or 1
    T = half / max_speed  # turns until the fastest ship would reach the origin

    result: dict[str, tuple[Hex, Facing]] = {}

    for ships in sides.values():
        if not ships:
            continue

        # Dominant facing for this side — used only for the lateral spread axis
        dominant_facing = ship_facing_from_route(ships[0])
        perp_idx = (int(dominant_facing) + 1) % 6
        pq, pr   = FACING_OFFSETS[perp_idx]

        n = len(ships)
        for i, ship in enumerate(ships):
            # Each ship gets its own facing and depth from the origin
            facing = ship_facing_from_route(ship)
            fq, fr = FACING_OFFSETS[int(facing)]
            speed  = ship.instance.active_speed or 1
            d      = speed * T          # hexes from origin along approach vector

            # Place behind the origin (opposite of facing = the direction they came from)
            base_q = round(-fq * d)
            base_r = round(-fr * d)

            # Spread laterally around the side's base position
            lateral = i - (n - 1) / 2
            q = round(base_q + lateral * pq * LATERAL_SPACING)
            r = round(base_r + lateral * pr * LATERAL_SPACING)

            result[ship.ship_id] = (Hex(q, r), facing)

    _deconflict(result, sides)
    return result


# ---------------------------------------------------------------------------
# BattleState builder
# ---------------------------------------------------------------------------

def build_battle_from_engagement(
    engagement: Engagement,
    galaxy:     Galaxy,
    separation: int = TACTICAL_SEPARATION,
) -> tuple[BattleState, random.Random]:
    """Build a ready-to-start BattleState from an Engagement.

    Ships are placed according to their strategic heading and speed so that
    their projected paths converge near the tactical map origin.
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

    positions = build_battle_positions(sides, separation)

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
