from sim.colonies import Colony
from sim.hexgrid import Hex
from sim.map import GameMap
from sim.map_content import HexContent
from sim.orders import MoveOrder
from sim.persistence import game_from_json, game_to_json
from sim.turn_engine import GameState
from sim.units import PlayerID, UnitGroup, UnitType


def test_persistence_roundtrip_core_state():
    game = GameState()
    game.game_map = GameMap(q_min=-4, q_max=4, r_min=-4, r_max=4)

    p1 = PlayerID("A")
    p2 = PlayerID("B")
    game.players = [p1, p2]
    game.active_player = p1

    # Map state
    planet = Hex(1, 0)
    game.game_map.set_hex_content(planet, HexContent.PLANET_STANDARD)
    game.game_map.set_explored(planet)

    # Colony
    home = Hex(0, 0)
    game.colonies[home] = Colony(owner=p1, level=0, homeworld=True)

    # Credits
    game.credits[p1] = 30
    game.credits[p2] = 10

    # Group + pending move order
    ut = UnitType(
        name="Scout",
        max_groups=6,
        movement=1,
        is_combatant=True,
        initiative="E",
        attack=3,
        defense=0,
        hull=1,
    )
    g = UnitGroup("A1", p1, ut, count=2, location=home)
    game.add_group(g)

    game.pending_orders[p1] = [MoveOrder("A1", planet)]

    s = game_to_json(game)
    loaded = game_from_json(s)

    assert [p.name for p in loaded.players] == ["A", "B"]
    assert loaded.active_player.name == "A"

    assert loaded.game_map.get_hex_content(planet) == HexContent.PLANET_STANDARD
    assert planet in loaded.game_map.explored

    assert home in loaded.colonies
    assert loaded.colonies[home].owner.name == "A"
    assert loaded.colonies[home].homeworld is True

    g2 = loaded.get_group("A1")
    assert g2 is not None
    assert g2.owner.name == "A"
    assert g2.count == 2
    assert g2.location == home
    assert g2.unit_type.name == "Scout"
    assert g2.unit_type.attack == 3

    # Pending orders survived
    loaded._ensure_order_queue(loaded.active_player)
    olist = loaded.pending_orders[loaded.active_player]
    assert len(olist) == 1
    assert isinstance(olist[0], MoveOrder)
    assert olist[0].group_id == "A1"
    assert olist[0].dest == planet


def test_persistence_is_deterministic():
    game = GameState()
    game.game_map = GameMap(q_min=-4, q_max=4, r_min=-4, r_max=4)

    p1 = PlayerID("A")
    p2 = PlayerID("B")
    game.players = [p1, p2]
    game.active_player = p1

    ut = UnitType(
        name="Decoy",
        max_groups=99,
        movement=1,
        is_combatant=True,
        initiative="E",
        attack=0,
        defense=0,
        hull=1,
    )
    game.add_group(UnitGroup("A1", p1, ut, count=1, location=Hex(0, 0)))

    s1 = game_to_json(game)
    s2 = game_to_json(game)
    assert s1 == s2
