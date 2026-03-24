"""Tests for carrier launch and recovery mechanics, including Bl slot enforcement."""
from __future__ import annotations

import dataclasses
import random

import pytest

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.encounter import Encounter, Phase
from tactical.events import RecoveryEvent
from tactical.facing import Facing
from tactical.fighter_class import F1
from tactical.hull_types import HULL_TYPES
CV = HULL_TYPES["CA"]
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems
from tactical.squadron_state import FighterLoadout, SquadronState
from tactical.turn_orders import RecoverOrder
from tactical.weapons import WeaponType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CV_2BL = "SSSAAAFQ(I)(I)BhBhBlBlR"  # 2 Bh, 2 Bl
_CV_1BL = "SSSAAAFQ(I)(I)BhBhBlR"    # 2 Bh, 1 Bl
_CV_1BH = "SSSAAAFQ(I)(I)BhBlR"      # 1 Bh, 1 Bl


def _carrier(ship_id: str, owner: str, pos: Hex, systems: str = _CV_2BL) -> ShipState:
    return ShipState(
        ship_id=ship_id, owner_id=owner, pos=pos, facing=Facing.N,
        mp=4, turn_cost=CV.turn_cost, turn_charge=0,
        systems=ShipSystems.parse(systems), hull_type=CV,
    )


def _squadron(sq_id: str, owner: str, pos: Hex, docked_at: str | None = None) -> SquadronState:
    return SquadronState(
        squadron_id=sq_id, owner_id=owner, pos=pos,
        strength=5, max_strength=5,
        loadout=FighterLoadout(fighter_class=F1, internal=(WeaponType.GUN,)),
        endurance=10, max_endurance=10,
        docked_at=docked_at,
    )


def _advance_to_combat_small(battle: BattleState) -> Encounter:
    """Advance through MOVE and FIRE phases with no orders, reaching COMBAT_SMALL."""
    enc = Encounter.start(battle, rng=random.Random(1))
    enc, _ = enc.commit_movement("A", random.Random(1))
    enc, _ = enc.commit_movement("B", random.Random(1))
    enc, _ = enc.commit_fire("A", random.Random(1))
    enc, _ = enc.commit_fire("B", random.Random(1))
    assert enc.phase == Phase.COMBAT_SMALL
    return enc


# ---------------------------------------------------------------------------
# Recovery tests
# ---------------------------------------------------------------------------

