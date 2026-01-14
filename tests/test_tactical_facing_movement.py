import pytest

from sim.hexgrid import Hex
from tactical.facing import Facing, FACING_OFFSETS
from tactical.movement import forward_neighbor, step_forward, compute_move_forward


def test_facing_offsets_match_expected_order():
    assert FACING_OFFSETS == (
        (0, 1),
        (1, 0),
        (1, -1),
        (0, -1),
        (-1, 0),
        (-1, 1),
    )


def test_rotate_left_right_wraps_and_is_inverse():
    f = Facing.D0
    assert f.right(1) == Facing.D1
    assert f.left(1) == Facing.D5

    for i in range(6):
        fi = Facing.from_int(i)
        assert fi.left(1).right(1) == fi
        assert fi.right(1).left(1) == fi

    assert Facing.D0.right(6) == Facing.D0
    assert Facing.D3.left(6) == Facing.D3


def test_forward_neighbor_moves_correctly_in_axial_coords():
    origin = Hex(0, 0)

    # Using the canonical offset table for determinism.
    expected = [Hex(dq, dr) for dq, dr in FACING_OFFSETS]

    actual = [forward_neighbor(origin, Facing.from_int(i)) for i in range(6)]
    assert [(h.q, h.r) for h in actual] == [(h.q, h.r) for h in expected]


def test_step_forward_is_pure_and_deterministic():
    start = Hex(2, -1)
    end = step_forward(start, Facing.N, steps=3)
    assert (end.q, end.r) == (2, 2)

    same = step_forward(start, Facing.D0, steps=0)
    assert (same.q, same.r) == (2, -1)

    with pytest.raises(ValueError):
        step_forward(start, Facing.D0, steps=-1)


def test_move_forward_spends_mp_and_returns_result():
    start = Hex(0, 0)
    end, mp2, res = compute_move_forward(start, Facing.D2, mp=5, steps=2)
    assert (end.q, end.r) == (2, -2)
    assert mp2 == 3
    assert res.start == start
    assert res.end == end
    assert res.facing == Facing.D2
    assert res.cost == 2

    with pytest.raises(ValueError):
        compute_move_forward(start, Facing.D2, mp=1, steps=2)
