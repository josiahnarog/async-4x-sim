from sim.hexgrid import Hex
from sim.map import GameMap
from sim.map_content import HexContent
from sim.turn_engine import GameState
from sim.units import PlayerID, UnitGroup, UnitType
from tests.conftest import dump_log


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
        name="COLONY_SHIP",
        max_groups=99,
        initiative="E",
        attack=0,
        defense=0,
        hull=1,
        movement=1,
        is_combatant=False,
    )
    ut.can_colonize = True
    return ut


def mk_mining_ship_type():
    ut = UnitType(
        name="MINING_SHIP",
        max_groups=99,
        initiative="E",
        attack=0,
        defense=0,
        hull=1,
        movement=1,
        is_combatant=False,
    )
    ut.can_mine = True
    return ut


def test_queued_colonize_executes_in_actions_phase():
    game, p1, _ = mk_game()
    planet = Hex(1, 0)

    game.game_map.set_hex_content(planet, HexContent.PLANET_STANDARD)
    game.game_map.set_explored(planet)

    g = UnitGroup("A1", p1, mk_colony_ship_type(), count=1, location=planet)
    game.add_group(g)

    ok, msg = game.queue_colonize("A1")
    assert ok, msg

    events = game.submit_orders()
    assert planet in game.colonies
    assert game.get_group("A1") is None
    assert any("PHASE: Actions" in e for e in events)


def test_queued_mine_executes_in_actions_phase_and_clears_hex():
    game, p1, _ = mk_game()
    mhex = Hex(2, 0)

    game.game_map.set_hex_content(mhex, HexContent.MINERALS)
    game.game_map.set_explored(mhex)

    g = UnitGroup("A1", p1, mk_mining_ship_type(), count=2, location=mhex)
    game.add_group(g)

    ok, msg = game.queue_mine("A1")
    assert ok, msg

    _events = game.submit_orders()
    g2 = game.get_group("A1")
    assert g2 is not None
    assert g2.cargo_minerals == 1
    assert game.game_map.get_hex_content(mhex) == HexContent.CLEAR
