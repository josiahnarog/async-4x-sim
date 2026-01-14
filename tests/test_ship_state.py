import pytest

from sim.hexgrid import Hex
from tactical.facing import Facing
from tactical.ship_state import ShipState
from tactical.system_track import ShipSystems


def test_turn_charge_caps_and_turning_resets_charge():
    s0 = ShipState(
        ship_id="s1",
        owner_id="p1",
        pos=Hex(0, 0),
        facing=Facing.N,
        mp=10,
        turn_cost=3,
        turn_charge=0,
        systems=ShipSystems.parse("III"),
    )

    # Move 1 => charge 1
    s1 = s0.move_forward(1)
    assert (s1.pos.q, s1.pos.r) == (0, 1)
    assert s1.mp == 9
    assert s1.turn_charge == 1
    assert not s1.can_turn()

    # Spend 2 MP stationary => charge 3 => can turn
    s2 = s1.spend_mp(2)
    assert s2.mp == 7
    assert s2.turn_charge == 3
    assert s2.can_turn()

    # Turning is free but resets charge
    s3 = s2.turn_left()
    assert s3.mp == 7
    assert s3.facing == Facing.NW
    assert s3.turn_charge == 0


def test_excess_movement_does_not_accrue_past_turn_cost():
    s0 = ShipState(
        ship_id="s1",
        owner_id="p1",
        pos=Hex(0, 0),
        facing=Facing.SE,
        mp=10,
        turn_cost=3,
        turn_charge=0,
    )

    s1 = s0.move_forward(5)  # spends 5 MP
    assert s1.mp == 5
    assert s1.turn_charge == 3  # capped at turn_cost
    assert s1.can_turn()

    # Turn for free; charge resets to 0
    s2 = s1.turn_right()
    assert s2.mp == 5
    assert s2.turn_charge == 0


def test_cannot_turn_without_full_charge():
    s0 = ShipState(
        ship_id="s1",
        owner_id="p1",
        pos=Hex(0, 0),
        facing=Facing.N,
        mp=3,
        turn_cost=3,
        turn_charge=2,
    )
    with pytest.raises(ValueError):
        s0.turn_left()


def test_spend_mp_and_move_validate_resources():
    s0 = ShipState(
        ship_id="s1",
        owner_id="p1",
        pos=Hex(0, 0),
        facing=Facing.NE,
        mp=1,
        turn_cost=2,
        turn_charge=0,
    )

    with pytest.raises(ValueError):
        s0.spend_mp(2)

    with pytest.raises(ValueError):
        s0.move_forward(2)
