from sim.combat.targeting import focus_fire
from sim.units import PlayerID, UnitType, UnitGroup
from sim.hexgrid import Hex


def _mk(owner, gid, hull, defense, attack, damage=0):
    ut = UnitType(
        name=f"T{gid}",
        max_groups=99,
        movement=3,
        is_combatant=True,
        initiative="C",
        attack=attack,
        defense=defense,
        hull=hull,
    )
    g = UnitGroup(gid, owner, ut, count=1, location=Hex(0, 0))
    # If you have damage tracking, set it; otherwise this is harmless
    setattr(g, "damage", damage)
    return g


def test_focus_fire_prefers_lowest_remaining_hull():
    A = PlayerID("A")
    B = PlayerID("B")

    attacker = _mk(A, "ATK", hull=3, defense=1, attack=2)

    # remaining hull: E1 = 1 (hull3 damage2), E2 = 2 (hull2 damage0)
    e1 = _mk(B, "E1", hull=3, defense=9, attack=9, damage=2)
    e2 = _mk(B, "E2", hull=2, defense=0, attack=0, damage=0)

    target = focus_fire(attacker, [e1, e2])
    assert target.group_id == "E1"


def test_focus_fire_tiebreaks_by_lowest_defense_then_highest_attack():
    A = PlayerID("A")
    B = PlayerID("B")

    attacker = _mk(A, "ATK", hull=3, defense=1, attack=2)

    # Same remaining hull for both => compare defense (lower wins)
    e1 = _mk(B, "E1", hull=3, defense=1, attack=1, damage=0)
    e2 = _mk(B, "E2", hull=3, defense=2, attack=999, damage=0)
    assert focus_fire(attacker, [e1, e2]).group_id == "E1"

    # Same remaining hull and same defense => higher attack wins
    e3 = _mk(B, "E3", hull=3, defense=1, attack=5, damage=0)
    e4 = _mk(B, "E4", hull=3, defense=1, attack=2, damage=0)
    assert focus_fire(attacker, [e3, e4]).group_id == "E3"
