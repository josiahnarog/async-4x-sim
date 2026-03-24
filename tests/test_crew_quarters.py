"""Tests for the Q (Crew Quarters) system and its shooting_mods hook."""
from __future__ import annotations

import pytest

from sim.hexgrid import Hex
from tactical.attack_context import ToHitMod
from tactical.battle_state import BattleState
from tactical.encounter import Encounter
from tactical.facing import Facing
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems
from tactical.hull_types import HULL_TYPES
FG = HULL_TYPES["FG"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FixedRNG:
    def __init__(self, value: int = 5):
        self.value = value
    def randint(self, a: int, b: int) -> int:
        return self.value


def _ship(ship_id: str, owner: str, pos: Hex, facing: Facing,
          systems: str) -> ShipState:
    return ShipState(
        ship_id=ship_id, owner_id=owner, pos=pos, facing=facing,
        mp=5, turn_cost=FG.turn_cost, turn_charge=0,
        systems=ShipSystems.parse(systems), hull_type=FG,
    )


# ---------------------------------------------------------------------------
# ShipSystems.shooting_mods()
# ---------------------------------------------------------------------------

class TestShootingMods:
    def test_no_q_systems_no_penalty(self):
        """Ships without Q have no condition penalty."""
        s = ShipSystems.parse("SSAL")
        assert s.shooting_mods() == ToHitMod(target_delta=0)

    def test_q_intact_no_penalty(self):
        """Intact Q does not impose a penalty."""
        s = ShipSystems.parse("SSALQ")
        assert s.shooting_mods() == ToHitMod(target_delta=0)

    def test_q_destroyed_applies_penalty(self):
        """All Q destroyed → -2 target_delta."""
        s = ShipSystems.parse("SSALQ")
        s = s.apply_damage(4)   # destroy S S A L, Q still intact
        assert s.shooting_mods() == ToHitMod(target_delta=0)
        s = s.apply_damage(1)   # destroy Q
        assert s.shooting_mods() == ToHitMod(target_delta=-2)

    def test_partial_q_destroyed_no_penalty(self):
        """Only some Q destroyed — crew can still function normally."""
        s = ShipSystems.parse("SSQQL")
        s = s.apply_damage(3)   # destroys S S Q; one Q remains
        assert s.shooting_mods() == ToHitMod(target_delta=0)

    def test_all_multiple_q_destroyed_applies_penalty(self):
        """All Q destroyed when ship has multiple Q units."""
        s = ShipSystems.parse("SSQQL")
        s = s.apply_damage(4)   # destroys S S Q Q; L intact
        assert s.shooting_mods() == ToHitMod(target_delta=-2)

    def test_shooting_mods_stacks_with_future_conditions(self):
        """shooting_mods returns a single combined ToHitMod (extensibility check)."""
        mod = ShipSystems.parse("Q").shooting_mods()
        assert isinstance(mod, ToHitMod)


# ---------------------------------------------------------------------------
# End-to-end: penalty applied in combat resolution
# ---------------------------------------------------------------------------

class TestQPenaltyInCombat:
    """Verify that the -2 penalty reduces effective to-hit in resolve_large_fire."""

    def _enc(self, attacker_systems: str, target_systems: str) -> Encounter:
        a = _ship("A1", "A", Hex(0, 0), Facing.D1,  attacker_systems)
        b = _ship("B1", "B", Hex(1, 0), Facing.D4,  target_systems)
        return Encounter.start(BattleState(ships={"A1": a, "B1": b}))

    def test_no_penalty_normal_to_hit(self):
        """With Q intact, to-hit is unaffected by condition."""
        from tactical.combat import resolve_large_fire
        from tactical.weapons import WeaponType
        enc = self._enc("SQQL", "SSAL")
        battle = enc.battle
        # Roll 5 vs a laser at range 1 — just confirm no exception and event generated
        _, ev = resolve_large_fire(battle, attacker_id="A1", target_id="B1",
                                   weapon=WeaponType.LASER, rng=FixedRNG(5))
        assert ev.to_hit is not None
        normal_to_hit = ev.to_hit

    def test_q_destroyed_lowers_to_hit_by_2(self):
        """With all Q destroyed, to_hit is 2 lower than baseline."""
        from tactical.combat import resolve_large_fire
        from tactical.weapons import WeaponType

        # Build a ship with Q then pre-destroy the Q
        intact_systems = ShipSystems.parse("SQQL")
        # Destroy S, then both Q → L remains
        damaged = intact_systems.apply_damage(3)  # S, Q, Q destroyed
        a = ShipState(
            ship_id="A1", owner_id="A", pos=Hex(0, 0), facing=Facing.D1,
            mp=5, turn_cost=FG.turn_cost, turn_charge=0,
            systems=damaged, hull_type=FG,
        )
        b = _ship("B1", "B", Hex(1, 0), Facing.D4, "SSAL")
        battle = BattleState(ships={"A1": a, "B1": b})

        _, ev_damaged = resolve_large_fire(battle, attacker_id="A1", target_id="B1",
                                           weapon=WeaponType.LASER, rng=FixedRNG(5))

        # Compare against intact attacker
        a_intact = _ship("A1", "A", Hex(0, 0), Facing.D1, "SQQL")
        battle_intact = BattleState(ships={"A1": a_intact, "B1": b})
        _, ev_intact = resolve_large_fire(battle_intact, attacker_id="A1",
                                          target_id="B1",
                                          weapon=WeaponType.LASER, rng=FixedRNG(5))

        assert ev_intact.to_hit is not None
        assert ev_damaged.to_hit is not None
        assert ev_damaged.to_hit == ev_intact.to_hit - 2
