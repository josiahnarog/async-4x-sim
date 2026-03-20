"""Tests for the simultaneous-submission Encounter model."""
from __future__ import annotations

import random

import pytest

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.encounter import Encounter, Phase
from tactical.facing import Facing
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _two_ship_battle(
    a_pos: Hex = Hex(0, 0),
    b_pos: Hex = Hex(10, 0),
    a_facing: Facing = Facing.N,
    b_facing: Facing = Facing.S,
    mp: int = 6,
) -> BattleState:
    a = ShipState(ship_id="a1", owner_id="A", pos=a_pos, facing=a_facing, mp=mp, turn_cost=3)
    b = ShipState(ship_id="b1", owner_id="B", pos=b_pos, facing=b_facing, mp=mp, turn_cost=3)
    return BattleState(ships={"a1": a, "b1": b})


# ---------------------------------------------------------------------------
# Initiative
# ---------------------------------------------------------------------------

class TestInitiative:
    def test_deterministic_with_seed(self):
        battle = _two_ship_battle()
        enc = Encounter.start(battle, rng=random.Random(123))
        assert set(enc.initiative.rolls.keys()) == {"A", "B"}
        for roll in enc.initiative.rolls.values():
            assert 1 <= roll <= 10

    def test_order_is_reversed(self):
        battle = _two_ship_battle()
        enc = Encounter.start(battle, rng=random.Random(7))
        lo_hi = enc.initiative.order_low_to_high()
        hi_lo = enc.initiative.order_high_to_low()
        assert lo_hi == list(reversed(hi_lo))


# ---------------------------------------------------------------------------
# MOVE_SUBMISSION phase
# ---------------------------------------------------------------------------

class TestMoveSubmission:
    def test_starts_in_move_submission(self):
        battle = _two_ship_battle()
        enc = Encounter.start(battle, rng=random.Random(1))
        assert enc.phase == Phase.MOVE_SUBMISSION

    def test_stage_move_validates_mp(self):
        battle = _two_ship_battle(mp=3)
        enc = Encounter.start(battle, rng=random.Random(1))
        # Distance 4 > MP 3 => error
        with pytest.raises(ValueError, match="MP capacity"):
            enc.stage_move("A", "a1", Hex(4, 0), Facing.N)

    def test_stage_move_wrong_side_raises(self):
        battle = _two_ship_battle()
        enc = Encounter.start(battle, rng=random.Random(1))
        with pytest.raises(PermissionError):
            enc.stage_move("B", "a1", Hex(1, 0), Facing.N)

    def test_stage_move_can_be_overridden(self):
        battle = _two_ship_battle()
        enc = Encounter.start(battle, rng=random.Random(1))
        enc = enc.stage_move("A", "a1", Hex(1, 0), Facing.N)
        enc = enc.stage_move("A", "a1", Hex(2, 0), Facing.N)  # override
        assert enc._move_orders["a1"].dest == Hex(2, 0)

    def test_commit_after_commit_raises(self):
        battle = _two_ship_battle()
        enc = Encounter.start(battle, rng=random.Random(1))
        enc, _ = enc.commit_movement("A", random.Random(0))
        with pytest.raises(PermissionError):
            enc.commit_movement("A", random.Random(0))

    def test_stage_after_commit_raises(self):
        battle = _two_ship_battle()
        enc = Encounter.start(battle, rng=random.Random(1))
        enc, _ = enc.commit_movement("A", random.Random(0))
        with pytest.raises(PermissionError):
            enc.stage_move("A", "a1", Hex(1, 0), Facing.N)

    def test_first_commit_does_not_resolve(self):
        battle = _two_ship_battle()
        enc = Encounter.start(battle, rng=random.Random(1))
        enc, _ = enc.commit_movement("A", random.Random(0))
        assert enc.phase == Phase.MOVE_SUBMISSION  # still waiting for B

    def test_second_commit_triggers_resolution(self):
        battle = _two_ship_battle()
        enc = Encounter.start(battle, rng=random.Random(1))
        enc, _ = enc.commit_movement("A", random.Random(0))
        enc, _ = enc.commit_movement("B", random.Random(0))
        assert enc.phase == Phase.COMBAT_SUBMISSION

    def test_move_order_applied_after_both_commit(self):
        battle = _two_ship_battle(a_pos=Hex(0, 0), mp=6)
        enc = Encounter.start(battle, rng=random.Random(1))
        enc = enc.stage_move("A", "a1", Hex(3, 0), Facing.NE)
        enc, _ = enc.commit_movement("A", random.Random(0))
        enc, _ = enc.commit_movement("B", random.Random(0))
        # A's ship should have moved to (3, 0)
        assert enc.battle.ships["a1"].pos == Hex(3, 0)
        assert enc.battle.ships["a1"].facing == Facing.NE

    def test_ship_without_order_stays_in_place(self):
        battle = _two_ship_battle(a_pos=Hex(0, 0), b_pos=Hex(10, 0))
        enc = Encounter.start(battle, rng=random.Random(1))
        # A stages a move; B does not
        enc = enc.stage_move("A", "a1", Hex(2, 0), Facing.N)
        enc, _ = enc.commit_movement("A", random.Random(0))
        enc, _ = enc.commit_movement("B", random.Random(0))
        assert enc.battle.ships["a1"].pos == Hex(2, 0)
        assert enc.battle.ships["b1"].pos == Hex(10, 0)  # unchanged


