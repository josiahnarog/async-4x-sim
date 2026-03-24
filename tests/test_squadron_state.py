"""Tests for FighterLoadout, SquadronState, and related weapon additions."""
from __future__ import annotations

import pytest

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.fighter_class import F1, FighterClass
from tactical.ship_state import ShipState
from tactical.facing import Facing
from tactical.squadron_state import FighterLoadout, SquadronState
from tactical.weapons import WEAPONS, WeaponType, GUN, LASER, STANDARD_MISSILE


# ---------------------------------------------------------------------------
# Weapon table additions
# ---------------------------------------------------------------------------

class TestGunWeapon:
    def test_gun_in_weapons_dict(self):
        assert WeaponType.GUN in WEAPONS

    def test_gun_anti_fighter_modifier(self):
        assert GUN.anti_fighter_modifier == 2

    def test_gun_can_target_fighters(self):
        assert GUN.can_target_fighters is True

    def test_gun_damage_vs_ship(self):
        # Gun does 2 damage at close range, 1 at medium; half vs shields/armor
        assert GUN.damage_at(0) == 2
        assert GUN.damage_at(3) == 1
        assert GUN.shield_multiplier == 0.5
        assert GUN.armor_multiplier == 0.5

    def test_missile_cannot_target_fighters(self):
        assert STANDARD_MISSILE.can_target_fighters is False

    def test_laser_anti_fighter_modifier_zero(self):
        assert LASER.anti_fighter_modifier == 0


# ---------------------------------------------------------------------------
# FighterLoadout — derived stats
# ---------------------------------------------------------------------------

class TestFighterLoadout:
    def _interceptor(self) -> FighterLoadout:
        return FighterLoadout(
            fighter_class=F1,
            internal=(WeaponType.GUN,),
        )

    def _strike(self, shots: int = 2) -> FighterLoadout:
        return FighterLoadout(
            fighter_class=F1,
            internal=(WeaponType.LASER,),
            external=(WeaponType.STANDARD_MISSILE, WeaponType.STANDARD_MISSILE),
            external_shots_remaining=shots,
        )

    def test_interceptor_no_external_penalty(self):
        lo = self._interceptor()
        assert lo.effective_mp  == 10
        assert lo.effective_mvr == 4

    def test_strike_mp_penalty_while_loaded(self):
        lo = self._strike(shots=2)
        assert lo.effective_mp == 8  # 10 - 2

    def test_strike_mvr_penalty_per_shot(self):
        assert self._strike(shots=2).effective_mvr == 2   # 4 - 2
        assert self._strike(shots=1).effective_mvr == 3   # 4 - 1

    def test_strike_penalty_gone_when_expended(self):
        lo = self._strike(shots=0)
        assert lo.effective_mp  == 10  # no penalty
        assert lo.effective_mvr == 4   # no penalty

    def test_expend_external_shot_decrements(self):
        lo = self._strike(shots=2)
        lo2 = lo.expend_external_shot()
        assert lo2.external_shots_remaining == 1

    def test_expend_external_shot_raises_when_empty(self):
        lo = self._strike(shots=0)
        with pytest.raises(ValueError):
            lo.expend_external_shot()

    def test_effective_mvr_floor_zero(self):
        low_mvr_class = FighterClass(designation="T1", name="Test", base_mvr=1, base_mp=6)
        lo = FighterLoadout(fighter_class=low_mvr_class,
                            internal=(WeaponType.GUN,),
                            external=(WeaponType.STANDARD_MISSILE,
                                      WeaponType.STANDARD_MISSILE),
                            external_shots_remaining=4)
        assert lo.effective_mvr == 0  # floor at 0, not negative


# ---------------------------------------------------------------------------
# SquadronState
# ---------------------------------------------------------------------------

def _basic_squadron(
    pos: Hex = Hex(0, 0),
    strength: int = 5,
    shots: int = 0,
) -> SquadronState:
    loadout = FighterLoadout(
        fighter_class=F1,
        internal=(WeaponType.GUN, WeaponType.GUN),
        external=(WeaponType.STANDARD_MISSILE,) if shots > 0 else (),
        external_shots_remaining=shots,
    )
    return SquadronState(
        squadron_id="S1", owner_id="A",
        pos=pos,
        strength=strength, max_strength=5,
        loadout=loadout,
        endurance=20, max_endurance=20,
    )


