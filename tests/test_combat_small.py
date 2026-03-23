"""Tests for the COMBAT_SMALL phase: dogfights, attack runs, and phase machinery."""
from __future__ import annotations

import random

import pytest

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.encounter import Encounter, Phase
from tactical.facing import Facing
from tactical.fighter_combat import (
    resolve_all_dogfights,
    resolve_attack_run,
    resolve_combat_small,
)
from tactical.fighter_events import AttackRunEvent, DogfightEvent
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems
from tactical.fighter_class import F1
from tactical.squadron_state import FighterLoadout, SquadronState
from tactical.turn_orders import InterceptOrder, MoveOrder, StrikeOrder
from tactical.weapons import WeaponType


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _interceptor(sq_id: str, owner: str, pos: Hex, strength: int = 5) -> SquadronState:
    return SquadronState(
        squadron_id=sq_id, owner_id=owner, pos=pos,
        strength=strength, max_strength=5,
        loadout=FighterLoadout(
            fighter_class=F1,
            internal=(WeaponType.GUN,),
        ),
        endurance=20, max_endurance=20,
    )


def _strike_fighter(sq_id: str, owner: str, pos: Hex, strength: int = 5, shots: int = 2) -> SquadronState:
    return SquadronState(
        squadron_id=sq_id, owner_id=owner, pos=pos,
        strength=strength, max_strength=5,
        loadout=FighterLoadout(
            fighter_class=F1,
            internal=(WeaponType.LASER,),
            external=(WeaponType.STANDARD_MISSILE, WeaponType.STANDARD_MISSILE),
            external_shots_remaining=shots,
        ),
        endurance=20, max_endurance=20,
    )


def _ship(ship_id: str, owner: str, pos: Hex, systems: str = "SSSAAALL") -> ShipState:
    return ShipState(
        ship_id=ship_id, owner_id=owner,
        pos=pos, facing=Facing.N,
        mp=5, turn_cost=2,
        systems=ShipSystems.parse(systems),
    )


def _ship_no_systems(ship_id: str, owner: str, pos: Hex) -> ShipState:
    return ShipState(
        ship_id=ship_id, owner_id=owner,
        pos=pos, facing=Facing.N,
        mp=5, turn_cost=2,
    )


# ---------------------------------------------------------------------------
# Dogfight resolution
# ---------------------------------------------------------------------------

