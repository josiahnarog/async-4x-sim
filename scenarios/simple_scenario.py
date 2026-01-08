from sim.colonies import Colony
from sim.hexgrid import Hex
from sim.map_content import HexContent
from sim.unit_types import BATTLESHIP, DECOY, SCOUT, COLONY_SHIP, MINING_SHIP
from sim.units import PlayerID, UnitType, UnitGroup
from sim.turn_engine import GameState
from sim.map import GameMap


def build_game():
    game = GameState()
    game.game_map = GameMap(q_min=-4, q_max=4, r_min=-4, r_max=4)

    # Players
    p1 = PlayerID("A")
    p2 = PlayerID("B")
    p1_home_hex = Hex(-4, -4)
    p2_home_hex = Hex(4, 4)

    game.players = [p1, p2]
    game.active_player = p1

    for player, home in [(p1, p1_home_hex), (p2, p2_home_hex)]:
        _set_player_homeworld(game, player, home)
        for unit in [COLONY_SHIP, MINING_SHIP, SCOUT]:
            ug = UnitGroup(game.allocate_group_id(player), player, unit, count=1, location=home)
            game.add_group(ug)

    game.game_map.set_hex_content(Hex(-4, -3), HexContent.PLANET_STANDARD)
    game.game_map.set_hex_content(Hex(4, 3), HexContent.PLANET_STANDARD)
    game.game_map.set_hex_content(Hex(-3, -4), HexContent.MINERALS)
    game.game_map.set_hex_content(Hex(3, 4), HexContent.MINERALS)

    return game


def _set_player_homeworld(game: GameState, player: PlayerID, home_hex: Hex):
    game.game_map.set_hex_content(home_hex, HexContent.HOMEWORLD)
    game.game_map.set_explored(home_hex)  # if home starts explored for owner/global
    game.colonies[home_hex] = Colony(owner=player, level=3, homeworld=True)  # or a special field
