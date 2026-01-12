import pytest

from sim.hexgrid import Hex
from tactical.facing import Facing
from tactical.ship_state import ShipState


def test_can_pass_through_occupied_hex_but_cannot_end_in_one():
    ship = ShipState(
        ship_id="s1",
        owner_id="p1",
        pos=Hex(0, 0),
        facing=Facing.N,
        mp=10,
        turn_cost=3,
        turn_charge=0,
    )

    occupied = {Hex(1, 0)}  # directly in front

    # steps=2 passes through (1,0) but ends at (2,0) => allowed
    ship2 = ship.move_forward(2, occupied=occupied)
    assert (ship2.pos.q, ship2.pos.r) == (2, 0)
    assert ship2.mp == 8
    assert ship2.turn_charge == 2

    # steps=1 ends at (1,0) => not allowed
    with pytest.raises(ValueError):
        ship.move_forward(1, occupied=occupied)


def test_destination_occupied_blocks_even_if_not_adjacent():
    ship = ShipState(
        ship_id="s1",
        owner_id="p1",
        pos=Hex(0, 0),
        facing=Facing.N,
        mp=10,
        turn_cost=3,
        turn_charge=0,
    )

    occupied = {Hex(3, 0)}

    # moving 3 would land on occupied destination => blocked
    with pytest.raises(ValueError):
        ship.move_forward(3, occupied=occupied)
