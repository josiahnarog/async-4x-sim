import random
import pytest

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.encounter import Encounter, Phase
from tactical.facing import Facing
from tactical.ship_state import ShipState


def test_initiative_roll_deterministic_ordering_with_seed():
    # seed controls initiative rolls
    rng = random.Random(123)

    a1 = ShipState(ship_id="a1", owner_id="A", pos=Hex(0, 0), facing=Facing.N, mp=6, turn_cost=3)
    b1 = ShipState(ship_id="b1", owner_id="B", pos=Hex(2, 0), facing=Facing.S, mp=6, turn_cost=3)
    battle = BattleState(ships={"a1": a1, "b1": b1})

    enc = Encounter.start(battle, rng=rng, movement_subphases=3)

    # Ensure we got rolls for both sides, in 1..10
    assert set(enc.initiative.rolls.keys()) == {"A", "B"}
    assert 1 <= enc.initiative.rolls["A"] <= 10
    assert 1 <= enc.initiative.rolls["B"] <= 10

    lo_hi = enc.initiative.order_low_to_high()
    hi_lo = enc.initiative.order_high_to_low()
    assert lo_hi == list(reversed(hi_lo))


def test_movement_subphase_requires_minimum_spend_per_ship():
    # Force deterministic initiative ordering by bypassing randomness:
    # We'll seed so that (roll, side_id) makes A active first or second deterministically,
    # but for this test we just query active_side() at runtime and comply.
    rng = random.Random(1)

    a1 = ShipState(ship_id="a1", owner_id="A", pos=Hex(0, 0), facing=Facing.N, mp=5, turn_cost=3)
    b1 = ShipState(ship_id="b1", owner_id="B", pos=Hex(5, 0), facing=Facing.S, mp=5, turn_cost=3)
    battle = BattleState(ships={"a1": a1, "b1": b1})

    enc = Encounter.start(battle, rng=rng, movement_subphases=3)
    assert enc.phase == Phase.MOVEMENT

    # required spend is ceil(5/3)=2 per subphase
    assert enc.required_spend_this_subphase("a1") == 2

    active = enc.active_side()
    ships = enc.ships_for_side(active)
    # Spend only 1 MP on the active side's ship => should fail end_side_movement
    enc2 = enc.spend_mp(active, ships[0], 1)
    with pytest.raises(ValueError):
        enc2.end_side_movement(active)

    # Spend one more MP => now can end side movement
    enc3 = enc2.spend_mp(active, ships[0], 1)
    enc4 = enc3.end_side_movement(active)
    assert enc4.phase == Phase.MOVEMENT


def test_movement_advances_subphases_and_then_enters_combat_large():
    rng = random.Random(2)

    a1 = ShipState(ship_id="a1", owner_id="A", pos=Hex(0, 0), facing=Facing.N, mp=3, turn_cost=3)
    b1 = ShipState(ship_id="b1", owner_id="B", pos=Hex(10, 0), facing=Facing.S, mp=3, turn_cost=3)
    battle = BattleState(ships={"a1": a1, "b1": b1})

    enc = Encounter.start(battle, rng=rng, movement_subphases=3)

    # required spend ceil(3/3)=1 each subphase
    assert enc.required_spend_this_subphase("a1") == 1

    for sub in range(3):
        # For each subphase, both sides must spend 1 MP on each ship.
        # We'll iterate sides in the encounter's active order.
        for _ in range(len(enc.movement_side_order())):
            side = enc.active_side()
            sid = enc.ships_for_side(side)[0]
            enc = enc.spend_mp(side, sid, 1)
            enc = enc.end_side_movement(side)
        assert enc.movement_subphase_index == min(sub + 1, 2) or enc.phase != Phase.MOVEMENT

    assert enc.phase == Phase.COMBAT_LARGE


def test_combat_large_turn_order_high_to_low_and_pass_spends_unit():
    rng = random.Random(3)

    # two ships, one per side
    a1 = ShipState(ship_id="a1", owner_id="A", pos=Hex(0, 0), facing=Facing.N, mp=3, turn_cost=3)
    b1 = ShipState(ship_id="b1", owner_id="B", pos=Hex(10, 0), facing=Facing.S, mp=3, turn_cost=3)
    battle = BattleState(ships={"a1": a1, "b1": b1})
    enc = Encounter.start(battle, rng=rng, movement_subphases=1)

    # Complete movement quickly by spending required mp=ceil(3/1)=3 for each ship
    # Side-by-side in active order
    for _ in range(len(enc.movement_side_order())):
        side = enc.active_side()
        sid = enc.ships_for_side(side)[0]
        enc = enc.spend_mp(side, sid, 3)
        enc = enc.end_side_movement(side)

    assert enc.phase == Phase.COMBAT_LARGE

    # active combat side is highest initiative
    active = enc.active_large_combat_side()
    sid = enc.ships_for_side(active)[0]

    # pass consumes that unit
    enc2 = enc.pass_fire(active, sid)
    assert sid in enc2.spent_to_fire

    # advance to next side
    enc3 = enc2.advance_combat_turn()
    active2 = enc3.active_large_combat_side()
    sid2 = enc3.ships_for_side(active2)[0]
    enc4 = enc3.choose_unit_to_fire(active2, sid2)

    # End of cycle -> all ships spent -> COMBAT_SMALL
    enc5 = enc4.advance_combat_turn()
    assert enc5.phase == Phase.COMBAT_SMALL
