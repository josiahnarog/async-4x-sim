"""Fleet arrangement: place ships on the hex grid for scenario initialisation.

Ships within each fleet are arranged in rings (heaviest first, by installed HS),
with random position within each ring for jitter.  All ships face the nearest
cardinal direction toward the enemy fleet centre.

Carriers (hull_mods contains "carrier") receive one docked F1 squadron per
active Bh bay, using a default gun-armed loadout.
"""
from __future__ import annotations

import random

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.facing import Facing, FACING_OFFSETS
from tactical.fighter_class import F1
from tactical.hull_types import HULL_TYPES
from tactical.ship_catalog import track_to_system_string
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems
from tactical.squadron_state import FighterLoadout, SquadronState
from tactical.weapons import WeaponType


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _facing_toward(src: Hex, dst: Hex) -> Facing:
    """Return the cardinal Facing that best points from src toward dst."""
    dq = dst.q - src.q
    dr = dst.r - src.r
    if dq == 0 and dr == 0:
        return Facing.N
    best, best_dot = Facing.N, float("-inf")
    for i, (fq, fr) in enumerate(FACING_OFFSETS):
        dot = dq * fq + dr * fr
        if dot > best_dot:
            best_dot = dot
            best = Facing(i)
    return best


def _hex_ring(center: Hex, radius: int) -> list[Hex]:
    """Return all hexes exactly `radius` steps from center."""
    if radius == 0:
        return [center]
    results: list[Hex] = []
    q = center.q + FACING_OFFSETS[4][0] * radius  # start at SW corner
    r = center.r + FACING_OFFSETS[4][1] * radius
    for i in range(6):
        dq, dr = FACING_OFFSETS[i]
        for _ in range(radius):
            results.append(Hex(q, r))
            q += dq
            r += dr
    return results


def _build_hex_pool(center: Hex, n: int, rng: random.Random) -> list[Hex]:
    """Return at least n hexes spiralling outward from center, ring order randomised."""
    pool: list[Hex] = []
    ring = 0
    while len(pool) < n:
        ring_hexes = _hex_ring(center, ring)
        rng.shuffle(ring_hexes)
        pool.extend(ring_hexes)
        ring += 1
    return pool


# ---------------------------------------------------------------------------
# Ship construction from design dict
# ---------------------------------------------------------------------------

def _design_to_ship(
    design: dict,
    ship_id: str,
    owner_id: str,
    pos: Hex,
    facing: Facing,
) -> ShipState | None:
    """Build a ShipState from a saved design dict.  Returns None if hull unknown."""
    hull_desig = design.get("hull_type", "")
    hull_type  = HULL_TYPES.get(hull_desig)
    if hull_type is None:
        return None
    sys_str = track_to_system_string(design.get("track", [])) or "S"
    systems  = ShipSystems.parse(sys_str)
    return ShipState(
        ship_id=ship_id,
        owner_id=owner_id,
        pos=pos,
        facing=facing,
        mp=hull_type.max_speed,
        turn_cost=hull_type.turn_cost,
        turn_charge=0,
        systems=systems,
        hull_type=hull_type,
    )


# ---------------------------------------------------------------------------
# Single-fleet placement
# ---------------------------------------------------------------------------

