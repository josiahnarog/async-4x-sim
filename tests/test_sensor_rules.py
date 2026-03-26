"""Tests for tactical/sensor_rules.py — fog of war detection logic."""
from __future__ import annotations

import pytest

from sim.hexgrid import Hex, hex_distance
from tactical.facing import Facing
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems
from tactical.sensor_rules import (
    BASE_SENSOR_LEVEL,
    _y_tier,
    sensor_level,
    cloak_level,
    detection_level,
    major_status_flags,
    compute_detections,
    update_knowledge,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ship(
    ship_id: str = "X1",
    owner_id: str = "A",
    pos: Hex | None = None,
    systems_str: str = "SSSAAAI",
) -> ShipState:
    return ShipState(
        ship_id=ship_id,
        owner_id=owner_id,
        pos=pos or Hex(0, 0),
        facing=Facing.N,
        mp=5,
        turn_cost=2,
        turn_charge=0,
        systems=ShipSystems.parse(systems_str),
    )


# ---------------------------------------------------------------------------
# _y_tier
# ---------------------------------------------------------------------------

def test_y_tier_empty():
    assert _y_tier("") == 1


def test_y_tier_i():
    assert _y_tier("i") == 2


def test_y_tier_a():
    assert _y_tier("a") == 3


def test_y_tier_unknown():
    assert _y_tier("x") == 1


# ---------------------------------------------------------------------------
# sensor_level
# ---------------------------------------------------------------------------

def test_sensor_level_no_y():
    ship = make_ship(systems_str="SSSAAAI")
    assert sensor_level(ship) == BASE_SENSOR_LEVEL


def test_sensor_level_basic_y():
    ship = make_ship(systems_str="YSSSAAAI")
    assert sensor_level(ship) == 1


def test_sensor_level_improved_yi():
    ship = make_ship(systems_str="YiSSSAAI")
    assert sensor_level(ship) == 2


def test_sensor_level_advanced_ya():
    ship = make_ship(systems_str="YaSSSAAI")
    assert sensor_level(ship) == 3


def test_sensor_level_multiple_y_same_tier_no_stack():
    # Two basic Y systems — should still be tier 1, not 2
    ship = make_ship(systems_str="YYSSSAI")
    assert sensor_level(ship) == 1


def test_sensor_level_best_tier_wins():
    # Y (tier 1) + Yi (tier 2) → should return 2
    ship = make_ship(systems_str="YYiSAI")
    assert sensor_level(ship) == 2


def test_sensor_level_no_systems():
    ship = ShipState(
        ship_id="X1", owner_id="A", pos=Hex(0, 0),
        facing=Facing.N, mp=5, turn_cost=2, turn_charge=0,
        systems=None,
    )
    assert sensor_level(ship) == BASE_SENSOR_LEVEL


# ---------------------------------------------------------------------------
# cloak_level
# ---------------------------------------------------------------------------

def test_cloak_level_no_clk():
    ship = make_ship(systems_str="SSSAAAI")
    assert cloak_level(ship) == 0


def test_cloak_level_with_clk():
    # Clk is parsed as base=C mods=lk — but token="Clk"
    # We need to verify the parser handles it correctly.
    ship = make_ship(systems_str="ClkSAAI")
    assert cloak_level(ship) == 1


def test_cloak_level_multiple_clk():
    ship = make_ship(systems_str="ClkClkSAI")
    assert cloak_level(ship) == 2


def test_cloak_level_no_systems():
    ship = ShipState(
        ship_id="X1", owner_id="A", pos=Hex(0, 0),
        facing=Facing.N, mp=5, turn_cost=2, turn_charge=0,
        systems=None,
    )
    assert cloak_level(ship) == 0


# ---------------------------------------------------------------------------
# detection_level — table spot checks
# ---------------------------------------------------------------------------

def test_detection_range_ge_1000():
    # Any diff, range >= 1000 → always 0
    assert detection_level(3, 0, 1000) == 0
    assert detection_level(3, 0, 9999) == 0


def test_detection_diff0_range4():
    # diff=0, range<5 → col 4 → table row[3][4] = 3
    assert detection_level(0, 0, 4) == 3


def test_detection_diff0_range6():
    # diff=0, range<10 → col 3 → table row[3][3] = 2
    assert detection_level(0, 0, 6) == 2


def test_detection_diff0_range15():
    # diff=0, range<20 → col 2 → table row[3][2] = 1
    assert detection_level(0, 0, 15) == 1


def test_detection_diff0_range50():
    # diff=0, range<100 → col 1 → table row[3][1] = 1
    assert detection_level(0, 0, 50) == 1


def test_detection_diff0_range500():
    # diff=0, range<1000 → col 0 → table row[3][0] = 0
    assert detection_level(0, 0, 500) == 0


def test_detection_diff1_range6():
    # diff=1, range<10 → col 3 → table row[4][3] = 3
    assert detection_level(1, 0, 6) == 3


def test_detection_diff_neg1_range6():
    # diff=-1, range<10 → col 3 → table row[2][3] = 1
    assert detection_level(0, 1, 6) == 1


def test_detection_diff3_range500():
    # diff=3, range<1000 → col 0 → table row[6][0] = 2
    assert detection_level(3, 0, 500) == 2


def test_detection_diff_neg3_range4():
    # diff=-3, range<5 → col 4 → table row[0][4] = 1
    assert detection_level(0, 3, 4) == 1


def test_detection_clamped_diff():
    # diff > 3 should be clamped to 3
    assert detection_level(10, 0, 6) == detection_level(3, 0, 6)
    # diff < -3 should be clamped to -3
    assert detection_level(0, 10, 6) == detection_level(0, 3, 6)


# ---------------------------------------------------------------------------
# major_status_flags
# ---------------------------------------------------------------------------

def test_major_status_all_intact():
    ship = make_ship(systems_str="SSSAAAI")
    flags = major_status_flags(ship)
    assert "SHIELDS DOWN" not in flags
    assert "STREAMING ATMO" not in flags
    assert "ENGINES DAMAGED" not in flags
    assert "ENGINES DISABLED" not in flags


def test_major_status_shields_down():
    ship = make_ship(systems_str="AAAI")
    flags = major_status_flags(ship)
    assert "SHIELDS DOWN" in flags


def test_major_status_streaming_atmo():
    # STREAMING ATMO triggers when the first non-S/A system is destroyed,
    # regardless of whether shields/armor are intact.
    from tactical.ship_systems import ShipSystems as SS
    systems = ShipSystems.parse("SSSAAI")
    # Destroy the engine (index 5) — armor still intact
    new_systems = list(systems.systems)
    new_systems[5] = new_systems[5].destroy()
    ship = ShipState(
        ship_id="X1", owner_id="A", pos=Hex(0, 0),
        facing=Facing.N, mp=5, turn_cost=2, turn_charge=0,
        systems=SS(tuple(new_systems)),
    )
    flags = major_status_flags(ship)
    assert "STREAMING ATMO" in flags
    # Intact armor alone does NOT trigger the flag
    assert "STREAMING ATMO" not in major_status_flags(make_ship(systems_str="SSSAAI"))


def test_major_status_engines_damaged():
    # Build a ship with 2 I systems, destroy one.
    systems = ShipSystems.parse("SSSAAII")
    # Destroy the first I system (index 5)
    new_systems = list(systems.systems)
    from tactical.ship_systems import SystemStatus
    new_systems[5] = new_systems[5].destroy()
    from tactical.ship_systems import ShipSystems as SS
    ship = ShipState(
        ship_id="X1", owner_id="A", pos=Hex(0, 0),
        facing=Facing.N, mp=5, turn_cost=2, turn_charge=0,
        systems=SS(tuple(new_systems)),
    )
    flags = major_status_flags(ship)
    assert "ENGINES DAMAGED" in flags
    assert "ENGINES DISABLED" not in flags


def test_major_status_engines_disabled():
    # Build a ship with 2 I systems, destroy all.
    systems = ShipSystems.parse("SSSAAII")
    new_systems = list(systems.systems)
    from tactical.ship_systems import SystemStatus, ShipSystems as SS
    new_systems[5] = new_systems[5].destroy()
    new_systems[6] = new_systems[6].destroy()
    ship = ShipState(
        ship_id="X1", owner_id="A", pos=Hex(0, 0),
        facing=Facing.N, mp=5, turn_cost=2, turn_charge=0,
        systems=SS(tuple(new_systems)),
    )
    flags = major_status_flags(ship)
    assert "ENGINES DISABLED" in flags
    assert "ENGINES DAMAGED" not in flags


def test_major_status_no_systems():
    ship = ShipState(
        ship_id="X1", owner_id="A", pos=Hex(0, 0),
        facing=Facing.N, mp=5, turn_cost=2, turn_charge=0,
        systems=None,
    )
    assert major_status_flags(ship) == []


def test_major_status_all_flags():
    # Ship with only one of each destroyed
    systems = ShipSystems.parse("SAI")
    new_systems = list(systems.systems)
    from tactical.ship_systems import ShipSystems as SS
    # Destroy all systems
    new_systems = [s.destroy() for s in new_systems]
    ship = ShipState(
        ship_id="X1", owner_id="A", pos=Hex(0, 0),
        facing=Facing.N, mp=5, turn_cost=2, turn_charge=0,
        systems=SS(tuple(new_systems)),
    )
    flags = major_status_flags(ship)
    assert "SHIELDS DOWN" in flags
    assert "STREAMING ATMO" in flags
    assert "ENGINES DISABLED" in flags


# ---------------------------------------------------------------------------
# update_knowledge
# ---------------------------------------------------------------------------

def test_update_knowledge_empty_old():
    old = {}
    current = {"A1": 2, "B1": 0}
    result = update_knowledge(old, current)
    assert result["A1"] == 2
    assert result["B1"] == 0


def test_update_knowledge_level_retained_if_still_detected():
    old = {"A1": 1}
    current = {"A1": 2}
    result = update_knowledge(old, current)
    assert result["A1"] == 2  # max(1, 2)


def test_update_knowledge_level_not_downgraded():
    old = {"A1": 3}
    current = {"A1": 1}
    result = update_knowledge(old, current)
    assert result["A1"] == 3  # max(3, 1) = 3


def test_update_knowledge_reset_when_zero():
    old = {"A1": 3}
    current = {"A1": 0}
    result = update_knowledge(old, current)
    assert result["A1"] == 0  # lost contact → reset


def test_update_knowledge_units_not_in_current_unchanged():
    old = {"A1": 2, "A2": 1}
    current = {"A1": 3}
    result = update_knowledge(old, current)
    assert result["A1"] == 3  # updated
    assert result["A2"] == 1  # preserved (not in current)


def test_update_knowledge_new_unit_detected():
    old = {}
    current = {"X1": 1}
    result = update_knowledge(old, current)
    assert result["X1"] == 1


# ---------------------------------------------------------------------------
# compute_detections — integration with BattleState
# ---------------------------------------------------------------------------

def test_compute_detections_basic():
    """Side A has a ship at (0,0), Side B at (5,0). Range=5, diff=0 → col<10 → 2."""
    from tactical.battle_state import BattleState

    ship_a = make_ship("A1", "A", Hex(0, 0), "SSSAAAI")
    ship_b = make_ship("B1", "B", Hex(5, 0), "SSSAAAI")
    battle = BattleState(ships={"A1": ship_a, "B1": ship_b}, squadrons={})

    dets = compute_detections(battle, "A")
    # Only enemy B1 should be in the result
    assert "A1" not in dets
    assert "B1" in dets
    # Range 5, diff 0, range<10 → col 3 → table[3][3] = 2
    assert dets["B1"] == 2


def test_compute_detections_own_ships_excluded():
    from tactical.battle_state import BattleState

    ship_a1 = make_ship("A1", "A", Hex(0, 0), "SSSAAAI")
    ship_a2 = make_ship("A2", "A", Hex(1, 0), "SSSAAAI")
    ship_b1 = make_ship("B1", "B", Hex(10, 0), "SSSAAAI")
    battle = BattleState(ships={"A1": ship_a1, "A2": ship_a2, "B1": ship_b1}, squadrons={})

    dets = compute_detections(battle, "A")
    assert "A1" not in dets
    assert "A2" not in dets
    assert "B1" in dets


def test_compute_detections_sensor_advantage():
    """A1 has Yi (tier 2 sensor), B1 has no cloak. At range 6: diff=2, col<10 → 3."""
    from tactical.battle_state import BattleState

    ship_a = make_ship("A1", "A", Hex(0, 0), "YiSAAI")
    ship_b = make_ship("B1", "B", Hex(6, 0), "SSSAAAI")
    battle = BattleState(ships={"A1": ship_a, "B1": ship_b}, squadrons={})

    dets = compute_detections(battle, "A")
    # diff=2, range=6 → col<10 → table[5][3] = 3
    assert dets["B1"] == 3


def test_compute_detections_out_of_range():
    """Ships 1000 hexes apart → always 0."""
    from tactical.battle_state import BattleState

    ship_a = make_ship("A1", "A", Hex(0, 0), "YaSAAI")
    ship_b = make_ship("B1", "B", Hex(1000, 0), "SSSAAAI")
    battle = BattleState(ships={"A1": ship_a, "B1": ship_b}, squadrons={})

    dets = compute_detections(battle, "A")
    assert dets["B1"] == 0
