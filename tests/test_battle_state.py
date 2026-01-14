import pytest

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.facing import Facing
from tactical.ship_state import ShipState


def test_battle_state_enforces_destination_not_occupied_but_allows_pass_through():
    # Facing.N now means (dq,dr) = (0,+1), i.e. "up" on the printed grid.
    s1 = ShipState(ship_id="a", owner_id="p1", pos=Hex(0, 0), facing=Facing.N, mp=10, turn_cost=3)
    s2 = ShipState(ship_id="b", owner_id="p2", pos=Hex(0, 1), facing=Facing.S, mp=10, turn_cost=3)

    b0 = BattleState(ships={"a": s1, "b": s2})

    # a moving 2 passes through (0,1) occupied by b, ends at (0,2) => allowed
    b1 = b0.move_ship_forward("a", steps=2)
    assert (b1.ships["a"].pos.q, b1.ships["a"].pos.r) == (0, 2)

    # a moving 1 would end at (0,1) => blocked
    with pytest.raises(ValueError):
        b0.move_ship_forward("a", steps=1)


def test_ship_ordering_is_deterministic():
    # Ordering: by (q, r, ship_id)
    s_b = ShipState(ship_id="b", owner_id="p1", pos=Hex(0, 0), facing=Facing.N, mp=1, turn_cost=1)
    s_a = ShipState(ship_id="a", owner_id="p2", pos=Hex(0, 0), facing=Facing.S, mp=10, turn_cost=3)
    s_c = ShipState(ship_id="c", owner_id="p1", pos=Hex(-1, 0), facing=Facing.N, mp=1, turn_cost=1)

    b = BattleState(ships={"b": s_b, "a": s_a, "c": s_c})
    assert b.ship_ids_sorted() == ["c", "a", "b"]
