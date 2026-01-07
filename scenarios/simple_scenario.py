from sim.hexgrid import Hex
from sim.unit_types import BATTLESHIP, DECOY
from sim.units import PlayerID, UnitType, UnitGroup
from sim.turn_engine import GameState
from sim.map import GameMap

def build_game():
    game = GameState()
    game.game_map = GameMap(q_min=-4, q_max=4, r_min=-4, r_max=4)

    # Players
    p1 = PlayerID("A")
    p2 = PlayerID("B")

    game.players = [p1, p2]
    game.active_player = p1

    # Units
    g1 = UnitGroup("G1", p1, BATTLESHIP, count=3, location=Hex(0, 0))
    g2 = UnitGroup("G2", p2, BATTLESHIP, count=5, location=Hex(1, 0))

    game.add_group(g1)
    game.add_group(g2)

    return game
