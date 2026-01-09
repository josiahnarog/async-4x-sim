from sim.hexgrid import Hex
from sim.map import GameMap
from sim.persistence import game_from_json, game_to_json
from sim.turn_engine import GameState
from sim.units import PlayerID, UnitGroup, UnitType


def test_persistence_roundtrip_fog_and_markers():
    game = GameState()
    game.game_map = GameMap(q_min=-4, q_max=4, r_min=-4, r_max=4)

    p1 = PlayerID("A")
    p2 = PlayerID("B")
    game.players = [p1, p2]
    game.active_player = p1

    # Create two groups, one per player.
    ut = UnitType(
        name="Scout",
        max_groups=6,
        movement=1,
        is_combatant=True,
        initiative="E",
        attack=1,
        defense=0,
        hull=1,
    )
    g1 = UnitGroup("A1", p1, ut, count=1, location=Hex(0, 0))
    g2 = UnitGroup("B1", p2, ut, count=1, location=Hex(1, 0))
    game.add_group(g1)
    game.add_group(g2)

    # Fog-of-war / reveal structures
    # A has revealed B1
    game.revealed_to[p1] = {"B1"}
    game.revealed_to[p2] = set()

    # Viewer-specific markers
    game.marker_for_viewer[p1] = {"B1": "E1"}  # A sees B1 as marker E1
    game.marker_for_viewer[p2] = {}

    # Reverse mapping (viewer marker -> group id)
    game.group_for_viewer_marker[p1] = {"E1": "B1"}
    game.group_for_viewer_marker[p2] = {}

    # Next marker index per viewer
    game.next_marker_index[p1] = 2
    game.next_marker_index[p2] = 1

    s = game_to_json(game)
    loaded = game_from_json(s)

    # Reveal survived
    assert loaded.revealed_to[loaded.players[0]] == {"B1"}  # A
    assert loaded.revealed_to[loaded.players[1]] == set()   # B

    # Markers survived
    assert loaded.marker_for_viewer[loaded.players[0]] == {"B1": "E1"}
    assert loaded.group_for_viewer_marker[loaded.players[0]] == {"E1": "B1"}
    assert loaded.next_marker_index[loaded.players[0]] == 2