class TestDogfights:
    def test_dogfight_produces_events_for_both_sides(self):
        sq_a = _interceptor("A1", "A", Hex(0, 0))
        sq_b = _interceptor("B1", "B", Hex(0, 0))
        battle = BattleState(ships={}, squadrons={"A1": sq_a, "B1": sq_b})
        battle2, events = resolve_all_dogfights(battle, rng=random.Random(1))
        dogfights = [ev for ev in events if isinstance(ev, DogfightEvent)]
        attacker_ids = {ev.attacker_id for ev in dogfights}
        assert attacker_ids == {"A1", "B1"}

    def test_dogfight_causes_casualties(self):
        """High-roll RNG forces many hits; both squads should take casualties."""
        sq_a = _interceptor("A1", "A", Hex(0, 0))
        sq_b = _interceptor("B1", "B", Hex(0, 0))
        battle = BattleState(ships={}, squadrons={"A1": sq_a, "B1": sq_b})
        # Seed 42 gives varied rolls; at least some hits expected with to-hit 9 (7+2)
        battle2, events = resolve_all_dogfights(battle, rng=random.Random(42))
        dogfights = [ev for ev in events if isinstance(ev, DogfightEvent)]
        total_casualties = sum(ev.total_casualties for ev in dogfights)
        assert total_casualties > 0

    def test_dogfight_simultaneity(self):
        """Both sides fire from the snapshot — a destroyed squad still fires back."""
        # A1 is at strength 1 and will be one-shot; B1 should still receive fire.
        sq_a = _interceptor("A1", "A", Hex(0, 0), strength=1)
        sq_b = _interceptor("B1", "B", Hex(0, 0), strength=5)
        battle = BattleState(ships={}, squadrons={"A1": sq_a, "B1": sq_b})

        # Force all rolls to 1 (guaranteed hits)
        class AlwaysOne:
            def randint(self, a, b):
                return 1

        battle2, events = resolve_all_dogfights(battle, rng=AlwaysOne())
        # Both A1 and B1 should have fired (two DogfightEvents)
        dogfights = [ev for ev in events if isinstance(ev, DogfightEvent)]
        attacker_ids = {ev.attacker_id for ev in dogfights}
        assert attacker_ids == {"A1", "B1"}

    def test_dogfight_higher_mvr_bonus(self):
        """Interceptor (MVR 4) vs laden strike (MVR 1) has +3 to-hit bonus."""
        sq_a = _interceptor("A1", "A", Hex(0, 0))          # MVR 4
        sq_b = _strike_fighter("B1", "B", Hex(0, 0), shots=2)  # MVR 3-2=1
        battle = BattleState(ships={}, squadrons={"A1": sq_a, "B1": sq_b})

        battle2, events = resolve_all_dogfights(battle, rng=random.Random(1))
        dogfights = [ev for ev in events if isinstance(ev, DogfightEvent)]
        a_fires = [ev for ev in dogfights if ev.attacker_id == "A1"]
        b_fires = [ev for ev in dogfights if ev.attacker_id == "B1"]
        assert len(a_fires) == 1 and len(b_fires) == 1

        # A's mvr_delta should be positive (4 - 1 = 3)
        assert a_fires[0].mvr_delta > b_fires[0].mvr_delta

    def test_missiles_cannot_be_used_in_dogfight(self):
        """R weapons are skipped in dogfights (can_target_fighters=False)."""
        sq_a = _strike_fighter("A1", "A", Hex(0, 0))  # L internal, R external
        sq_b = _interceptor("B1", "B", Hex(0, 0))
        battle = BattleState(ships={}, squadrons={"A1": sq_a, "B1": sq_b})
        battle2, events = resolve_all_dogfights(battle, rng=random.Random(1))
        dogfights = [ev for ev in events if isinstance(ev, DogfightEvent)]
        a_fires = [ev for ev in dogfights if ev.attacker_id == "A1"]
        assert len(a_fires) == 1
        # Only L shots should appear — no R shots
        for shot in a_fires[0].shots:
            assert shot.weapon != WeaponType.STANDARD_MISSILE

    def test_no_dogfight_when_same_side(self):
        """Two friendly squadrons in the same hex don't fight each other."""
        sq_a = _interceptor("A1", "A", Hex(0, 0))
        sq_b = _interceptor("A2", "A", Hex(0, 0))
        battle = BattleState(ships={}, squadrons={"A1": sq_a, "A2": sq_b})
        battle2, events = resolve_all_dogfights(battle, rng=random.Random(1))
        assert events == []

    def test_destroyed_squadron_removed(self):
        """A squad reduced to 0 strength is removed from battle."""
        sq_a = _interceptor("A1", "A", Hex(0, 0), strength=5)
        sq_b = _interceptor("B1", "B", Hex(0, 0), strength=1)

        class AlwaysOne:
            def randint(self, a, b):
                return 1

        battle = BattleState(ships={}, squadrons={"A1": sq_a, "B1": sq_b})
        battle2, events = resolve_all_dogfights(battle, rng=AlwaysOne())
        # B1 had strength 1 and was hit by guaranteed hits → destroyed
        assert "B1" not in battle2.squadrons

    def test_weakest_enemy_targeted(self):
        """In a 1v2 dogfight, the attacker targets the weakest enemy."""
        sq_a  = _interceptor("A1", "A", Hex(0, 0), strength=5)
        sq_b1 = _interceptor("B1", "B", Hex(0, 0), strength=2)  # weakest
        sq_b2 = _interceptor("B2", "B", Hex(0, 0), strength=4)
        battle = BattleState(
            ships={}, squadrons={"A1": sq_a, "B1": sq_b1, "B2": sq_b2}
        )
        battle2, events = resolve_all_dogfights(battle, rng=random.Random(1))
        dogfights = [ev for ev in events if isinstance(ev, DogfightEvent)]
        a_events = [ev for ev in dogfights if ev.attacker_id == "A1"]
        assert len(a_events) == 1
        assert a_events[0].target_id == "B1"


