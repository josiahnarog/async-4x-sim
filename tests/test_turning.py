import random
import pytest

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.encounter import Encounter, Phase
from tactical.facing import Facing
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems


def test_turning_requires_full_charge_and_resets_charge():
    rng = random.Random(1)

    # track=III => capacity=3 MP per movement subphase refresh
    ship = ShipState(
        ship_id="A1",
        owner_id="A",
        pos=Hex(0, 0),
        facing=Facing.N,
        mp=3,
        turn_cost=3,
        turn_charge=0,
        systems=ShipSystems.parse("III"),
    )
    battle = BattleState(ships={"A1": ship})
    enc = Encounter.start(battle, rng=rng, movement_subphases=3)

    assert enc.phase == Phase.MOVEMENT
    side = enc.active_side()

    # Not enough charge -> cannot turn
    with pytest.raises(ValueError):
        enc.turn_ship_left(side, "A1")

    # Spend MP to charge; turning is free but gated
    enc2 = enc.spend_mp(side, "A1", 3)
    assert enc2.battle.ships["A1"].turn_charge == 3

    enc3 = enc2.turn_ship_left(side, "A1")
    s3 = enc3.battle.ships["A1"]
    assert s3.facing == Facing.NW
    assert s3.turn_charge == 0


def test_turning_does_not_count_as_mp_spent_for_subphase_requirement():
    rng = random.Random(1)
    ship = ShipState(
        ship_id="A1",
        owner_id="A",
        pos=Hex(0, 0),
        facing=Facing.N,
        mp=3,
        turn_cost=3,
        turn_charge=3,  # already charged
        systems=ShipSystems.parse("III"),
    )
    battle = BattleState(ships={"A1": ship})
    enc = Encounter.start(battle, rng=rng, movement_subphases=3)

    side = enc.active_side()

    # Turn (free) - should not increase mp_spent_this_subphase
    enc2 = enc.turn_ship_right(side, "A1")
    assert enc2.spent_this_subphase("A1") == 0
    assert enc2.battle.ships["A1"].turn_charge == 0


def test_auto_turn_spends_missing_mp_then_turns_and_counts_as_spend():
    rng = random.Random(1)
    ship = ShipState(
        ship_id="A1",
        owner_id="A",
        pos=Hex(0, 0),
        facing=Facing.N,
        mp=3,
        turn_cost=3,
        turn_charge=1,
        systems=ShipSystems.parse("III"),
    )
    battle = BattleState(ships={"A1": ship})
    enc = Encounter.start(battle, rng=rng, movement_subphases=3)
    side = enc.active_side()

    # Ensure we have partial charge (Encounter.start refreshes mp but preserves charge)
    assert enc.battle.ships["A1"].turn_charge == 1

    enc2 = enc.turn_ship_left(side, "A1", auto_spend=True)
    s2 = enc2.battle.ships["A1"]

    assert s2.facing == Facing.NW
    assert s2.turn_charge == 0
    # Spent missing=2 mp to charge
    assert enc2.spent_this_subphase("A1") == 2
