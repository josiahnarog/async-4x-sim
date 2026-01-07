import pytest
from sim.turn_engine import GameState
from sim.hexgrid import Hex
from sim.units import PlayerID, UnitType, UnitGroup


def _build_game():
    game = GameState()

    A = PlayerID("A")
    B = PlayerID("B")

    game.players = [A, B]
    game.active_player = A

    battleship = UnitType("Battleship", max_groups=5, movement=3, is_combatant=True)
    decoy = UnitType("Decoy", max_groups=10, movement=3, is_combatant=False)

    g1 = UnitGroup("G1", A, battleship, count=3, tech_level=1, location=Hex(0, 0))
    g2 = UnitGroup("G2", B, decoy, count=1, tech_level=0, location=Hex(2, 0))

    game.add_group(g1)
    game.add_group(g2)

    return game


@pytest.fixture
def game():
    """
    Shared GameState fixture for all tests.
    """
    return _build_game()