# ---------------------------------------------------------------------------
# Attack run resolution
# ---------------------------------------------------------------------------

class TestAttackRun:
    def test_attack_run_returns_event(self):
        sq = _strike_fighter("A1", "A", Hex(0, 0))
        ship = _ship_no_systems("B1", "B", Hex(0, 0))
        battle = BattleState(ships={"B1": ship}, squadrons={"A1": sq})
        battle2, ev = resolve_attack_run(battle, attacker_id="A1",
                                         target_ship_id="B1", rng=random.Random(1))
        assert isinstance(ev, AttackRunEvent)
        assert ev.attacker_id == "A1"
        assert ev.target_id == "B1"

    def test_pd_fires_at_fighters(self):
        """Ship with PD kills some fighters before they can fire."""
        sq = _strike_fighter("A1", "A", Hex(0, 0), strength=5)
        ship = _ship("B1", "B", Hex(0, 0), systems="DSSAA")

        class AlwaysOne:
            def randint(self, a, b):
                return 1

        battle = BattleState(ships={"B1": ship}, squadrons={"A1": sq})
        battle2, ev = resolve_attack_run(battle, attacker_id="A1",
                                          target_ship_id="B1", rng=AlwaysOne())
        assert ev.pd_hits > 0
        assert ev.fighters_killed_by_pd > 0
        assert ev.surviving_strength < 5

    def test_no_pd_no_casualties(self):
        """Ship with no PD: all fighters survive to fire."""
        sq = _strike_fighter("A1", "A", Hex(0, 0), strength=5)
        ship = _ship_no_systems("B1", "B", Hex(0, 0))
        battle = BattleState(ships={"B1": ship}, squadrons={"A1": sq})
        _, ev = resolve_attack_run(battle, attacker_id="A1",
                                    target_ship_id="B1", rng=random.Random(1))
        assert ev.fighters_killed_by_pd == 0
        assert ev.surviving_strength == 5

    def test_external_shot_expended_after_run(self):
        """External shots_remaining decrements by 1 after an attack run."""
        sq = _strike_fighter("A1", "A", Hex(0, 0), shots=2)
        ship = _ship_no_systems("B1", "B", Hex(0, 0))
        battle = BattleState(ships={"B1": ship}, squadrons={"A1": sq})
        battle2, _ = resolve_attack_run(battle, attacker_id="A1",
                                         target_ship_id="B1", rng=random.Random(1))
        assert battle2.squadrons["A1"].loadout.external_shots_remaining == 1

    def test_no_external_fire_when_empty(self):
        """No external weapons fire when shots_remaining == 0."""
        sq = _strike_fighter("A1", "A", Hex(0, 0), shots=0)
        ship = _ship_no_systems("B1", "B", Hex(0, 0))
        battle = BattleState(ships={"B1": ship}, squadrons={"A1": sq})
        _, ev = resolve_attack_run(battle, attacker_id="A1",
                                    target_ship_id="B1", rng=random.Random(1))
        weapon_types = {s.weapon for s in ev.weapon_shots}
        assert WeaponType.STANDARD_MISSILE not in weapon_types

    def test_hits_damage_ship_systems(self):
        """Guaranteed-hit attack run applies damage to the target ship."""
        sq = _strike_fighter("A1", "A", Hex(0, 0), strength=5, shots=0)
        ship = _ship("B1", "B", Hex(0, 0), systems="AAAA")

        class AlwaysOne:
            def randint(self, a, b):
                return 1

        battle = BattleState(ships={"B1": ship}, squadrons={"A1": sq})
        battle2, ev = resolve_attack_run(battle, attacker_id="A1",
                                          target_ship_id="B1", rng=AlwaysOne())
        assert ev.total_ship_damage > 0
        # Verify systems actually changed
        orig_compact = ship.systems.render_compact()
        new_compact  = battle2.ships["B1"].systems.render_compact()
        assert orig_compact != new_compact


# ---------------------------------------------------------------------------
# Full resolve_combat_small
# ---------------------------------------------------------------------------

