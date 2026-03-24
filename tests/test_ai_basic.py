"""Smoke tests for the tactical AI.

These tests verify that the AI produces valid, committable orders without
crashing, covers all three phases, and respects difficulty settings.
They do not assert specific tactical decisions — the AI's choices are
intentionally stochastic.
"""
from __future__ import annotations

import random

import pytest

from sim.hexgrid import Hex
from tactical.ai import DEFAULT, EASY, HARD, make_fire_orders, make_move_orders, make_squadron_orders
from tactical.ai.evaluator import evaluate
from tactical.ai.profile import AIProfile
from tactical.battle_state import BattleState
from tactical.encounter import Encounter, Phase
from tactical.facing import Facing
from tactical.fighter_class import F1
from tactical.hull_types import HULL_TYPES
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems
from tactical.squadron_state import FighterLoadout, SquadronState
from tactical.weapons import WeaponType

FG = HULL_TYPES["FG"]
CV = HULL_TYPES["CA"]

_FG_SYS = "SSSAAAFFL(I)"
_CV_SYS = "SSSAAAFQ(I)(I)BhBhBlBlR"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _ship(ship_id: str, owner: str, pos: Hex, facing: Facing = Facing.N,
          systems: str = _FG_SYS, hull=None) -> ShipState:
    ht = hull or FG
    return ShipState(
        ship_id=ship_id, owner_id=owner, pos=pos, facing=facing,
        mp=ht.max_speed, turn_cost=ht.turn_cost, turn_charge=0,
        systems=ShipSystems.parse(systems), hull_type=ht,
    )


def _squadron(sq_id: str, owner: str, pos: Hex, docked_at=None) -> SquadronState:
    return SquadronState(
        squadron_id=sq_id, owner_id=owner, pos=pos,
        strength=5, max_strength=5,
        loadout=FighterLoadout(fighter_class=F1, internal=(WeaponType.GUN,)),
        endurance=10, max_endurance=10,
        docked_at=docked_at,
    )


def _simple_battle() -> BattleState:
    return BattleState(ships={
        "A1": _ship("A1", "A", Hex(0, 0), Facing.NE),
        "B1": _ship("B1", "B", Hex(6, 0), Facing.SW),
    })


def _advance_to_fire(battle: BattleState) -> Encounter:
    enc = Encounter.start(battle, rng=random.Random(42))
    enc = make_move_orders(enc, "A", rng=random.Random(1))
    enc = make_move_orders(enc, "B", rng=random.Random(2))
    enc, _ = enc.commit_movement("A", random.Random(3))
    enc, _ = enc.commit_movement("B", random.Random(4))
    assert enc.phase == Phase.COMBAT_SUBMISSION
    return enc


def _advance_to_combat_small(battle: BattleState) -> Encounter:
    enc = _advance_to_fire(battle)
    enc = make_fire_orders(enc, "A", rng=random.Random(5))
    enc = make_fire_orders(enc, "B", rng=random.Random(6))
    enc, _ = enc.commit_fire("A", random.Random(7))
    enc, _ = enc.commit_fire("B", random.Random(8))
    return enc


# ---------------------------------------------------------------------------
# Evaluator tests
# ---------------------------------------------------------------------------

class TestEvaluator:
    def test_equal_fleets_near_zero(self):
        """Symmetric battle should evaluate near 0 for both sides."""
        battle = _simple_battle()
        score_a = evaluate(battle, "A", DEFAULT)
        score_b = evaluate(battle, "B", DEFAULT)
        # Not exactly 0 due to position asymmetry; magnitudes should be similar.
        assert abs(score_a + score_b) < 5.0

    def test_destroyed_ship_hurts_score(self):
        """Losing systems should worsen material score."""
        battle = _simple_battle()
        score_before = evaluate(battle, "A", DEFAULT)

        # Destroy A1's systems.
        a1 = battle.ships["A1"]
        damaged = a1.systems.apply_damage(len(list(a1.systems.systems)))
        import dataclasses
        a1_damaged = dataclasses.replace(a1, systems=damaged)
        damaged_battle = battle.with_ship(a1_damaged)

        score_after = evaluate(damaged_battle, "A", DEFAULT)
        assert score_after < score_before

    def test_different_profiles_same_battle(self):
        """Profile should not crash the evaluator."""
        battle = _simple_battle()
        for profile in [EASY, DEFAULT, HARD]:
            score = evaluate(battle, "A", profile)
            assert isinstance(score, float)


# ---------------------------------------------------------------------------
# Move phase tests
# ---------------------------------------------------------------------------

