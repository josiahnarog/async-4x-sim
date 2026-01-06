from sim.hexgrid import Hex
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

    # Unit types
    battleship = UnitType("Battleship", max_groups=5)
    decoy = UnitType("Decoy", max_groups=10)

    # Units
    g1 = UnitGroup("G1", p1, battleship, count=3, tech_level=1, location=Hex(0, 0))
    g2 = UnitGroup("G2", p2, decoy, count=1, tech_level=0, location=Hex(2, 0))

    game.add_group(g1)
    game.add_group(g2)

    return game
