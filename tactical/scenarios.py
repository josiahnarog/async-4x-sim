"""Canned battle scenarios for development and playtesting.

Each function returns a (BattleState, random.Random) pair ready to pass to
Encounter.start().  Both the REPL and the web UI import from here so the
scenario definitions stay in sync.
"""
from __future__ import annotations

import random

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.facing import Facing
from tactical.hull_types import FG
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems
from tactical.squadron_state import FighterLoadout, SquadronState
from tactical.weapons import WeaponType


def default_scenario(seed: int = 1) -> tuple[BattleState, random.Random]:
    """Two frigates with four fighter squadrons for development playtesting."""
    rng = random.Random(seed)

    fg_systems = "SSSSSAAAAA(I)FFRRD(I)(I)(I)"
    a = ShipState(
        ship_id="A1", owner_id="A", pos=Hex(0, 0), facing=Facing.NE,
        mp=5, turn_cost=2, turn_charge=0,
        systems=ShipSystems.parse(fg_systems), hull_type=FG,
    )
    b = ShipState(
        ship_id="B1", owner_id="B", pos=Hex(6, 0), facing=Facing.S,
        mp=5, turn_cost=2, turn_charge=0,
        systems=ShipSystems.parse(fg_systems), hull_type=FG,
    )

    # A's squadrons
    af1 = SquadronState(          # interceptors: high MVR, gun-armed
        squadron_id="AF1", owner_id="A", pos=Hex(1, 0),
        strength=5, max_strength=5,
        loadout=FighterLoadout(base_mvr=4, base_mp=10,
                               internal=(WeaponType.GUN,)),
        endurance=20, max_endurance=20,
    )
    af2 = SquadronState(          # strike fighters: laser + missiles
        squadron_id="AF2", owner_id="A", pos=Hex(0, 1),
        strength=5, max_strength=5,
        loadout=FighterLoadout(base_mvr=3, base_mp=8,
                               internal=(WeaponType.LASER,),
                               external=(WeaponType.STANDARD_MISSILE,),
                               external_shots_remaining=2),
        endurance=20, max_endurance=20,
    )

    # B's squadrons
    bf1 = SquadronState(          # interceptors: high MVR, laser-armed
        squadron_id="BF1", owner_id="B", pos=Hex(5, 0),
        strength=5, max_strength=5,
        loadout=FighterLoadout(base_mvr=4, base_mp=10,
                               internal=(WeaponType.LASER,)),
        endurance=0, max_endurance=20,
    )
    bf2 = SquadronState(          # strike fighters: laser + missiles
        squadron_id="BF2", owner_id="B", pos=Hex(6, 1),
        strength=5, max_strength=5,
        loadout=FighterLoadout(base_mvr=3, base_mp=8,
                               internal=(WeaponType.LASER,),
                               external=(WeaponType.STANDARD_MISSILE,),
                               external_shots_remaining=2),
        endurance=20, max_endurance=20,
    )

    battle = BattleState(
        ships={"A1": a, "B1": b},
        squadrons={"AF1": af1, "AF2": af2, "BF1": bf1, "BF2": bf2},
    )
    return battle, rng
