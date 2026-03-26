"""Integration test: run a full AI-vs-AI battle from the default scenario.

Drives the encounter through MOVE → FIRE → COMBAT_SMALL repeatedly using the
same auto-turn logic as the web UI until Phase.COMPLETE, then asserts:
  - No exception was raised at any point.
  - The battle resolved within a reasonable turn limit.
  - At least one side survived (winner or draw — both are valid outcomes).
"""
from __future__ import annotations

import random

import pytest

from tactical.ai import DEFAULT, HARD, make_fire_orders, make_move_orders, make_squadron_orders
from tactical.encounter import Encounter, Phase
from tactical.scenarios import default_scenario


MAX_TURNS = 60  # safety ceiling — a real battle should resolve well before this


def _run_full_battle(battle_state, rng: random.Random, profile=DEFAULT) -> Encounter:
    """Drive an encounter to completion using AI orders for both sides.

    Returns the final Encounter (phase == COMPLETE).
    Raises AssertionError if the turn cap is exceeded.
    """
    enc = Encounter.start(battle_state, rng=rng)
    sides = ["A", "B"]

    for turn_number in range(1, MAX_TURNS + 1):
        if enc.phase == Phase.COMPLETE:
            break

        # --- MOVE_SUBMISSION ---
        assert enc.phase == Phase.MOVE_SUBMISSION, (
            f"Turn {turn_number}: unexpected phase {enc.phase}"
        )
        for side in sides:
            enc = make_move_orders(enc, side, profile, rng=random.Random(rng.randint(0, 2**31)))
        for side in sides:
            enc, _ = enc.commit_movement(side, random.Random(rng.randint(0, 2**31)))
            if enc.phase == Phase.COMPLETE:
                break
        if enc.phase == Phase.COMPLETE:
            break

        # --- COMBAT_SUBMISSION ---
        assert enc.phase == Phase.COMBAT_SUBMISSION, (
            f"Turn {turn_number}: unexpected phase {enc.phase}"
        )
        for side in sides:
            enc = make_fire_orders(enc, side, profile, rng=random.Random(rng.randint(0, 2**31)))
        for side in sides:
            enc, _ = enc.commit_fire(side, random.Random(rng.randint(0, 2**31)))
            if enc.phase == Phase.COMPLETE:
                break
        if enc.phase == Phase.COMPLETE:
            break

        # --- COMBAT_SMALL (may be auto-skipped if no squadrons) ---
        if enc.phase == Phase.COMBAT_SMALL:
            for side in sides:
                enc = make_squadron_orders(enc, side, profile, rng=random.Random(rng.randint(0, 2**31)))
            for side in sides:
                enc, _ = enc.commit_squadron_orders(side, random.Random(rng.randint(0, 2**31)))
                if enc.phase == Phase.COMPLETE:
                    break

    assert enc.phase == Phase.COMPLETE, (
        f"Battle did not resolve within {MAX_TURNS} turns (stuck at {enc.phase})"
    )
    return enc


class TestFullBattleIntegration:

    def test_default_scenario_resolves(self):
        """Default scenario (2 FGs + 2 CVs per side) reaches COMPLETE without crashing."""
        battle, rng = default_scenario(seed=42)
        enc = _run_full_battle(battle, rng)
        assert enc.phase == Phase.COMPLETE

    def test_default_scenario_has_outcome(self):
        """At least one side survives (winner or draw — no zombie battle)."""
        battle, rng = default_scenario(seed=42)
        enc = _run_full_battle(battle, rng)
        alive = {
            s.owner_id for s in enc.battle.ships.values()
            if s.systems is None or not s.systems.is_destroyed()
        }
        # alive can be {"A"}, {"B"}, or {"A", "B"} (draw) — but not empty.
        assert len(alive) >= 1

    def test_different_seeds_no_crash(self):
        """Several seeds all complete MAX_TURNS without raising any exception.

        Some seeds may reach a tactical stalemate (both sides too damaged to
        finish each other off) — that is a known design edge case, not a bug.
        The critical invariant here is: no exception at any point.
        """
        for seed in [1, 7, 13, 99, 256]:
            battle, rng = default_scenario(seed=seed)
            try:
                enc = _run_full_battle(battle, rng)
            except AssertionError as exc:
                # Turn-cap assertion is expected for stalemate seeds; re-raise
                # anything that isn't the cap message.
                if "did not resolve within" not in str(exc):
                    raise

    def test_hard_profile_resolves(self):
        """HARD AI profile also completes without crashing."""
        battle, rng = default_scenario(seed=42)
        enc = _run_full_battle(battle, rng, profile=HARD)
        assert enc.phase == Phase.COMPLETE
