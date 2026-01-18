import random

from tactical.missile_volley import resolve_missile_volley


def test_pd_does_nothing_when_no_hits():
    rng = random.Random(1)
    res = resolve_missile_volley(
        incoming_hits=0,
        pd_shots=6,
        pd_to_hit=3,
        rng=rng,
    )
    assert res.remaining_hits == 0
    assert res.intercepted == 0


def test_pd_limited_by_shots_per_volley():
    rng = random.Random(1)
    res = resolve_missile_volley(
        incoming_hits=10,
        pd_shots=3,
        pd_to_hit=10,  # guaranteed hits under roll<=target semantics
        rng=rng,
    )
    assert res.intercepted == 3
    assert res.remaining_hits == 7


def test_pd_overwhelmed_by_many_hits():
    rng = random.Random(2)
    res = resolve_missile_volley(
        incoming_hits=20,
        pd_shots=6,
        pd_to_hit=3,
        rng=rng,
    )
    assert 0 <= res.intercepted <= 6
    assert res.remaining_hits == res.incoming_hits - res.intercepted


def test_pd_exactly_intercepts_all_hits_if_lucky():
    rng = random.Random(0)
    res = resolve_missile_volley(
        incoming_hits=2,
        pd_shots=5,
        pd_to_hit=10,  # guaranteed hits
        rng=rng,
    )
    assert res.remaining_hits == 0
