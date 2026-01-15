import random

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.combat import resolve_large_fire
from tactical.facing import Facing
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems
from tactical.weapons import WeaponType, WEAPONS


def test_range_table_allows_dash_to_mean_cannot_hit():
    spec = WEAPONS[WeaponType.STANDARD_MISSILE]
    # At range 18 (0-indexed table entry 18) and beyond, cannot hit.
    assert spec.to_hit_at(18) is None
    assert spec.to_hit_at(50) is None


def test_standard_missile_never_hits_beyond_cutoff():
    rng = random.Random(1)

    attacker = ShipState(
        ship_id="A1",
        owner_id="A",
        pos=Hex(0, 0),
        facing=Facing.N,
        mp=0,
        turn_cost=3,
        turn_charge=0,
        systems=ShipSystems.parse("R"),
    )
    target = ShipState(
        ship_id="B1",
        owner_id="B",
        pos=Hex(0, 20),
        facing=Facing.S,
        mp=0,
        turn_cost=3,
        turn_charge=0,
        systems=ShipSystems.parse("SS"),
    )

    b0 = BattleState(ships={"A1": attacker, "B1": target})