class TestResolveCombatSmall:
    def test_strike_moves_squad_to_ship_hex(self):
        sq = _interceptor("A1", "A", Hex(0, 0))
        ship = _ship_no_systems("B1", "B", Hex(3, 0))
        battle = BattleState(ships={"B1": ship}, squadrons={"A1": sq})
        orders = {"A1": StrikeOrder(target_id="B1")}
        battle2, _ = resolve_combat_small(battle, orders, rng=random.Random(1))
        assert battle2.squadrons["A1"].pos == Hex(3, 0)

    def test_intercept_moves_squad_to_patrol_hex(self):
        sq = _interceptor("A1", "A", Hex(0, 0))
        battle = BattleState(ships={}, squadrons={"A1": sq})
        orders = {"A1": InterceptOrder(patrol_hex=Hex(5, 0))}
        battle2, _ = resolve_combat_small(battle, orders, rng=random.Random(1))
        assert battle2.squadrons["A1"].pos == Hex(5, 0)

    def test_unreachable_strike_target_moves_partial(self):
        """Squad with MP 10 cannot reach a hex 20 away — advances as far as MP allows."""
        sq = _interceptor("A1", "A", Hex(0, 0))  # effective_mp=10
        ship = _ship_no_systems("B1", "B", Hex(20, 0))
        battle = BattleState(ships={"B1": ship}, squadrons={"A1": sq})
        orders = {"A1": StrikeOrder(target_id="B1")}
        battle2, _ = resolve_combat_small(battle, orders, rng=random.Random(1))
        # Should have moved 10 hexes toward (20,0)
        assert battle2.squadrons["A1"].pos == Hex(10, 0)
        # Did not reach target — no attack run
        assert not any(hasattr(e, "target_id") and e.target_id == "B1"
                       and type(e).__name__ == "AttackRunEvent"
                       for e in _)

    def test_strike_on_ship_triggers_attack_run(self):
        sq = _strike_fighter("A1", "A", Hex(0, 0), shots=0)
        ship = _ship_no_systems("B1", "B", Hex(3, 0))
        battle = BattleState(ships={"B1": ship}, squadrons={"A1": sq})
        orders = {"A1": StrikeOrder(target_id="B1")}
        _, events = resolve_combat_small(battle, orders, rng=random.Random(1))
        assert any(isinstance(ev, AttackRunEvent) for ev in events)

    def test_engaged_squad_cannot_make_attack_run(self):
        """A striker that moves into a hex with an enemy squadron is locked in a
        dogfight and cannot make its attack run that turn."""
        sq_a = _strike_fighter("A1", "A", Hex(0, 0), shots=0)
        sq_b = _interceptor("B1", "B", Hex(3, 0))   # enemy interceptor at ship hex
        ship  = _ship_no_systems("B_ship", "B", Hex(3, 0))
        battle = BattleState(
            ships={"B_ship": ship},
            squadrons={"A1": sq_a, "B1": sq_b},
        )
        orders = {"A1": StrikeOrder(target_id="B_ship")}
        _, events = resolve_combat_small(battle, orders, rng=random.Random(1))
        # Should see a dogfight event, no attack run
        assert any(isinstance(ev, DogfightEvent) for ev in events)
        assert not any(isinstance(ev, AttackRunEvent) for ev in events)


# ---------------------------------------------------------------------------
# Encounter phase machinery
# ---------------------------------------------------------------------------

def _two_ship_battle_with_squadrons():
    """Two ships + one interceptor per side, ships facing each other."""
    ship_a = ShipState(ship_id="a1", owner_id="A", pos=Hex(0, 0),
                       facing=Facing.N, mp=6, turn_cost=3,
                       systems=ShipSystems.parse("SSALL"))
    ship_b = ShipState(ship_id="b1", owner_id="B", pos=Hex(0, 10),
                       facing=Facing.S, mp=6, turn_cost=3,
                       systems=ShipSystems.parse("SSALL"))
    sq_a = _interceptor("F_A", "A", Hex(1, 0))
    sq_b = _interceptor("F_B", "B", Hex(1, 9))
    return BattleState(
        ships={"a1": ship_a, "b1": ship_b},
        squadrons={"F_A": sq_a, "F_B": sq_b},
    )


