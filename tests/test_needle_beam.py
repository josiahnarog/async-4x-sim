"""Tests for the Needle Beam (N) weapon system."""
from __future__ import annotations

import random

import pytest

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.combat import FireEvent, resolve_large_fire
from tactical.encounter import Encounter, Phase
from tactical.facing import Facing
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems
from tactical.weapons import WeaponType


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _ship(ship_id: str, owner: str, pos: Hex, systems: str, facing: Facing = Facing.N) -> ShipState:
    return ShipState(
        ship_id=ship_id, owner_id=owner,
        pos=pos, facing=facing,
        mp=5, turn_cost=2,
        systems=ShipSystems.parse(systems),
    )


class AlwaysN:
    """RNG stub: always returns a fixed value."""
    def __init__(self, n: int):
        self.n = n
    def randint(self, a: int, b: int) -> int:
        return self.n


class Sequence:
    """RNG stub: returns values in order, then repeats last."""
    def __init__(self, *values: int):
        self.values = list(values)
        self.idx = 0
    def randint(self, a: int, b: int) -> int:
        v = self.values[min(self.idx, len(self.values) - 1)]
        self.idx += 1
        return v


# ---------------------------------------------------------------------------
# ShipSystems.needle_beam_target — unit tests
# ---------------------------------------------------------------------------

class TestNeedleBeamTarget:
    def test_example1_battlecruiser(self):
        """20S + 20A: skip=30 → pool is A11-A20, roll=6 → A16 (index 30+5=35)."""
        track = "S" * 20 + "A" * 20
        ss = ShipSystems.parse(track)
        idx = ss.needle_beam_target(roll=6, skip=30)
        assert idx is not None
        # After skipping 20S+10A (indices 0-29), pool starts at index 30 (A11).
        # Roll 6 → pool[5] → index 35.
        assert idx == 35
        assert ss.systems[idx].base == "A"

    def test_example2_carrier_bays_skipped(self):
        """After shields/armor, bays are ineligible; roll 4 picks 4th non-bay system."""
        # Track: SSAA BhBh (III)  — 2S 2A then 2 hangar bays then an engine group
        ss = ShipSystems.parse("SSAA BhBh (III)")
        # skip=30 but only 4 S/A → skip all of them; pool = I I I (indices 6,7,8)
        idx = ss.needle_beam_target(roll=4, skip=30)
        assert idx is not None
        # Pool has 3 eligible (3 I systems), roll=4 → ((4-1) % 3) = 0 → first I (index 6)
        assert ss.systems[idx].base == "I"

    def test_example3_wrapping(self):
        """3 eligible non-S/A systems, roll=5 → wraps to 2nd (index 1 of pool)."""
        # Track: LLL  (3 lasers, no shields/armor)
        ss = ShipSystems.parse("LLL")
        idx = ss.needle_beam_target(roll=5, skip=30)
        assert idx is not None
        # Pool = [0, 1, 2], roll=5 → ((5-1) % 3) = 1 → index 1
        assert idx == 1

    def test_no_eligible_returns_none(self):
        """If all post-skip systems are bays, returns None."""
        ss = ShipSystems.parse("BhBh")
        idx = ss.needle_beam_target(roll=1, skip=30)
        assert idx is None

    def test_skip_partial_sa(self):
        """If fewer S/A than skip, all S/A are pre-skip and post-skip starts at first non-S/A."""
        # 5S + 1L: skip=30, only 5 S/A → pre-skip=[0..4], pool=[5 (L)]
        ss = ShipSystems.parse("SSSSSL")
        idx = ss.needle_beam_target(roll=3, skip=30)
        # Pool has 1 element (L at index 5), roll=3 → ((3-1) % 1) = 0 → index 5
        assert idx == 5
        assert ss.systems[idx].base == "L"

    def test_destroyed_systems_not_eligible(self):
        """Destroyed systems are excluded from the eligible pool."""
        ss = ShipSystems.parse("LLL")
        # Destroy the first L
        ss_damaged = ss.apply_damage(1)
        # Pool now = [1, 2] (index 0 is destroyed)
        idx = ss_damaged.needle_beam_target(roll=1, skip=30)
        assert idx == 1  # first intact system

    def test_sa_beyond_skip_threshold_are_eligible(self):
        """S/A systems beyond the skip threshold join the eligible pool."""
        # 35 armor systems: skip=30 → first 30 pre-skip, last 5 (indices 30-34) eligible
        ss = ShipSystems.parse("A" * 35)
        idx = ss.needle_beam_target(roll=2, skip=30)
        assert idx is not None
        # Pool = [30, 31, 32, 33, 34], roll=2 → index 31
        assert idx == 31

    def test_roll_1_always_first_eligible(self):
        """Roll 1 always selects the first eligible system."""
        ss = ShipSystems.parse("SSAL")
        idx = ss.needle_beam_target(roll=1, skip=30)
        # Skip 2 S/A → pool = [L at index 3]... wait, SS=2 (pre-skip), AA=skip 2 more=4,
        # but skip=30 so all S/A pre-skip. Pool = [L at index 3] since A's are pre-skip.
        # Actually track is S S A L → S(0), S(1), A(2), L(3)
        # skip=30, only 3 S/A → all pre-skip. Pool = [L at index 3].
        assert idx == 3