class TestCarrierRecovery:
    def test_recovery_docks_squadron(self):
        """A squadron at the carrier's hex can recover successfully."""
        carrier_a = _carrier("A1", "A", Hex(0, 0))
        carrier_b = _carrier("B1", "B", Hex(20, 0))
        sq = _squadron("AF1", "A", Hex(0, 0))
        battle = BattleState(
            ships={"A1": carrier_a, "B1": carrier_b},
            squadrons={"AF1": sq},
        )

        enc = _advance_to_combat_small(battle)
        enc = enc.stage_squadron_order("A", "AF1", RecoverOrder(carrier_id="A1"))
        enc, events = enc.commit_squadron_orders("A", random.Random(1))
        enc, events2 = enc.commit_squadron_orders("B", random.Random(1))

        assert enc.battle.squadrons["AF1"].docked_at == "A1"
        assert any(isinstance(e, RecoveryEvent) and e.squadron_id == "AF1"
                   for e in events + events2)

    def test_recovery_requires_squadron_at_carrier_hex(self):
        """Squadron not co-located with carrier — recovery silently ignored."""
        carrier_a = _carrier("A1", "A", Hex(0, 0))
        carrier_b = _carrier("B1", "B", Hex(20, 0))
        sq = _squadron("AF1", "A", Hex(5, 0))   # different hex
        battle = BattleState(
            ships={"A1": carrier_a, "B1": carrier_b},
            squadrons={"AF1": sq},
        )

        enc = _advance_to_combat_small(battle)
        enc = enc.stage_squadron_order("A", "AF1", RecoverOrder(carrier_id="A1"))
        enc, ev1 = enc.commit_squadron_orders("A", random.Random(1))
        enc, ev2 = enc.commit_squadron_orders("B", random.Random(1))

        assert enc.battle.squadrons["AF1"].docked_at is None
        assert not any(isinstance(e, RecoveryEvent) for e in ev1 + ev2)

    def test_second_recovery_blocked_by_single_bl(self):
        """Carrier with 1 Bl can recover at most 1 squadron per turn."""
        carrier_a = _carrier("A1", "A", Hex(0, 0), systems=_CV_1BL)
        carrier_b = _carrier("B1", "B", Hex(20, 0))
        sq1 = _squadron("AF1", "A", Hex(0, 0))
        sq2 = _squadron("AF2", "A", Hex(0, 0))
        battle = BattleState(
            ships={"A1": carrier_a, "B1": carrier_b},
            squadrons={"AF1": sq1, "AF2": sq2},
        )

        enc = _advance_to_combat_small(battle)
        enc = enc.stage_squadron_order("A", "AF1", RecoverOrder(carrier_id="A1"))
        enc = enc.stage_squadron_order("A", "AF2", RecoverOrder(carrier_id="A1"))
        enc, ev1 = enc.commit_squadron_orders("A", random.Random(1))
        enc, ev2 = enc.commit_squadron_orders("B", random.Random(1))

        recovery_events = [e for e in ev1 + ev2 if isinstance(e, RecoveryEvent)]
        assert len(recovery_events) == 1   # only one Bl slot available

    def test_two_recoveries_allowed_with_two_bl(self):
        """Carrier with 2 Bl can recover 2 squadrons in the same turn."""
        carrier_a = _carrier("A1", "A", Hex(0, 0), systems=_CV_2BL)
        carrier_b = _carrier("B1", "B", Hex(20, 0))
        sq1 = _squadron("AF1", "A", Hex(0, 0))
        sq2 = _squadron("AF2", "A", Hex(0, 0))
        battle = BattleState(
            ships={"A1": carrier_a, "B1": carrier_b},
            squadrons={"AF1": sq1, "AF2": sq2},
        )

        enc = _advance_to_combat_small(battle)
        enc = enc.stage_squadron_order("A", "AF1", RecoverOrder(carrier_id="A1"))
        enc = enc.stage_squadron_order("A", "AF2", RecoverOrder(carrier_id="A1"))
        enc, ev1 = enc.commit_squadron_orders("A", random.Random(1))
        enc, ev2 = enc.commit_squadron_orders("B", random.Random(1))

        recovery_events = [e for e in ev1 + ev2 if isinstance(e, RecoveryEvent)]
        assert len(recovery_events) == 2

    def test_recovery_blocked_when_no_empty_bh(self):
        """No empty Bh — recovery silently ignored even when Bl is available."""
        # Carrier has 1 Bh, 1 Bl; pre-dock AF2 to fill the Bh
        carrier_a = _carrier("A1", "A", Hex(0, 0), systems=_CV_1BH)
        carrier_b = _carrier("B1", "B", Hex(20, 0))
        sq_free   = _squadron("AF1", "A", Hex(0, 0))
        sq_docked = _squadron("AF2", "A", Hex(0, 0), docked_at="A1")
        # Occupy the Bh in the systems state
        filled_sys = carrier_a.systems.dock_squadron("AF2")
        carrier_a  = dataclasses.replace(carrier_a, systems=filled_sys)

        battle = BattleState(
            ships={"A1": carrier_a, "B1": carrier_b},
            squadrons={"AF1": sq_free, "AF2": sq_docked},
        )

        enc = _advance_to_combat_small(battle)
        enc = enc.stage_squadron_order("A", "AF1", RecoverOrder(carrier_id="A1"))
        enc, ev1 = enc.commit_squadron_orders("A", random.Random(1))
        enc, ev2 = enc.commit_squadron_orders("B", random.Random(1))

        assert enc.battle.squadrons["AF1"].docked_at is None
        assert not any(isinstance(e, RecoveryEvent) for e in ev1 + ev2)
