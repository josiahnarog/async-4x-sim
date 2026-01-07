import pytest

from sim.map import GameMap
from sim.turn_engine import GameState
from sim.hexgrid import Hex
from sim.unit_types import BATTLESHIP, DECOY
from sim.units import PlayerID, UnitType, UnitGroup

FAST_BATTLESHIP = UnitType(
    name="Battleship",
    max_groups=5,
    movement=3,            # test-specific
    is_combatant=True,
    initiative="B",
    attack=4,
    defense=3,
    hull=3,
)

def _build_game():
    game = GameState()
    game.game_map = GameMap(q_min=-4, q_max=4, r_min=-4, r_max=4)

    # Players
    p1 = PlayerID("A")
    p2 = PlayerID("B")

    game.players = [p1, p2]
    game.active_player = p1

    # Units
    g1 = UnitGroup("G1", p1, FAST_BATTLESHIP, count=3, location=Hex(0, 0))
    g2 = UnitGroup("G2", p2, DECOY, count=1, location=Hex(2, 0))

    game.add_group(g1)
    game.add_group(g2)

    return game


@pytest.fixture
def game():
    """
    Shared GameState fixture for all tests.
    """
    return _build_game()


def dump_log(game):
    print("\n--- GAME LOG ---")
    for e in game.log:
        print(e)
    print("--- END LOG ---\n")
