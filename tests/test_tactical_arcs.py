"""Tests for tactical/arcs.py — bearing math and arc classification."""
import pytest
from tactical.arcs import Arc, arc_of, relative_bearing, REAR_ARC_TO_HIT_BONUS
from tactical.facing import Facing


# ---------------------------------------------------------------------------
# relative_bearing: spot-check each of the 6 directions when facing N (0)
# ---------------------------------------------------------------------------

class TestRelativeBearingFacingN:
    """With facing=N (0), absolute bearing == relative bearing."""

    def test_dead_ahead(self):
        assert relative_bearing(Facing.N, 0, +1) == 0

    def test_sixty_right(self):
        assert relative_bearing(Facing.N, +1, 0) == 1

    def test_one_twenty_right(self):
        assert relative_bearing(Facing.N, +1, -1) == 2

    def test_dead_astern(self):
        assert relative_bearing(Facing.N, 0, -1) == 3

    def test_one_twenty_left(self):
        assert relative_bearing(Facing.N, -1, 0) == 4

    def test_sixty_left(self):
        assert relative_bearing(Facing.N, -1, +1) == 5


class TestRelativeBearingFacingNE:
    """Rotate the frame: facing=NE (1). Dead-ahead is the NE neighbour (+1, 0)."""

    def test_dead_ahead_is_ne_offset(self):
        assert relative_bearing(Facing.NE, +1, 0) == 0

    def test_dead_astern_is_sw_offset(self):
        # SW = (-1, 0): directly behind when facing NE
        assert relative_bearing(Facing.NE, -1, 0) == 3

    def test_sixty_right_is_se_offset(self):
        # SE = (+1, -1): 60° right of NE
        assert relative_bearing(Facing.NE, +1, -1) == 1

    def test_sixty_left_is_n_offset(self):
        # N = (0, +1): 60° left of NE
        assert relative_bearing(Facing.NE, 0, +1) == 5


# ---------------------------------------------------------------------------
# arc_of: front vs rear
# ---------------------------------------------------------------------------

class TestArcOf:
    """arc_of(observer_facing, dq, dr) -> Arc."""

    @pytest.mark.parametrize("dq,dr", [
        (0, +1),   # N — dead ahead
        (+1, 0),   # NE — 60° right (front)
        (-1, +1),  # NW — 60° left (front)
    ])
    def test_front_arc(self, dq, dr):
        assert arc_of(Facing.N, dq, dr) == Arc.FRONT

    def test_rear_arc_dead_astern(self):
        # S = (0, -1): only dead astern (bearing 3) is the blind spot
        assert arc_of(Facing.N, 0, -1) == Arc.REAR

    @pytest.mark.parametrize("dq,dr", [
        (+1, -1),  # SE — 120° right (bearing 2, not blind spot)
        (-1, 0),   # SW — 120° left (bearing 4, not blind spot)
    ])
    def test_rear_flanks_are_front_arc(self, dq, dr):
        # Blind spot is 60° only; flanking-rear hexes are still fireable
        assert arc_of(Facing.N, dq, dr) == Arc.FRONT


# ---------------------------------------------------------------------------
# arc_of: attacker-in-target-rear (for to-hit bonus / PD suppression)
# ---------------------------------------------------------------------------

class TestAttackerInTargetRear:
    """Check the pattern used in combat.py: arc_of(target.facing, -dq, -dr)."""

    def test_attacker_behind_target_is_rear(self):
        # A at (0,0) facing N; B at (0, +1) facing N (away from A).
        # dq=0, dr=+1 (B is north of A).  From B's POV, A is at (-dq,-dr)=(0,-1) = south = dead astern.
        dq, dr = 0, +1
        target_facing = Facing.N
        assert arc_of(int(target_facing), -dq, -dr) == Arc.REAR

    def test_attacker_in_front_of_target_is_front(self):
        # A at (0,0) facing N; B at (0, -1) facing N (toward A).
        # From B's POV, A is at (0,+1) = dead ahead.
        dq, dr = 0, -1
        target_facing = Facing.N
        assert arc_of(int(target_facing), -dq, -dr) == Arc.FRONT


# ---------------------------------------------------------------------------
# Constant sanity check
# ---------------------------------------------------------------------------

def test_rear_arc_bonus_is_positive():
    assert REAR_ARC_TO_HIT_BONUS > 0
