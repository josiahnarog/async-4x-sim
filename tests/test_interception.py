from sim.hexgrid import Hex

from sim.hexgrid import Hex
from sim.map import GameMap
from sim.pathfinding import bfs_path
from tests.conftest import dump_log


def test_bfs_path_includes_intermediate_steps():
    m = GameMap(q_min=-4, q_max=4, r_min=-4, r_max=4)
    p = bfs_path(m, Hex(0, 0), Hex(3, 0))
    assert p == [Hex(1, 0), Hex(2, 0), Hex(3, 0)]


def test_pass_through_destroys_noncombat_and_continues(game):
    """
    Moving combat unit passes through non-combat enemy units,
    destroying them and continuing movement.
    """
    a1 = game.get_group("A1")  # battleship
    b1 = game.get_group("B1")  # decoy (non-combat)

    assert not b1.unit_type.is_combatant

    # Move through B1's hex and beyond
    dest = Hex(3, 0)
    game.queue_move("A1", dest)
    events = game.submit_orders()

    # dump_log(game)

    # Non-combatant destroyed
    assert game.get_group("B1") is None

    # Mover continued to destination
    assert game.get_group("A1").location == dest

    joined = "\n".join(events).lower()
    assert "destroyed during interception" in joined, joined


def test_noncombat_destroyed_even_if_cloak_pass_through(game):
    a1 = game.get_group("A1")
    b1 = game.get_group("B1")
    assert not b1.unit_type.is_combatant

    # Give mover high cloak; should still destroy noncombat if that's the rule
    a1.cloak_bonus = 5

    game.queue_move("A1", Hex(3, 0))
    game.submit_orders()

    assert game.get_group("B1") is None
