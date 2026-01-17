import random

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.combat import resolve_large_fire
from tactical.facing import Facing
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems
from tactical.weapons import WeaponType


def test_standard_missile_uses_pd_and_reports_fields():
    rng = random.Random(0)

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
        pos=Hex(0, 1),
        facing=Facing.S,
        mp=0,
        turn_cost=3,
        turn_charge=0,
        systems=ShipSystems.parse("DDSH"),
    )

    battle = BattleState(ships={"A1": attacker, "B1": target})

    _b2, ev = resolve_large_fire(
        battle,
        attacker_id="A1",
        target_id="B1",
        weapon=WeaponType.STANDARD_MISSILE,
        rng=rng,
    )

    assert ev.missile_hits is not None
    assert ev.pd_intercepted is not None
    assert ev.remaining_hits is not None
    assert ev.remaining_hits == ev.raw_damage
    assert ev.missile_hits >= ev.pd_intercepted
    assert ev.remaining_hits == ev.missile_hits - ev.pd_intercepted


def test_missiles_can_overwhelm_pd_capacity():
    rng = random.Random(1)

    attacker = ShipState(
        ship_id="A1",
        owner_id="A",
        pos=Hex(0, 0),
        facing=Facing.N,
        mp=0,
        turn_cost=3,
        turn_charge=0,
        systems=ShipSystems.parse("RRRR"),
    )

    target = ShipState(
        ship_id="B1",
        owner_id="B",
        pos=Hex(0, 1),
        facing=Facing.S,
        mp=0,
        turn_cost=3,
        turn_charge=0,
        systems=ShipSystems.parse("D"),
    )

    battle = BattleState(ships={"A1": attacker, "B1": target})

    _b2, ev = resolve_large_fire(
        battle,
        attacker_id="A1",
        target_id="B1",
        weapon=WeaponType.STANDARD_MISSILE,
        rng=rng,
    )

    assert ev.missile_hits is not None
    assert ev.pd_intercepted is not None
    assert ev.remaining_hits == ev.missile_hits - ev.pd_intercepted