class TestEncounterCombatSmall:
    def _reach_combat_small(self) -> Encounter:
        battle = _two_ship_battle_with_squadrons()
        enc = Encounter.start(battle, rng=random.Random(1))
        enc, _ = enc.commit_movement("A", random.Random(0))
        enc, _ = enc.commit_movement("B", random.Random(0))
        enc, _ = enc.commit_fire("A", random.Random(1))
        enc, _ = enc.commit_fire("B", random.Random(1))
        assert enc.phase == Phase.COMBAT_SMALL, enc.phase
        return enc

    def test_fire_resolution_stops_at_combat_small_when_squads_exist(self):
        enc = self._reach_combat_small()
        assert enc.phase == Phase.COMBAT_SMALL

    def test_stage_squadron_order_wrong_side_raises(self):
        enc = self._reach_combat_small()
        with pytest.raises(PermissionError):
            enc.stage_squadron_order("B", "F_A", InterceptOrder(patrol_hex=Hex(2, 0)))

    def test_stage_squadron_order_unknown_squadron_raises(self):
        enc = self._reach_combat_small()
        with pytest.raises(KeyError):
            enc.stage_squadron_order("A", "GHOST", InterceptOrder(patrol_hex=Hex(0, 0)))

    def test_first_commit_does_not_resolve(self):
        enc = self._reach_combat_small()
        enc2, events = enc.commit_squadron_orders("A", random.Random(1))
        assert enc2.phase == Phase.COMBAT_SMALL
        assert events == []

    def test_both_commits_trigger_resolution(self):
        enc = self._reach_combat_small()
        enc = enc.stage_squadron_order("A", "F_A", InterceptOrder(patrol_hex=Hex(1, 0)))
        enc = enc.stage_squadron_order("B", "F_B", InterceptOrder(patrol_hex=Hex(1, 9)))
        enc, _ = enc.commit_squadron_orders("A", random.Random(1))
        enc, _ = enc.commit_squadron_orders("B", random.Random(1))
        assert enc.phase == Phase.MOVE_SUBMISSION

    def test_no_squads_skips_combat_small(self):
        """Encounters with no squadrons auto-advance past COMBAT_SMALL."""
        from tests.test_encounter_phases import _two_ship_battle
        battle = _two_ship_battle()
        enc = Encounter.start(battle, rng=random.Random(1))
        enc, _ = enc.commit_movement("A", random.Random(0))
        enc, _ = enc.commit_movement("B", random.Random(0))
        enc, _ = enc.commit_fire("A", random.Random(1))
        enc, _ = enc.commit_fire("B", random.Random(1))
        assert enc.phase == Phase.MOVE_SUBMISSION

    def test_override_squadron_order_before_commit(self):
        enc = self._reach_combat_small()
        enc = enc.stage_squadron_order("A", "F_A", InterceptOrder(patrol_hex=Hex(2, 0)))
        enc = enc.stage_squadron_order("A", "F_A", InterceptOrder(patrol_hex=Hex(3, 0)))
        assert enc._squadron_orders["F_A"].patrol_hex == Hex(3, 0)

    def test_double_commit_raises(self):
        enc = self._reach_combat_small()
        enc, _ = enc.commit_squadron_orders("A", random.Random(1))
        with pytest.raises(PermissionError):
            enc.commit_squadron_orders("A", random.Random(1))


# ---------------------------------------------------------------------------
# MoveOrder — move without intercepting
# ---------------------------------------------------------------------------

class TestMoveOrder:
    def test_move_order_reaches_dest(self):
        """MoveOrder moves the squadron to dest (within MP)."""
        sq = _interceptor("A1", "A", Hex(0, 0))  # effective_mp = 10
        battle = BattleState(ships={}, squadrons={"A1": sq})
        orders = {"A1": MoveOrder(dest=Hex(5, 0))}
        battle2, _ = resolve_combat_small(battle, orders, rng=random.Random(1))
        assert battle2.squadrons["A1"].pos == Hex(5, 0)

    def test_move_order_does_not_engage_enemies(self):
        """A MoveOrder that passes through an enemy hex does not trigger a dogfight."""
        sq_a = _interceptor("A1", "A", Hex(0, 0))
        sq_b = _interceptor("B1", "B", Hex(3, 0))  # on A1's path
        battle = BattleState(ships={}, squadrons={"A1": sq_a, "B1": sq_b})
        orders = {"A1": MoveOrder(dest=Hex(6, 0))}
        _, events = resolve_combat_small(battle, orders, rng=random.Random(1))
        assert not any(isinstance(ev, DogfightEvent) for ev in events)

    def test_move_order_limited_by_mp(self):
        """If dest is beyond MP, the squadron moves as far as MP allows."""
        sq = _interceptor("A1", "A", Hex(0, 0))  # effective_mp = 10
        battle = BattleState(ships={}, squadrons={"A1": sq})
        orders = {"A1": MoveOrder(dest=Hex(20, 0))}
        battle2, _ = resolve_combat_small(battle, orders, rng=random.Random(1))
        # Should have advanced exactly 10 hexes
        assert battle2.squadrons["A1"].pos == Hex(10, 0)