class TestSquadronState:
    def test_is_destroyed_false_when_alive(self):
        sq = _basic_squadron(strength=1)
        assert not sq.is_destroyed()

    def test_is_destroyed_true_at_zero(self):
        sq = _basic_squadron(strength=0)
        assert sq.is_destroyed()

    def test_take_casualties_reduces_strength(self):
        sq = _basic_squadron(strength=5)
        sq2 = sq.take_casualties(2)
        assert sq2.strength == 3

    def test_take_casualties_floors_at_zero(self):
        sq = _basic_squadron(strength=2)
        sq2 = sq.take_casualties(10)
        assert sq2.strength == 0

    def test_expend_external_shot(self):
        sq = _basic_squadron(shots=2)
        sq2 = sq.expend_external_shot()
        assert sq2.loadout.external_shots_remaining == 1

    def test_decrement_endurance(self):
        sq = _basic_squadron()
        sq2 = sq.decrement_endurance()
        assert sq2.endurance == 19

    def test_decrement_endurance_floors_at_zero(self):
        import dataclasses
        sq = dataclasses.replace(_basic_squadron(), endurance=0)
        assert sq.decrement_endurance().endurance == 0

    def test_move_to_updates_pos(self):
        sq = _basic_squadron(pos=Hex(0, 0))
        sq2 = sq.move_to(Hex(3, 1))
        assert sq2.pos == Hex(3, 1)

    def test_effective_mvr_delegates_to_loadout(self):
        sq = _basic_squadron(shots=2)
        assert sq.effective_mvr == sq.loadout.effective_mvr

    def test_effective_mp_delegates_to_loadout(self):
        sq = _basic_squadron(shots=2)
        assert sq.effective_mp == sq.loadout.effective_mp


# ---------------------------------------------------------------------------
# BattleState squadron integration
# ---------------------------------------------------------------------------

class TestBattleStateSquadrons:
    def _battle_with_squadron(self) -> BattleState:
        ship = ShipState(
            ship_id="A1", owner_id="A",
            pos=Hex(0, 0), facing=Facing.N,
            mp=5, turn_cost=2,
        )
        sq_a = _basic_squadron(pos=Hex(2, 0))
        sq_b = SquadronState(
            squadron_id="S2", owner_id="B",
            pos=Hex(2, 0),  # same hex as S1 — they are engaged
            strength=5, max_strength=5,
            loadout=FighterLoadout(fighter_class=F1,
                                   internal=(WeaponType.LASER,)),
            endurance=20, max_endurance=20,
        )
        return BattleState(
            ships={"A1": ship},
            squadrons={"S1": sq_a, "S2": sq_b},
        )

    def test_default_squadrons_empty(self):
        ship = ShipState(ship_id="A1", owner_id="A",
                         pos=Hex(0, 0), facing=Facing.N, mp=5, turn_cost=2)
        battle = BattleState(ships={"A1": ship})
        assert battle.squadrons == {}

    def test_with_squadron_adds_entry(self):
        ship = ShipState(ship_id="A1", owner_id="A",
                         pos=Hex(0, 0), facing=Facing.N, mp=5, turn_cost=2)
        battle = BattleState(ships={"A1": ship})
        sq = _basic_squadron()
        battle2 = battle.with_squadron(sq)
        assert "S1" in battle2.squadrons

    def test_without_squadron_removes_entry(self):
        b = self._battle_with_squadron()
        b2 = b.without_squadron("S1")
        assert "S1" not in b2.squadrons
        assert "S2" in b2.squadrons

    def test_engaged_squadrons_detects_shared_hex(self):
        b = self._battle_with_squadron()
        engaged = b.engaged_squadrons()
        # Both S1 and S2 are at Hex(2,0), different owners → both appear
        engaged_ids = {sq.squadron_id for sq, _ in engaged}
        assert engaged_ids == {"S1", "S2"}

    def test_squadrons_at_returns_correct_units(self):
        b = self._battle_with_squadron()
        at_2_0 = b.squadrons_at(Hex(2, 0))
        assert {sq.squadron_id for sq in at_2_0} == {"S1", "S2"}
        assert b.squadrons_at(Hex(99, 0)) == []

    def test_squadron_ids_sorted_deterministic(self):
        b = self._battle_with_squadron()
        ids = b.squadron_ids_sorted()
        assert ids == sorted(ids)