def _place_fleet(
    designs: list[dict],
    center: Hex,
    facing: Facing,
    side_id: str,
    rng: random.Random,
) -> tuple[dict[str, ShipState], dict[str, SquadronState]]:
    """Place one fleet's ships around center and generate carrier squadrons."""
    sorted_designs = sorted(
        designs, key=lambda d: d.get("hull_spaces", 0), reverse=True
    )
    hex_pool = _build_hex_pool(center, len(sorted_designs), rng)

    ships:    dict[str, ShipState]    = {}
    squadrons: dict[str, SquadronState] = {}
    sq_counter = 1

    for i, design in enumerate(sorted_designs):
        ship_num = i + 1
        ship_id  = f"{side_id}{ship_num}"
        ship = _design_to_ship(design, ship_id, side_id, hex_pool[i], facing)
        if ship is None:
            continue

        # Dock one squadron per active Bh bay (carriers only).
        # Internal weapon is read from the design track's Bh slot; defaults to GUN.
        is_carrier = "carrier" in design.get("hull_mods", [])
        if is_carrier:
            # Build an ordered list of squadron configs from the design track.
            # Build ordered lists of internal configs and external ordnance per Bh slot.
            bh_configs: list[dict] = [
                slot.get("squadron") or {}
                for slot in design.get("track", [])
                if isinstance(slot, dict)
                and slot.get("type") == "system"
                and slot.get("code") == "Bh"
            ]
            bh_ordnance: list = design.get("bh_ordnance") or []
            config_iter  = iter(bh_configs)
            ord_iter     = iter(bh_ordnance)

            import dataclasses
            updated_systems = ship.systems
            for sys in ship.systems.systems:
                if sys.token == "Bh" and sys.is_active() and sys.occupant is None:
                    config = next(config_iter, {})
                    ord_code = next(ord_iter, None)

                    # Internal weapon from design track
                    internal_code = config.get("internal") or None
                    try:
                        internal_wt = WeaponType(internal_code) if internal_code else WeaponType.GUN
                    except ValueError:
                        internal_wt = WeaponType.GUN

                    # External ordnance from scenario selection (F1 has 2 external mounts)
                    if ord_code:
                        try:
                            ext_wt   = WeaponType(ord_code)
                            external = (ext_wt, ext_wt)
                            ext_shots = 2
                        except ValueError:
                            external  = ()
                            ext_shots = 0
                    else:
                        external  = ()
                        ext_shots = 0

                    sq_id = f"{side_id}F{sq_counter}"
                    sq_counter += 1
                    sq = SquadronState(
                        squadron_id=sq_id,
                        owner_id=side_id,
                        pos=hex_pool[i],
                        strength=5, max_strength=5,
                        loadout=FighterLoadout(
                            fighter_class=F1,
                            internal=(internal_wt,),
                            external=external,
                            external_shots_remaining=ext_shots,
                        ),
                        endurance=20, max_endurance=20,
                        docked_at=ship_id,
                    )
                    updated_systems = updated_systems.dock_squadron(sq_id)
                    squadrons[sq_id] = sq

            ship = dataclasses.replace(ship, systems=updated_systems)

        ships[ship_id] = ship

    return ships, squadrons


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def arrange_fleets(
    side_a_designs: list[dict],
    side_b_designs: list[dict],
    distance: int,
    seed: int | None = None,
) -> tuple[BattleState, random.Random, int]:
    """
    Arrange two fleets on the hex grid and return a ready-to-start BattleState.

    Fleet A is centred at Hex(0, 0); fleet B at Hex(distance, 0).
    Ships are placed in rings (heaviest first), with random position within
    each ring.  All ships face the nearest cardinal direction toward the enemy.

    Parameters
    ----------
    side_a_designs, side_b_designs:
        Lists of design dicts as returned by load_design() / list_designs().
        Each dict must include "hull_type", "hull_spaces", "track", "hull_mods".
    distance:
        Hex distance between the two fleet centres (5–100).
    seed:
        RNG seed for reproducibility.  A random seed is chosen if None.

    Returns
    -------
    (battle_state, rng, seed_used)
    """
    if seed is None:
        seed = random.randrange(2 ** 32)

    rng = random.Random(seed)

    center_a = Hex(0, 0)
    center_b = Hex(distance, 0)

    facing_a = _facing_toward(center_a, center_b)
    facing_b = _facing_toward(center_b, center_a)

    ships_a, sqs_a = _place_fleet(side_a_designs, center_a, facing_a, "A", rng)
    ships_b, sqs_b = _place_fleet(side_b_designs, center_b, facing_b, "B", rng)

    battle = BattleState(
        ships={**ships_a, **ships_b},
        squadrons={**sqs_a, **sqs_b},
    )
    return battle, rng, seed
