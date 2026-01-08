import pytest

from sim.map import GameMap
from sim.turn_engine import GameState
from sim.hexgrid import Hex
from sim.unit_types import BATTLESHIP, DECOY
from sim.units import PlayerID, UnitType, UnitGroup

import pytest

from sim.map import GameMap
from sim.turn_engine import GameState
from sim.hexgrid import Hex
from sim.unit_types import DECOY
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

A_HOME = Hex(0, 0)
B_HOME = Hex(2, 0)

def _build_game():
    game = GameState()
    game.game_map = GameMap(q_min=-4, q_max=4, r_min=-4, r_max=4)

    # Players (keep references; don't recreate PlayerID("A") in tests)
    p1 = PlayerID("A")
    p2 = PlayerID("B")

    game.players = [p1, p2]
    game.active_player = p1

    # Units
    a_ship = UnitGroup("A1", p1, FAST_BATTLESHIP, count=3, location=A_HOME)
    b_decoy = UnitGroup("B1", p2, DECOY, count=1, location=B_HOME)

    game.add_group(a_ship)
    game.add_group(b_decoy)

    ids = {
        "A_SHIP": a_ship.group_id,
        "B_DECOY": b_decoy.group_id,
    }
    players = {"A": p1, "B": p2}
    hexes = {"A_HOME": A_HOME, "B_HOME": B_HOME}

    return game, ids, players, hexes


@pytest.fixture
def bundle():
    """(game, ids, players, hexes)"""
    return _build_game()


@pytest.fixture
def game(bundle):
    return bundle[0]


@pytest.fixture
def ids(bundle):
    return bundle[1]


@pytest.fixture
def players(bundle):
    return bundle[2]


@pytest.fixture
def hexes(bundle):
    return bundle[3]


def dump_log(game):
    print("\n--- GAME LOG ---")
    for e in game.log:
        print(e)
    print("--- END LOG ---\n")
