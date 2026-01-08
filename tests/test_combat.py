from sim.hexgrid import Hex
from sim.combat.resolver import collect_battles


def test_collect_battles_returns_empty_when_no_contest(game):
    battles = collect_battles(game, combat_sites=set())
    assert battles == []


from sim.hexgrid import Hex
from sim.combat.resolver import collect_battles


def test_collect_battles_detects_contested_hex(game, ids):
    # Put A's existing combatant at the hex
    a1 = game.get_group(ids["A_SHIP"])
    hx = Hex(1, 0)
    a1.location = hx

    # Add a B combatant at the same hex (do NOT rely on the decoy)
    from sim.units import UnitType, UnitGroup
    B = game.players[1]

    b_combat_type = UnitType(
        "Raider",
        max_groups=10,
        movement=3,
        is_combatant=True,
        initiative="C",
        attack=1,
        defense=0,
        hull=1,
    )
    b_ship = UnitGroup(game.allocate_group_id(B), B, b_combat_type, count=1, location=hx)
    game.add_group(b_ship)

    battles = collect_battles(game, combat_sites={hx})
    assert len(battles) == 1
    assert battles[0].location == hx
    assert len(battles[0].owners) == 2
    assert all(owner in battles[0].groups_by_owner for owner in battles[0].owners)


def test_collect_battles_is_deterministic_order(game):
    from sim.units import UnitType, UnitGroup

    A = game.players[0]
    B = game.players[1]

    hx1 = Hex(0, 0)
    hx2 = Hex(1, -1)

    # Create two contested hexes using ONLY combatants we add here
    a_type = UnitType("A_Combat", max_groups=10, movement=3, is_combatant=True,
                      initiative="C", attack=1, defense=0, hull=1)
    b_type = UnitType("B_Combat", max_groups=10, movement=3, is_combatant=True,
                      initiative="C", attack=1, defense=0, hull=1)

    # hx1: A combatant + B combatant
    a1 = UnitGroup(game.allocate_group_id(A), A, a_type, count=1, location=hx1)
    b1 = UnitGroup(game.allocate_group_id(B), B, b_type, count=1, location=hx1)
    game.add_group(a1)
    game.add_group(b1)

    # hx2: A combatant + B combatant
    a2 = UnitGroup(game.allocate_group_id(A), A, a_type, count=1, location=hx2)
    b2 = UnitGroup(game.allocate_group_id(B), B, b_type, count=1, location=hx2)
    game.add_group(a2)
    game.add_group(b2)

    battles = collect_battles(game, combat_sites={hx2, hx1})
    assert [b.location for b in battles] == [hx1, hx2]  # sorted by (q,r)


def test_collect_battles_ignores_noncombat_only_owner(game, ids):
    from sim.units import UnitType, UnitGroup

    a = game.players[0]
    b = game.players[1]
    hx = Hex(0, 0)

    # A combatant present
    a_ship = game.get_group(ids["A_SHIP"])
    a_ship.location = hx

    # B noncombatant present
    b_decoy = game.get_group(ids["B_DECOY"])
    b_decoy.location = hx
    assert not b_decoy.unit_type.is_combatant

    battles = collect_battles(game, combat_sites={hx})
    assert battles == []