# ---------------------------------------------------------------------------
# max_intercept_radius — voluntary radius cap on InterceptOrder
# ---------------------------------------------------------------------------

class TestMaxInterceptRadius:
    def test_radius_cap_prevents_distant_intercept(self):
        """With max_intercept_radius=1, an enemy landing at distance 3 from patrol hex is not intercepted."""
        # A1 patrols Hex(0,0) with radius cap 1.
        # Bship is at Hex(3,0); B1 starts at Hex(8,0) and strikes toward Hex(3,0).
        # B1 ends up at Hex(3,0) — distance 3 from A1's patrol hex, outside the cap.
        sq_a = _interceptor("A1", "A", Hex(0, 0))
        sq_b = _interceptor("B1", "B", Hex(8, 0))
        ship_b = _ship_no_systems("Bship", "B", Hex(3, 0))
        battle = BattleState(ships={"Bship": ship_b}, squadrons={"A1": sq_a, "B1": sq_b})
        orders = {
            "A1": InterceptOrder(patrol_hex=Hex(0, 0), max_intercept_radius=1),
            "B1": StrikeOrder(target_id="Bship"),
        }
        _, events = resolve_combat_small(battle, orders, rng=random.Random(1))
        # A1 should not have intercepted — B1 is beyond the radius cap
        dogfights = [ev for ev in events if isinstance(ev, DogfightEvent)]
        assert not any(ev.attacker_id == "A1" or ev.target_id == "A1" for ev in dogfights)

    def test_radius_cap_allows_close_intercept(self):
        """With max_intercept_radius=2, an enemy at distance 1 from patrol hex IS intercepted."""
        # A1 is at patrol Hex(0,0), enemy B1 moves to Hex(1,0) — within cap of 2.
        sq_a = _interceptor("A1", "A", Hex(0, 0))
        sq_b = _interceptor("B1", "B", Hex(5, 0))
        ship_b = _ship_no_systems("Bship", "B", Hex(1, 0))
        battle = BattleState(ships={"Bship": ship_b}, squadrons={"A1": sq_a, "B1": sq_b})
        orders = {
            "A1": InterceptOrder(patrol_hex=Hex(0, 0), max_intercept_radius=2),
            "B1": StrikeOrder(target_id="Bship"),
        }
        _, events = resolve_combat_small(battle, orders, rng=random.Random(1))
        dogfights = [ev for ev in events if isinstance(ev, DogfightEvent)]
        # A1 should have engaged B1
        assert any("A1" in (ev.attacker_id, ev.target_id) for ev in dogfights)

    def test_no_cap_uses_full_radius(self):
        """Without max_intercept_radius, full radius is used (default behaviour)."""
        sq_a = _interceptor("A1", "A", Hex(0, 0))  # effective_mp=10 → radius=11
        sq_b = _interceptor("B1", "B", Hex(5, 0))
        ship_b = _ship_no_systems("Bship", "B", Hex(1, 0))
        battle = BattleState(ships={"Bship": ship_b}, squadrons={"A1": sq_a, "B1": sq_b})
        orders = {
            "A1": InterceptOrder(patrol_hex=Hex(0, 0)),  # no cap
            "B1": StrikeOrder(target_id="Bship"),
        }
        _, events = resolve_combat_small(battle, orders, rng=random.Random(1))
        dogfights = [ev for ev in events if isinstance(ev, DogfightEvent)]
        assert any("A1" in (ev.attacker_id, ev.target_id) for ev in dogfights)
