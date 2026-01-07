import pytest
from sim.turn_engine import GameState
from sim.map import GameMap
from sim.hexgrid import Hex
from sim.units import PlayerID, UnitType, UnitGroup
from sim.targeting import focus_fire


def make_game_with_groups(groups, active_name="A"):
    game = GameState()
    game.game_map = GameMap(q_min=-4, q_max=4, r_min=-4, r_max=4)

    # Make sure these player objects are the same ones referenced by groups
    players = {g.owner for g in groups}
    # Also allow lookup by name
    name_to_player = {p.name: p for p in players}
    game.players = list(players)

    game.active_player = name_to_player.get(active_name, next(iter(players)))

    game.targeting_policy = focus_fire

    for g in groups:
        game.add_group(g)

    return game


def mk_unit_type(
    name: str,
    initiative: str,
    attack: int,
    defense: int,
    hull: int,
    movement: int = 3,
    is_combatant: bool = True,
):
    return UnitType(
        name=name,
        max_groups=99,
        movement=movement,
        is_combatant=is_combatant,
        initiative=initiative,
        attack=attack,
        defense=defense,
        hull=hull,
    )


def mk_group(gid: str, owner: PlayerID, ut: UnitType, count: int, loc: Hex, tactics: int = 0):
    # tech_level is sometimes optional in your code; if required, add tech_level=0 here
    g = UnitGroup(gid, owner, ut, count=count, location=loc)
    # Ensure tactics exists even if older constructor doesn’t take it
    setattr(g, "tactics", tactics)
    # Ensure damage exists (combat will set it if missing, but tests may inspect)
    if not hasattr(g, "damage"):
        setattr(g, "damage", 0)
    return g


def test_initiative_order_a_before_b():
    A = PlayerID("A")
    B = PlayerID("B")
    loc = Hex(0, 0)

    # A attacker: attack 11 vs target defense 0 => to_hit 11 (no hits ever)
    ut_A = mk_unit_type("A_ship", initiative="A", attack=11, defense=0, hull=2)
    # B attacker: attack 1 vs target defense 0 => to_hit 1 (always hit)
    ut_B = mk_unit_type("B_ship", initiative="B", attack=1, defense=0, hull=2)

    gA = mk_group("GA", A, ut_A, count=1, loc=loc, tactics=0)
    gB = mk_group("GB", B, ut_B, count=1, loc=loc, tactics=0)

    game = make_game_with_groups([gA, gB], active_name="A")
    events = game.resolve_combat(A, loc)

    joined = "\n".join(events)
    assert "Round 1 begins." in joined
    # Ensure we see Initiative A volley before Initiative B volley
    idx_A = joined.find("Initiative A")
    idx_B = joined.find("Initiative B")
    assert idx_A != -1 and idx_B != -1 and idx_A < idx_B


def test_tactics_breaks_tie_within_initiative():
    A = PlayerID("A")
    B = PlayerID("B")
    loc = Hex(0, 0)

    ut_fast = mk_unit_type("A_tactics1", initiative="A", attack=11, defense=0, hull=3)
    ut_slow = mk_unit_type("A_tactics0", initiative="A", attack=1, defense=0, hull=3)

    g1 = mk_group("G1", A, ut_fast, count=1, loc=loc, tactics=1)  # fires first, but misses
    g2 = mk_group("G2", B, ut_slow, count=1, loc=loc, tactics=0)  # fires second, always hits

    game = make_game_with_groups([g1, g2], active_name="A")
    events = game.resolve_combat(A, loc)

    joined = "\n".join(events)
    # Within Initiative A, tactics 1 should appear before tactics 0
    idx_t1 = joined.find("Tactics 1")
    idx_t0 = joined.find("Tactics 0")
    assert idx_t1 != -1 and idx_t0 != -1 and idx_t1 < idx_t0


def test_focus_fire_priority_remaining_hull_then_defense_then_attack():
    A = PlayerID("A")
    B = PlayerID("B")
    loc = Hex(0, 0)

    attacker_ut = mk_unit_type("Attacker", initiative="C", attack=5, defense=0, hull=2)
    attacker = mk_group("ATK", A, attacker_ut, count=1, loc=loc)

    # Enemy 1: more damaged (lower remaining hull) => should be chosen first
    e1_ut = mk_unit_type("E1", initiative="C", attack=1, defense=9, hull=3)
    e1 = mk_group("E1", B, e1_ut, count=1, loc=loc)
    e1.damage = 2  # remaining hull = 1

    e2_ut = mk_unit_type("E2", initiative="C", attack=999, defense=0, hull=2)
    e2 = mk_group("E2", B, e2_ut, count=1, loc=loc)
    e2.damage = 0  # remaining hull = 2

    assert focus_fire(attacker, [e1, e2]).group_id == "E1"

    # Now equal remaining hull; lowest defense wins
    e3_ut = mk_unit_type("E3", initiative="C", attack=1, defense=1, hull=3)
    e3 = mk_group("E3", B, e3_ut, count=1, loc=loc)
    e3.damage = 0

    e4_ut = mk_unit_type("E4", initiative="C", attack=999, defense=2, hull=3)
    e4 = mk_group("E4", B, e4_ut, count=1, loc=loc)
    e4.damage = 0

    assert focus_fire(attacker, [e3, e4]).group_id == "E3"

    # Now equal remaining hull and defense; highest attack wins
    e5_ut = mk_unit_type("E5", initiative="C", attack=5, defense=1, hull=3)
    e5 = mk_group("E5", B, e5_ut, count=1, loc=loc)
    e5.damage = 0

    e6_ut = mk_unit_type("E6", initiative="C", attack=2, defense=1, hull=3)
    e6 = mk_group("E6", B, e6_ut, count=1, loc=loc)
    e6.damage = 0

    assert focus_fire(attacker, [e5, e6]).group_id == "E5"


def test_combat_runs_multiple_rounds_and_ends_with_winner():
    A = PlayerID("A")
    B = PlayerID("B")
    loc = Hex(0, 0)

    # to_hit = max(1, attack - defense). Set attack=1, defense=0 => to_hit=1 => always hits.
    ut_A = mk_unit_type("A_ship", initiative="A", attack=1, defense=0, hull=2)
    ut_B = mk_unit_type("B_ship", initiative="A", attack=1, defense=0, hull=3)  # survives round 1

    gA = mk_group("GA", A, ut_A, count=2, loc=loc, tactics=0)  # 2 shots per volley
    gB = mk_group("GB", B, ut_B, count=1, loc=loc, tactics=0)  # 1 shot per volley

    game = make_game_with_groups([gA, gB], active_name="A")
    events = game.resolve_combat(A, loc)
    joined = "\n".join(events)

    assert "Round 1 begins." in joined
    assert "Round 2 begins." in joined  # proves multi-round happened
    assert game.get_group("GB") is None  # B should die by round 2
    assert game.get_group("GA") is not None  # A should survive