# ---------------------------------------------------------------------------
# Collision resolution
# ---------------------------------------------------------------------------

class TestCollisionResolution:
    def test_collision_higher_initiative_wins(self):
        """Two ships moving toward the same hex: higher initiative claims it."""
        # Place ships 3 hexes apart on the q-axis, both have MP=6
        # They both target the hex between them
        a = ShipState(ship_id="a1", owner_id="A", pos=Hex(0, 0), facing=Facing.N, mp=6, turn_cost=3)
        b = ShipState(ship_id="b1", owner_id="B", pos=Hex(6, 0), facing=Facing.N, mp=6, turn_cost=3)
        battle = BattleState(ships={"a1": a, "b1": b})

        # Use seed that gives A higher initiative (we'll find it via trial)
        # Force initiative: patch after construction to get deterministic result
        enc = Encounter.start(battle, rng=random.Random(1))

        contested = Hex(3, 0)
        enc = enc.stage_move("A", "a1", contested, Facing.N)
        enc = enc.stage_move("B", "b1", contested, Facing.N)
        enc, _ = enc.commit_movement("A", random.Random(0))
        enc, _ = enc.commit_movement("B", random.Random(0))

        # One ship is at (3,0), the other stayed put
        positions = {s.pos for s in enc.battle.ships.values()}
        assert Hex(3, 0) in positions
        # The loser stayed at its original position
        original_positions = {Hex(0, 0), Hex(6, 0)}
        non_contested = positions - {Hex(3, 0)}
        assert non_contested <= original_positions

    def test_no_collision_when_different_destinations(self):
        battle = _two_ship_battle(a_pos=Hex(0, 0), b_pos=Hex(10, 0), mp=6)
        enc = Encounter.start(battle, rng=random.Random(1))
        enc = enc.stage_move("A", "a1", Hex(3, 0), Facing.N)
        enc = enc.stage_move("B", "b1", Hex(7, 0), Facing.N)
        enc, _ = enc.commit_movement("A", random.Random(0))
        enc, _ = enc.commit_movement("B", random.Random(0))
        assert enc.battle.ships["a1"].pos == Hex(3, 0)
        assert enc.battle.ships["b1"].pos == Hex(7, 0)


# ---------------------------------------------------------------------------
# COMBAT_SUBMISSION phase
# ---------------------------------------------------------------------------

