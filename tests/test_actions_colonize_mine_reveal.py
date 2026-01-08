import pytest

from sim.turn_engine import GameState
from sim.map import GameMap
from sim.hexgrid import Hex
from sim.map_content import HexContent
from sim.units import PlayerID, UnitType, UnitGroup
from sim.colonies import Colony


def mk_game():
    game = GameState()
    game.game_map = GameMap(q_min=-4, q_max=4, r_min=-4, r_max=4)
    p1 = PlayerID("A")
    p2 = PlayerID("B")
    game.players = [p1, p2]
    game.active_player = p1
    return game, p1, p2


def mk_colony_ship_type():
    ut = UnitType(
        name="Colony Ship",
        max_groups=99,
        movement=1,
        is_combatant=False,
        initiative="E",
        attack=0,
        defense=0,
        hull=1,
    )
    ut.can_colonize = True
    return ut


def mk_mining_ship_type():
    ut = UnitType(
        name="Mining Ship",
        max_groups=99,
        movement=1,
        is_combatant=False,
        initiative="E",
        attack=0,
        defense=0,
        hull=1,
    )
    ut.can_mine = True
    return ut


def test_manual_colonize_consumes_one_ship_and_creates_colony():
    game, p1, _ = mk_game()
    h = Hex(0, 0)

    game.game_map.set_hex_content(h, HexContent.PLANET_STANDARD)
    game.game_map.set_explored(h)

    ut = mk_colony_ship_type()
    g = UnitGroup("A1", p1, ut, count=2, location=h)
    game.add_group(g)

    events = game.manual_colonize("A1")

    assert h in game.colonies
    assert game.colonies[h].owner == p1
    assert game.get_group("A1") is not None
    assert game.get_group("A1").count == 1
    assert any("colony" in e.lower() for e in events)


def test_auto_end_of_turn_actions_colonizes_and_removes_group_if_last_ship():
    game, p1, _ = mk_game()
    h = Hex(1, 0)

    game.game_map.set_hex_content(h, HexContent.PLANET_STANDARD)
    game.game_map.set_explored(h)

    ut = mk_colony_ship_type()
    g = UnitGroup("A1", p1, ut, count=1, location=h)
    game.add_group(g)

    events = game.resolve_end_of_turn_hex_actions(g)

    assert h in game.colonies
    assert game.get_group("A1") is None
    assert any("colony" in e.lower() for e in events)


def test_manual_mine_picks_up_once_and_clears_hex():
    game, p1, _ = mk_game()
    h = Hex(0, 0)

    game.game_map.set_hex_content(h, HexContent.MINERALS)
    game.game_map.set_explored(h)

    ut = mk_mining_ship_type()
    g = UnitGroup("A1", p1, ut, count=1, location=h)
    game.add_group(g)

    events = game.manual_mine("A1")

    g2 = game.get_group("A1")
    assert getattr(g2, "cargo_minerals", 0) == 1
    assert game.game_map.get_hex_content(h) == HexContent.CLEAR
    assert any("picked up" in e.lower() for e in events)


def test_mining_respects_capacity_for_multi_ship_group():
    game, p1, _ = mk_game()
    h = Hex(0, 0)

    game.game_map.set_hex_content(h, HexContent.MINERALS)
    game.game_map.set_explored(h)

    ut = mk_mining_ship_type()
    g = UnitGroup("A1", p1, ut, count=2, location=h)
    g.cargo_minerals = 2  # full
    game.add_group(g)

    events = game.manual_mine("A1")

    assert g.cargo_minerals == 2
    assert game.game_map.get_hex_content(h) == HexContent.MINERALS  # unchanged because no pickup
    assert all("picked up" not in e.lower() for e in events)


def test_debug_reveal_hex_marks_explored():
    game, _, _ = mk_game()
    h = Hex(2, 2)
    game.game_map.set_hex_content(h, HexContent.PLANET_STANDARD)

    assert not game.game_map.is_explored(h)
    events = game.debug_reveal_hex(h)
    assert game.game_map.is_explored(h)
    assert any("revealed" in e.lower() for e in events)


def test_debug_reveal_all_marks_map_explored():
    game, _, _ = mk_game()
    assert not game.game_map.is_explored(Hex(0, 0))
    events = game.debug_reveal_all_hexes()
    assert game.game_map.is_explored(Hex(0, 0))
    assert any("revealed all" in e.lower() for e in events)