class TestMoveAI:
    def test_move_orders_do_not_crash(self):
        """AI can stage move orders without raising."""
        battle = _simple_battle()
        enc = Encounter.start(battle, rng=random.Random(42))
        enc = make_move_orders(enc, "A", DEFAULT, rng=random.Random(1))
        enc = make_move_orders(enc, "B", DEFAULT, rng=random.Random(2))
        # Both sides commit successfully.
        enc, _ = enc.commit_movement("A", random.Random(3))
        enc, _ = enc.commit_movement("B", random.Random(4))
        assert enc.phase == Phase.COMBAT_SUBMISSION

    def test_easy_and_hard_profiles_both_work(self):
        """EASY and HARD profiles both produce committable orders."""
        for profile in [EASY, HARD]:
            battle = _simple_battle()
            enc = Encounter.start(battle, rng=random.Random(0))
            enc = make_move_orders(enc, "A", profile, rng=random.Random(1))
            enc = make_move_orders(enc, "B", profile, rng=random.Random(2))
            enc, _ = enc.commit_movement("A", random.Random(3))
            enc, _ = enc.commit_movement("B", random.Random(4))
            assert enc.phase == Phase.COMBAT_SUBMISSION

    def test_ai_ships_move_closer(self):
        """Ships starting far apart should generally close distance after an AI move."""
        battle = BattleState(ships={
            "A1": _ship("A1", "A", Hex(0, 0), Facing.NE),
            "B1": _ship("B1", "B", Hex(20, 0), Facing.SW),
        })
        enc = Encounter.start(battle, rng=random.Random(42))
        dist_before = 20
        enc = make_move_orders(enc, "A", DEFAULT, rng=random.Random(1))
        enc = make_move_orders(enc, "B", DEFAULT, rng=random.Random(2))
        enc, _ = enc.commit_movement("A", random.Random(3))
        enc, _ = enc.commit_movement("B", random.Random(4))
        from sim.hexgrid import hex_distance
        dist_after = hex_distance(
            enc.battle.ships["A1"].pos,
            enc.battle.ships["B1"].pos,
        )
        assert dist_after < dist_before


# ---------------------------------------------------------------------------
# Fire phase tests
# ---------------------------------------------------------------------------

class TestFireAI:
    def test_fire_orders_commit_cleanly(self):
        """AI fire orders can be staged and committed without error."""
        enc = _advance_to_fire(_simple_battle())
        enc = make_fire_orders(enc, "A", DEFAULT, rng=random.Random(9))
        enc = make_fire_orders(enc, "B", DEFAULT, rng=random.Random(10))
        enc, events = enc.commit_fire("A", random.Random(11))
        enc, events2 = enc.commit_fire("B", random.Random(12))
        # Phase advances regardless of whether fire connected.
        # With no squadrons, COMBAT_SMALL is skipped → next turn's MOVE_SUBMISSION.
        assert enc.phase in (Phase.COMBAT_SMALL, Phase.COMPLETE, Phase.MOVE_SUBMISSION)

    def test_fire_targets_enemies_not_allies(self):
        """Multi-ship scenario: ships must target enemies only."""
        battle = BattleState(ships={
            "A1": _ship("A1", "A", Hex(0, 0),  Facing.NE),
            "A2": _ship("A2", "A", Hex(1, 0),  Facing.NE),
            "B1": _ship("B1", "B", Hex(6, 0),  Facing.SW),
        })
        enc = _advance_to_fire(battle)
        enc = make_fire_orders(enc, "A", DEFAULT, rng=random.Random(1))
        # Inspect staged orders: all targets must be "B1".
        for ship_id, order in enc._fire_orders.items():
            if order is not None and enc.battle.ships[ship_id].owner_id == "A":
                assert enc.battle.ships[order.target_id].owner_id == "B", (
                    f"{ship_id} targeted a friendly ship"
                )


# ---------------------------------------------------------------------------
# Squadron phase tests
# ---------------------------------------------------------------------------

class TestSquadronAI:
    def test_squadron_orders_commit_cleanly(self):
        """AI squadron orders advance to the next turn without error."""
        battle = BattleState(
            ships={
                "A1": _ship("A1", "A", Hex(0, 0), Facing.NE),
                "B1": _ship("B1", "B", Hex(6, 0), Facing.SW),
            },
            squadrons={
                "AF1": _squadron("AF1", "A", Hex(1, 0)),
                "BF1": _squadron("BF1", "B", Hex(5, 0)),
            },
        )
        enc = _advance_to_combat_small(battle)
        assert enc.phase == Phase.COMBAT_SMALL
        enc = make_squadron_orders(enc, "A", DEFAULT, rng=random.Random(1))
        enc = make_squadron_orders(enc, "B", DEFAULT, rng=random.Random(2))
        enc, _ = enc.commit_squadron_orders("A", random.Random(3))
        enc, _ = enc.commit_squadron_orders("B", random.Random(4))
        # Phase should have advanced to next turn's MOVE_SUBMISSION.
        assert enc.phase in (Phase.MOVE_SUBMISSION, Phase.COMPLETE)

    def test_launch_orders_deploy_docked_squadrons(self):
        """AI stages a launch order for docked squadrons when enemies are near."""
        carrier = _ship("A2", "A", Hex(0, 0), Facing.NE, systems=_CV_SYS, hull=CV)
        sq_docked = _squadron("AF1", "A", Hex(0, 0), docked_at="A2")
        import dataclasses
        filled_sys = carrier.systems.dock_squadron("AF1")
        carrier = dataclasses.replace(carrier, systems=filled_sys)

        battle = BattleState(
            ships={
                "A2": carrier,
                "B1": _ship("B1", "B", Hex(6, 0), Facing.SW),
            },
            squadrons={"AF1": sq_docked},
        )
        enc = Encounter.start(battle, rng=random.Random(42))
        enc = make_move_orders(enc, "A", DEFAULT, rng=random.Random(1))
        # AF1 should be in the launch orders now.
        assert "A2" in enc._launch_orders
        launched_ids = [lo.squadron_id for lo in enc._launch_orders["A2"]]
        assert "AF1" in launched_ids