# ---------------------------------------------------------------------------
# ShipSystems.destroy_system_at — unit tests
# ---------------------------------------------------------------------------

class TestDestroySystemAt:
    def test_destroys_intact_system(self):
        ss = ShipSystems.parse("SAL")
        ss2 = ss.destroy_system_at(2)
        assert ss2.systems[2].status.value == "destroyed"
        assert ss.systems[2].status.value == "intact"   # original unchanged

    def test_noop_on_already_destroyed(self):
        ss = ShipSystems.parse("SAL")
        ss2 = ss.apply_damage(3)   # destroy all
        ss3 = ss2.destroy_system_at(1)
        assert ss3.systems == ss2.systems

    def test_noop_on_out_of_range(self):
        ss = ShipSystems.parse("SAL")
        ss2 = ss.destroy_system_at(99)
        assert ss2.systems == ss.systems


# ---------------------------------------------------------------------------
# resolve_large_fire — needle beam integration
# ---------------------------------------------------------------------------

class TestResolveLargeFireNeedle:
    def _attacker(self, systems="SSSSSSSSN") -> ShipState:
        return _ship("A1", "A", Hex(0, 0), systems)

    def _target(self, systems="SSSAAALL") -> ShipState:
        return _ship("B1", "B", Hex(2, 0), systems, facing=Facing.S)

    def _battle(self, attacker_systems="SSSSSSSSN", target_systems="SSSAAALL") -> BattleState:
        return BattleState(
            ships={
                "A1": self._attacker(attacker_systems),
                "B1": self._target(target_systems),
            },
            squadrons={},
        )

    def test_hit_returns_fire_event_with_needle_fields(self):
        """A hit populates needle_penetration_roll and needle_target_idx."""
        battle = self._battle()
        # Sequence(1, 3): roll=1 → hit (to_hit=8, roll 1 ≤ 8); needle_roll=3
        battle2, ev = resolve_large_fire(
            battle, attacker_id="A1", target_id="B1",
            weapon=WeaponType.NEEDLE_BEAM, rng=Sequence(1, 3),
        )
        assert isinstance(ev, FireEvent)
        assert ev.hit
        assert ev.needle_penetration_roll == 3
        assert ev.needle_target_idx is not None

    def test_miss_has_no_needle_fields(self):
        """A miss produces no needle fields."""
        battle = self._battle()
        # to_hit=8 at range 2; roll=10 → miss
        battle2, ev = resolve_large_fire(
            battle, attacker_id="A1", target_id="B1",
            weapon=WeaponType.NEEDLE_BEAM, rng=AlwaysN(10),
        )
        assert not ev.hit
        assert ev.needle_penetration_roll is None
        assert ev.needle_target_idx is None

    def test_hit_changes_target_systems(self):
        """A guaranteed hit actually modifies the target's systems."""
        # Target: 3S 3A 1L — needle skip=30 > 6 S/A → pool=[L at index 6]
        # Roll=1 (to-hit) guaranteed hit; needle_roll=1 → first eligible (L)
        battle = self._battle(target_systems="SSSAAAL")
        orig = battle.ships["B1"].systems.render_compact()

        battle2, ev = resolve_large_fire(
            battle, attacker_id="A1", target_id="B1",
            weapon=WeaponType.NEEDLE_BEAM, rng=Sequence(1, 1),
        )
        assert ev.hit
        new_compact = battle2.ships["B1"].systems.render_compact()
        assert orig != new_compact
        # The L should be destroyed
        assert "!L" in new_compact

    def test_needle_bypasses_shields(self):
        """Hit on a target with many shields still destroys a deep system."""
        # Target: 10S + 1L — skip=30 > 10 S/A → pool=[L at idx 10]
        battle = self._battle(target_systems="S" * 10 + "L")
        battle2, ev = resolve_large_fire(
            battle, attacker_id="A1", target_id="B1",
            weapon=WeaponType.NEEDLE_BEAM, rng=Sequence(1, 1),
        )
        assert ev.hit
        assert ev.needle_target_idx == 10
        new_compact = battle2.ships["B1"].systems.render_compact()
        assert "!L" in new_compact
        # Shields must be untouched
        assert "!S" not in new_compact

    def test_needle_skips_exactly_30_sa(self):
        """With exactly 30 S/A before other systems, the first eligible post-skip system is hit."""
        # 30 armor + 1 laser: pool=[L at index 30]
        battle = self._battle(target_systems="A" * 30 + "L")
        battle2, ev = resolve_large_fire(
            battle, attacker_id="A1", target_id="B1",
            weapon=WeaponType.NEEDLE_BEAM, rng=Sequence(1, 1),
        )
        assert ev.needle_target_idx == 30

    def test_needle_partially_penetrates_sa(self):
        """With 35 S/A, only the first 30 are skipped; remaining 5 + other systems are eligible."""
        # 35 armor: pre-skip=[0..29], pool=[30..34], roll_to_hit=1 (hit), needle_roll=3
        battle = self._battle(target_systems="A" * 35)
        battle2, ev = resolve_large_fire(
            battle, attacker_id="A1", target_id="B1",
            weapon=WeaponType.NEEDLE_BEAM, rng=Sequence(1, 3),
        )
        assert ev.hit
        # pool=[30,31,32,33,34], roll=3 → index 32
        assert ev.needle_target_idx == 32

    def test_wrapping_penetration_roll(self):
        """Roll > eligible count wraps correctly."""
        # Target: only 3L after shields (all S/A < 30 → pre-skip)
        battle = self._battle(target_systems="SSSLLL")
        battle2, ev = resolve_large_fire(
            battle, attacker_id="A1", target_id="B1",
            weapon=WeaponType.NEEDLE_BEAM, rng=Sequence(1, 5),
        )
        assert ev.hit
        # Pool=[3,4,5] (L,L,L), roll=5 → ((5-1)%3)=1 → index 4
        assert ev.needle_target_idx == 4

    def test_no_eligible_targets_no_damage(self):
        """If all post-skip systems are bays, raw_damage=0."""
        # Target: pure bay track — all bays, skip=30 (no S/A), eligible=empty
        battle = self._battle(target_systems="BhBh")
        battle2, ev = resolve_large_fire(
            battle, attacker_id="A1", target_id="B1",
            weapon=WeaponType.NEEDLE_BEAM, rng=Sequence(1, 1),
        )
        assert ev.hit
        assert ev.raw_damage == 0
        assert ev.needle_target_idx is None


