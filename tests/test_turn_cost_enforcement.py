"""Tests for turn-cost enforcement: staging validation and correct turn_charge
tracking through movement resolution."""
from __future__ import annotations

import pytest

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.encounter import Encounter
from tactical.facing import Facing
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FixedRNG:
    def randint(self, a: int, b: int) -> int:
        return 1  # always hit; fine for movement-only tests


def _fg(ship_id: str, owner: str, pos: Hex, facing: Facing, mp: int = 5,
        turn_charge: int = 0) -> ShipState:
    """Frigate with turn_cost=2 and a simple system strip."""
    return ShipState(
        ship_id=ship_id,
        owner_id=owner,
        pos=pos,
        facing=facing,
        mp=mp,
        turn_cost=2,
        turn_charge=turn_charge,
        systems=ShipSystems.parse("SAL"),
    )


def _enc_two_ships(a: ShipState, b: ShipState) -> Encounter:
    battle = BattleState(ships={a.ship_id: a, b.ship_id: b})
    return Encounter.start(battle)


# ---------------------------------------------------------------------------
# stage_move validation
# ---------------------------------------------------------------------------

class TestStageMoveValidation:
    def test_direct_move_within_mp_accepted(self):
        a = _fg("A1", "A", Hex(0, 0), Facing.D1, mp=5)
        b = _fg("B1", "B", Hex(6, 0), Facing.D4, mp=5)
        enc = _enc_two_ships(a, b)
        # Move 3 hexes forward (NE), same facing — should be fine.
        dest = Hex(3, 0)
        enc2 = enc.stage_move("A", "A1", dest, Facing.D1)
        assert enc2._move_orders["A1"].dest == dest

    def test_direct_move_exceeding_mp_rejected(self):
        a = _fg("A1", "A", Hex(0, 0), Facing.D1, mp=3)
        b = _fg("B1", "B", Hex(6, 0), Facing.D4, mp=3)
        enc = _enc_two_ships(a, b)
        # Distance 5 > mp 3.
        with pytest.raises(ValueError, match="exceeds MP capacity"):
            enc.stage_move("A", "A1", Hex(5, 0), Facing.D1)

    def test_facing_change_costs_extra_mp(self):
        # FG turn_cost=2, charge=0. One facing change needs 2 extra MP.
        a = _fg("A1", "A", Hex(0, 0), Facing.D1, mp=2, turn_charge=0)
        b = _fg("B1", "B", Hex(6, 0), Facing.D4, mp=5)
        enc = _enc_two_ships(a, b)
        # Move 1 hex AND change facing by 1: minimum cost = max(1, 1*2-0) = 2. OK.
        enc.stage_move("A", "A1", Hex(1, 0), Facing.D2)

    def test_facing_change_exceeds_budget_rejected(self):
        # FG turn_cost=2, charge=0, mp=1. Need 2 MP for one facing change.
        a = _fg("A1", "A", Hex(0, 0), Facing.D1, mp=1, turn_charge=0)
        b = _fg("B1", "B", Hex(6, 0), Facing.D4, mp=5)
        enc = _enc_two_ships(a, b)
        # Same hex (dist=0), but change facing by 1: cost = max(0, 2) = 2 > mp 1.
        with pytest.raises(ValueError, match="exceeds MP capacity"):
            enc.stage_move("A", "A1", Hex(0, 0), Facing.D2)

    def test_existing_charge_reduces_turn_cost(self):
        # FG turn_cost=2, charge=1 already. One facing change: cost = max(0, 2-1) = 1.
        a = _fg("A1", "A", Hex(0, 0), Facing.D1, mp=1, turn_charge=1)
        b = _fg("B1", "B", Hex(6, 0), Facing.D4, mp=5)
        enc = _enc_two_ships(a, b)
        # With charge=1 already: turning costs only 1 more MP. Should accept.
        enc.stage_move("A", "A1", Hex(0, 0), Facing.D2)

    def test_two_facing_changes_require_double_cost(self):
        # FG turn_cost=2, charge=0, mp=3. Two facing changes: 2*2=4 > 3.
        a = _fg("A1", "A", Hex(0, 0), Facing.D0, mp=3, turn_charge=0)
        b = _fg("B1", "B", Hex(6, 0), Facing.D4, mp=5)
        enc = _enc_two_ships(a, b)
        # Facing D0 → D2: facing_delta=2, turns_needed=2, cost=max(0,4)=4 > mp=3.
        with pytest.raises(ValueError, match="exceeds MP capacity"):
            enc.stage_move("A", "A1", Hex(0, 0), Facing.D2)

    def test_draft_move_accepted_and_preserves_final_charge(self):
        a = _fg("A1", "A", Hex(0, 0), Facing.D1, mp=5, turn_charge=0)
        b = _fg("B1", "B", Hex(6, 0), Facing.D4, mp=5)
        enc = _enc_two_ships(a, b)
        # Simulate a draft: mp_used=4, final turn_charge=2 (moved 4 hexes, 1 turn made,
        # remaining charge after turn = 2 from last 2 hexes).
        dest = Hex(4, 0)
        enc2 = enc.stage_move(
            "A", "A1", dest, Facing.D1,
            path_cost=4,
            final_turn_charge=2,
        )
        assert enc2._move_orders["A1"].final_turn_charge == 2


