import pytest

from sim.hexgrid import Hex
from tactical.activation import TacticalTurn
from tactical.battle_state import BattleState
from tactical.facing import Facing
from tactical.ship_state import ShipState


def test_activation_order_is_deterministic_and_advances_rounds():
    s1 = ShipState(ship_id="b", owner_id="p1", pos=Hex(0, 0), facing=Facing.N, mp=10, turn_cost=3)
    s2 = ShipState(ship_id="a", owner_id="p1", pos=Hex(0, 0), facing=Facing.N, mp=10, turn_cost=3)
    s3 = ShipState(ship_id="c", owner_id="p1", pos=Hex(-1, 0), facing=Facing.N, mp=10, turn_cost=3)

    battle = BattleState(ships={"b": s1, "a": s2, "c": s3})
    turn = TacticalTurn.start(battle)

    # Sorted by (q, r, ship_id): c at (-1,0) then a then b
    assert turn.active_ship_id() == "c"
    assert turn.activation.round_no == 1

    turn2 = turn.end_activation("c")
    assert turn2.active_ship_id() == "a"
    assert turn2.activation.round_no == 1

    turn3 = turn2.end_activation("a")
    assert turn3.active_ship_id() == "b"
    assert turn3.activation.round_no == 1

    # End last ship -> new round
    turn4 = turn3.end_activation("b")
    assert turn4.active_ship_id() == "c"
    assert turn4.activation.round_no == 2


def test_only_active_ship_may_act():
    s1 = ShipState(ship_id="a", owner_id="p1", pos=Hex(0, 0), facing=Facing.N, mp=10, turn_cost=3)
    s2 = ShipState(ship_id="b", owner_id="p2", pos=Hex(2, 0), facing=Facing.S, mp=10, turn_cost=3)

    battle = BattleState(ships={"a": s1, "b": s2})
    turn = TacticalTurn.start(battle)

    assert turn.active_ship_id() == "a"

    # Non-active ship can't move or end activation
    with pytest.raises(PermissionError):
        turn.move_active_ship_forward("b", steps=1)

    with pytest.raises(PermissionError):
        turn.end_activation("b")

    # Active ship can move
    turn2 = turn.move_active_ship_forward("a", steps=1)
    assert (turn2.battle.ships["a"].pos.q, turn2.battle.ships["a"].pos.r) == (0, 1)

    # Still active until end_activation is called
    assert turn2.active_ship_id() == "a"
    turn3 = turn2.end_activation("a")
    assert turn3.active_ship_id() == "b"