# ---------------------------------------------------------------------------
# Full encounter — needle beam through fire_resolution
# ---------------------------------------------------------------------------

class TestNeedleBeamInEncounter:
    def _reach_combat_submission(self, attacker_systems: str, target_systems: str) -> Encounter:
        a = _ship("a1", "A", Hex(0, 0), attacker_systems)
        b = _ship("b1", "B", Hex(2, 0), target_systems, facing=Facing.S)
        battle = BattleState(ships={"a1": a, "b1": b}, squadrons={})
        enc = Encounter.start(battle, rng=random.Random(1))
        enc, _ = enc.commit_movement("A", random.Random(0))
        enc, _ = enc.commit_movement("B", random.Random(0))
        return enc

    def test_needle_hit_bypasses_shields_in_encounter(self):
        """End-to-end: N beam at range 2 bypasses shields and destroys a deep system."""
        enc = self._reach_combat_submission("SSSSSSSSN", "S" * 10 + "L")
        enc = enc.stage_fire("A", "a1", "b1")

        # Use RNG that: hits (roll 1 ≤ 8), needle_roll=1 → first eligible (L at idx 10)
        enc2, events = enc.commit_fire("A", Sequence(1, 1))
        enc2, events2 = enc2.commit_fire("B", random.Random(0))
        all_events = events + events2

        b1_systems = enc2.battle.ships["b1"].systems.render_compact()
        # Shields intact, laser destroyed
        assert "!S" not in b1_systems
        assert "!L" in b1_systems

    def test_needle_hit_both_sides_simultaneous(self):
        """Both ships fire N beams; simultaneity maintained (each fires at snapshot)."""
        enc = self._reach_combat_submission("SSSSSSSSN", "SSSSSSSSN")
        enc = enc.stage_fire("A", "a1", "b1")
        enc = enc.stage_fire("B", "b1", "a1")
        enc2, _ = enc.commit_fire("A", Sequence(1, 1))
        enc2, _ = enc2.commit_fire("B", Sequence(1, 1))
        # Both N beams are turret-mounted (12 HS total) and fire at bearing 1 — valid.
        # (just ensuring no crash here — phase may be anything including COMPLETE)
        assert enc2.phase is not None
