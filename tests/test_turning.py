"""Tests for ship turning mechanics (ShipState level).

Turn model:
  - Moving/spending MP accumulates turn_charge, capped at turn_cost.
  - Turning is free once turn_charge == turn_cost, and resets charge to 0.
  - turn_left_auto / turn_right_auto auto-spends missing MP then turns.
"""
import pytest

from sim.hexgrid import Hex
from tactical.facing import Facing
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems


def _ship(turn_charge: int = 0, mp: int = 3, turn_cost: int = 3) -> ShipState:
    return ShipState(
        ship_id="A1",
        owner_id="A",
        pos=Hex(0, 0),
        facing=Facing.N,
        mp=mp,
        turn_cost=turn_cost,
        turn_charge=turn_charge,
        systems=ShipSystems.parse("III"),
    )


def test_turning_requires_full_charge():
    ship = _ship(turn_charge=0, mp=3, turn_cost=3)
    with pytest.raises(ValueError):
        ship.turn_left()
    with pytest.raises(ValueError):
        ship.turn_right()


def test_turning_possible_at_full_charge():
    ship = _ship(turn_charge=3, mp=3, turn_cost=3)
    turned = ship.turn_left()
    assert turned.facing == Facing.NW
    assert turned.turn_charge == 0


def test_turning_right():
    ship = _ship(turn_charge=3, mp=3, turn_cost=3)
    turned = ship.turn_right()
    assert turned.facing == Facing.NE
    assert turned.turn_charge == 0


def test_spending_mp_charges_turn():
    ship = _ship(turn_charge=0, mp=3, turn_cost=3)
    ship2 = ship.spend_mp(3)
    assert ship2.turn_charge == 3
    assert ship2.mp == 0

    turned = ship2.turn_left()
    assert turned.facing == Facing.NW
    assert turned.turn_charge == 0


def test_turning_does_not_cost_mp():
    ship = _ship(turn_charge=3, mp=3, turn_cost=3)
    turned = ship.turn_right()
    assert turned.mp == 3  # mp unchanged


def test_auto_turn_spends_missing_mp_then_turns():
    ship = _ship(turn_charge=1, mp=3, turn_cost=3)
    # Missing 2 MP to reach full charge
    turned = ship.turn_left_auto()
    assert turned.facing == Facing.NW
    assert turned.turn_charge == 0
    assert turned.mp == 1  # 3 - 2 spent to charge


def test_auto_turn_does_nothing_extra_when_already_charged():
    ship = _ship(turn_charge=3, mp=3, turn_cost=3)
    turned = ship.turn_right_auto()
    assert turned.facing == Facing.NE
    assert turned.mp == 3  # no extra spend


def test_auto_turn_fails_when_insufficient_mp():
    ship = _ship(turn_charge=0, mp=1, turn_cost=3)
    with pytest.raises(ValueError):
        ship.turn_left_auto()