# ---------------------------------------------------------------------------
# turn_charge after movement resolution
# ---------------------------------------------------------------------------

class TestTurnChargeAfterResolution:
    """Verify that _resolve_movement applies final_turn_charge correctly."""

    def _resolve(self, a: ShipState, b: ShipState, dest: Hex,
                 facing: Facing, *, path_cost=None, final_turn_charge=None):
        enc = _enc_two_ships(a, b)
        kwargs = {}
        if path_cost is not None:
            kwargs["path_cost"] = path_cost
        if final_turn_charge is not None:
            kwargs["final_turn_charge"] = final_turn_charge
        enc = enc.stage_move("A", "A1", dest, facing, **kwargs)
        enc = enc.stage_move("B", "B1", b.pos, b.facing)  # B stays in place
        rng = FixedRNG()
        enc, _ = enc.commit_movement("A", rng)
        enc, _ = enc.commit_movement("B", rng)
        return enc.battle.ships["A1"]

    def test_straight_movement_caps_turn_charge_not_wraps(self):
        # FG turn_cost=2, charge=0, moves 5 hexes straight (no turns).
        # Correct final charge: min(0+5, 2) = 2 (capped, not 5%2=1).
        a = _fg("A1", "A", Hex(0, 0), Facing.D1, mp=5, turn_charge=0)
        b = _fg("B1", "B", Hex(10, 0), Facing.D4, mp=0)
        ship = self._resolve(a, b, Hex(5, 0), Facing.D1)
        assert ship.turn_charge == 2  # capped at turn_cost, NOT 5%2=1

    def test_exact_draft_charge_propagated(self):
        # Draft produces final_turn_charge=1 (set explicitly).
        a = _fg("A1", "A", Hex(0, 0), Facing.D1, mp=5, turn_charge=0)
        b = _fg("B1", "B", Hex(10, 0), Facing.D4, mp=0)
        ship = self._resolve(
            a, b, Hex(3, 0), Facing.D1,
            path_cost=3,
            final_turn_charge=1,
        )
        assert ship.turn_charge == 1

    def test_draft_charge_zero_after_turn(self):
        # Draft: move 2 (charge→2), turn (charge→0).  final draft charge = 0.
        a = _fg("A1", "A", Hex(0, 0), Facing.D1, mp=5, turn_charge=0)
        b = _fg("B1", "B", Hex(10, 0), Facing.D4, mp=0)
        ship = self._resolve(
            a, b, Hex(2, 0), Facing.D2,  # turned right once after 2 hexes
            path_cost=2,
            final_turn_charge=0,
        )
        assert ship.turn_charge == 0

    def test_direct_hex_charge_no_facing_change(self):
        # Direct hex, no facing change: charge = min(0+3, 2) = 2.
        a = _fg("A1", "A", Hex(0, 0), Facing.D1, mp=5, turn_charge=0)
        b = _fg("B1", "B", Hex(10, 0), Facing.D4, mp=0)
        ship = self._resolve(a, b, Hex(3, 0), Facing.D1)
        assert ship.turn_charge == 2

    def test_direct_hex_charge_one_facing_change(self):
        # Direct hex, 1 facing change: cost=max(0,2)=2, final_charge=min(0+2-2,2)=0.
        a = _fg("A1", "A", Hex(0, 0), Facing.D1, mp=5, turn_charge=0)
        b = _fg("B1", "B", Hex(10, 0), Facing.D4, mp=0)
        ship = self._resolve(a, b, Hex(0, 0), Facing.D2)
        assert ship.turn_charge == 0

    def test_direct_hex_excess_movement_beyond_turn_caps_charge(self):
        # FG, move 3 hexes, 1 facing change: cost=max(3,2)=3.
        # final_charge = min(0+3-1*2, 2) = min(1, 2) = 1.
        a = _fg("A1", "A", Hex(0, 0), Facing.D1, mp=5, turn_charge=0)
        b = _fg("B1", "B", Hex(10, 0), Facing.D4, mp=0)
        ship = self._resolve(a, b, Hex(3, 0), Facing.D2)
        assert ship.turn_charge == 1

    def test_turn_charge_persists_into_next_turn(self):
        # After movement resolves, charge should allow (or deny) a turn next round.
        # Ship ends with charge=2=turn_cost => can turn next round without extra MP.
        a = _fg("A1", "A", Hex(0, 0), Facing.D1, mp=5, turn_charge=0)
        b = _fg("B1", "B", Hex(10, 0), Facing.D4, mp=0)
        enc = _enc_two_ships(a, b)
        enc = enc.stage_move("A", "A1", Hex(3, 0), Facing.D1)  # 3 fwd, no turn
        enc = enc.stage_move("B", "B1", b.pos, b.facing)
        rng = FixedRNG()
        enc, _ = enc.commit_movement("A", rng)
        enc, _ = enc.commit_movement("B", rng)
        # Advance through combat phases to reach next MOVE_SUBMISSION.
        enc, _ = enc.commit_fire("A", rng)
        enc, _ = enc.commit_fire("B", rng)
        # Now in next MOVE_SUBMISSION. Check A1's restored charge.
        a1 = enc.battle.ships["A1"]
        assert a1.turn_charge == 2  # carried over from previous move (capped at turn_cost)