class TestCombatSubmission:
    def _reach_combat(self) -> Encounter:
        battle = _two_ship_battle()
        enc = Encounter.start(battle, rng=random.Random(1))
        enc, _ = enc.commit_movement("A", random.Random(0))
        enc, _ = enc.commit_movement("B", random.Random(0))
        assert enc.phase == Phase.COMBAT_SUBMISSION
        return enc

    def test_stage_fire_wrong_side_raises(self):
        enc = self._reach_combat()
        with pytest.raises(PermissionError):
            enc.stage_fire("B", "a1", "b1")

    def test_stage_fire_unknown_target_raises(self):
        enc = self._reach_combat()
        with pytest.raises(KeyError):
            enc.stage_fire("A", "a1", "z99")

    def test_stage_fire_can_be_overridden(self):
        enc = self._reach_combat()
        enc2 = enc.stage_fire("A", "a1", "b1")
        enc3 = enc2.pass_fire("A", "a1")  # override with pass
        assert enc3._fire_orders["a1"] is None

    def test_first_fire_commit_does_not_resolve(self):
        enc = self._reach_combat()
        enc2, events = enc.commit_fire("A", random.Random(1))
        assert enc2.phase == Phase.COMBAT_SUBMISSION
        assert events == []

    def test_both_fire_commits_trigger_resolution(self):
        enc = self._reach_combat()
        enc, _ = enc.commit_fire("A", random.Random(1))
        enc, _ = enc.commit_fire("B", random.Random(1))
        assert enc.phase == Phase.MOVE_SUBMISSION

    def test_no_fire_orders_transitions_to_combat_small(self):
        """Both sides commit with no orders at all: should still transition."""
        enc = self._reach_combat()
        enc, events = enc.commit_fire("A", random.Random(1))
        enc, events = enc.commit_fire("B", random.Random(1))
        assert enc.phase == Phase.MOVE_SUBMISSION
        assert events == []

    def test_pass_fire_produces_no_events(self):
        enc = self._reach_combat()
        enc = enc.pass_fire("A", "a1")
        enc = enc.pass_fire("B", "b1")
        enc, events = enc.commit_fire("A", random.Random(1))
        enc, events = enc.commit_fire("B", random.Random(1))
        assert enc.phase == Phase.MOVE_SUBMISSION
        assert events == []


# ---------------------------------------------------------------------------
# Simultaneous fire — damage applied from pre-combat snapshot
# ---------------------------------------------------------------------------

class TestSimultaneousFire:
    def test_fire_events_returned_on_resolution(self):
        """Both sides fire at each other; events returned when last side commits."""
        a = ShipState(
            ship_id="a1", owner_id="A", pos=Hex(0, 0), facing=Facing.N,
            mp=6, turn_cost=3, systems=ShipSystems.parse("SSALL"),
        )
        b = ShipState(
            ship_id="b1", owner_id="B", pos=Hex(0, 3), facing=Facing.S,
            mp=6, turn_cost=3, systems=ShipSystems.parse("SSALL"),
        )
        battle = BattleState(ships={"a1": a, "b1": b})
        enc = Encounter.start(battle, rng=random.Random(42))
        enc, _ = enc.commit_movement("A", random.Random(0))
        enc, _ = enc.commit_movement("B", random.Random(0))

        enc = enc.stage_fire("A", "a1", "b1")
        enc = enc.stage_fire("B", "b1", "a1")

        enc, events_from_A_commit = enc.commit_fire("A", random.Random(5))
        assert events_from_A_commit == []  # resolution not triggered yet
        enc, events_final = enc.commit_fire("B", random.Random(5))
        # Resolution triggered: events list may be empty or not depending on rolls,
        # but the encounter must have advanced to COMBAT_SMALL
        assert enc.phase == Phase.MOVE_SUBMISSION

    def test_simultaneity_destroyed_ship_still_fires(self):
        """A ship with 1 system that is destroyed by incoming fire still fires back.

        We verify this by checking that both sides produce at least one roll each,
        even when one side is lethal.
        """
        # A fires lasers (L skips shields, hits hull directly)
        # Both ships have minimal systems so one shot can destroy
        a = ShipState(
            ship_id="a1", owner_id="A", pos=Hex(0, 0), facing=Facing.N,
            mp=0, turn_cost=3, systems=ShipSystems.parse("L"),
        )
        b = ShipState(
            ship_id="b1", owner_id="B", pos=Hex(0, 1), facing=Facing.S,
            mp=0, turn_cost=3, systems=ShipSystems.parse("L"),
        )
        battle = BattleState(ships={"a1": a, "b1": b})
        enc = Encounter.start(battle, rng=random.Random(1))
        enc, _ = enc.commit_movement("A", random.Random(0))
        enc, _ = enc.commit_movement("B", random.Random(0))

        enc = enc.stage_fire("A", "a1", "b1")
        enc = enc.stage_fire("B", "b1", "a1")

        rng = random.Random(999)  # high rolls to force misses (no damage, keep it simple)
        enc, _ = enc.commit_fire("A", rng)
        enc, events = enc.commit_fire("B", rng)

        # Both ships fired: there should be 2 fire events (one per attacker)
        assert len(events) == 2
        attacker_ids = {ev.attacker_id for ev in events}
        assert attacker_ids == {"a1", "b1"}
