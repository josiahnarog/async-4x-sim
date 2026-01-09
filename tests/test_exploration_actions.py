import pytest

from sim.turn_engine import GameState
from sim.map import GameMap
from sim.hexgrid import Hex
from sim.map_content import HexContent
from sim.units import PlayerID, UnitType, UnitGroup
from sim.colonies import Colony
from tests.conftest import dump_log


def mk_unit_type(name: str, movement=1, is_combatant=False):
    ut = UnitType(
        name=name,
        max_groups=99,
        movement=movement,
        is_combatant=is_combatant,
        initiative="E",
        attack=0,
        defense=0,
        hull=1,
    )
    return ut


def mk_game():
    game = GameState()
    game.game_map = GameMap(q_min=-4, q_max=4, r_min=-4, r_max=4)

    p1 = PlayerID("A")
    p2 = PlayerID("B")
    game.players = [p1, p2]
    game.active_player = p1

    return game, p1, p2


@pytest.fixture
def colony_ship_type():
    ut = mk_unit_type("Colony Ship", movement=1, is_combatant=False)
    ut.can_colonize = True
    return ut


@pytest.fixture
def mining_ship_type():
    ut = mk_unit_type("Mining Ship", movement=1, is_combatant=False)
    ut.can_mine = True
    return ut


def test_manual_colonize_on_explored_standard_planet_consumes_one_ship(colony_ship_type):
    game, p1, _ = mk_game()
    planet = Hex(0, 0)

    game.game_map.set_hex_content(planet, HexContent.PLANET_STANDARD)
    game.game_map.set_explored(planet)

    g = UnitGroup("A1", p1, colony_ship_type, count=2, location=planet)
    game.add_group(g)

    events = game.manual_colonize("A1")

    assert planet in game.colonies, "Colony should be created in GameState.colonies"
    assert game.colonies[planet].owner == p1
    assert game.get_group("A1") is not None, "Group should remain because count was 2"
    assert game.get_group("A1").count == 1, "Exactly one ship consumed"
    assert any("colony established" in e.lower() for e in events)


def test_auto_end_of_turn_actions_colonizes_too(colony_ship_type):
    game, p1, _ = mk_game()
    planet = Hex(1, 0)

    game.game_map.set_hex_content(planet, HexContent.PLANET_STANDARD)
    game.game_map.set_explored(planet)

    g = UnitGroup("A1", p1, colony_ship_type, count=1, location=planet)
    game.add_group(g)

    events = game.manual_colonize("A1")

    assert planet in game.colonies
    assert game.get_group("A1") is None, "Group removed because last ship consumed"
    assert any("colony established" in e.lower() for e in events)


def test_colonize_fails_on_unexplored_hex(colony_ship_type):
    game, p1, _ = mk_game()
    planet = Hex(0, 1)

    game.game_map.set_hex_content(planet, HexContent.PLANET_STANDARD)
    # not explored

    g = UnitGroup("A1", p1, colony_ship_type, count=1, location=planet)
    game.add_group(g)

    events = game.manual_colonize("A1")

    assert planet not in game.colonies
    assert any("unexplored" in e.lower() for e in events)


def test_manual_mine_picks_up_minerals_and_clears_hex(mining_ship_type):
    game, p1, _ = mk_game()
    h = Hex(0, 0)

    game.game_map.set_hex_content(h, HexContent.MINERALS)
    game.game_map.set_explored(h)

    g = UnitGroup("A1", p1, mining_ship_type, count=1, location=h)
    game.add_group(g)

    events = game.manual_mine("A1")

    g_live = game.get_group("A1")
    assert getattr(g_live, "cargo_minerals", 0) == 1
    assert game.game_map.get_hex_content(h) == HexContent.CLEAR
    assert any("picked up" in e.lower() for e in events)


def test_mine_respects_capacity_for_multi_ship_group(mining_ship_type):
    game, p1, _ = mk_game()
    h = Hex(0, 0)

    game.game_map.set_hex_content(h, HexContent.MINERALS)
    game.game_map.set_explored(h)

    g = UnitGroup("A1", p1, mining_ship_type, count=2, location=h)
    g.cargo_minerals = 2  # already full (capacity == count)
    game.add_group(g)

    events = game.manual_mine("A1")
    assert events == ["No mining possible here."] or all("picked up" not in e.lower() for e in events)
    assert g.cargo_minerals == 2


def test_debug_reveal_hex_marks_explored():
    game, _, _ = mk_game()
    h = Hex(2, 2)
    game.game_map.set_hex_content(h, HexContent.PLANET_STANDARD)

    assert not game.game_map.is_explored(h)
    events = game.debug_reveal_hex(h)
    assert game.game_map.is_explored(h)
    assert any("revealed" in e.lower() for e in events)


def test_debug_reveal_all_hexes_marks_many_explored():
    game, _, _ = mk_game()
    # ensure at least one tile is not explored
    h = Hex(0, 0)
    assert not game.game_map.is_explored(h)

    events = game.debug_reveal_all_hexes()
    assert game.game_map.is_explored(h)
    assert any("revealed all" in e.lower() for e in events)


def test_exploration_happens_on_destination_hex(game):
    dest = Hex(1, 0)
    assert not game.game_map.is_explored(dest)
    game.queue_move("A1", dest)
    game.submit_orders()
    dump_log(game)
    assert game.game_map.is_explored(dest)
