from sim.hexgrid import Hex
from sim.combat import collect_battles


def test_collect_battles_returns_empty_when_no_contest(game):
    battles = collect_battles(game, combat_sites=set())
    assert battles == []


def test_collect_battles_detects_contested_hex(game):

    # Force a contested hex without running submit: put G1 and G2 in same location
    g1 = game.get_group("G1")
    g2 = game.get_group("G2")
    hx = Hex(1, 0)
    g1.location = hx
    g2.location = hx

    battles = collect_battles(game, combat_sites={hx})
    assert len(battles) == 1
    assert battles[0].location == hx
    assert len(battles[0].owners) == 2
    assert all(owner in battles[0].groups_by_owner for owner in battles[0].owners)


def test_collect_battles_is_deterministic_order(game):

    # Create two contested hexes
    g1 = game.get_group("G1")
    g2 = game.get_group("G2")

    hx1 = Hex(0, 0)
    hx2 = Hex(1, -1)

    # Make G2 contested with G1 at hx1, and also add a new enemy at hx2
    g1.location = hx1
    g2.location = hx1

    # Add a second enemy group at hx2
    from sim.units import UnitType, UnitGroup
    B = game.players[1]
    decoy = UnitType("Decoy", max_groups=10, movement=3)
    g3 = UnitGroup("G3", B, decoy, count=1, location=hx2)
    game.add_group(g3)

    # Add a friendly group at hx2 too
    A = game.players[0]
    scout = UnitType("Scout", max_groups=10, movement=3)
    g4 = UnitGroup("G4", A, scout, count=1, location=hx2)
    game.add_group(g4)

    battles = collect_battles(game, combat_sites={hx2, hx1})
    assert [b.location for b in battles] == [hx1, hx2]  # sorted by (q,r)
