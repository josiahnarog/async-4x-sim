from sim.hexgrid import Hex
from sim.map import GameMap
from sim.pathfinding import bfs_path


def test_bfs_path_empty_grid():
    m = GameMap(-3, 3, -3, 3)
    start = Hex(0, 0)
    goal = Hex(2, 0)
    path = bfs_path(m, start, goal)
    assert path is not None
    assert path[-1] == goal
    assert len(path) == 2  # (1,0), (2,0) with our neighbor order


def test_bfs_path_blocked_goal():
    m = GameMap(-3, 3, -3, 3)
    goal = Hex(2, 0)
    m.block(goal)
    assert bfs_path(m, Hex(0, 0), goal) is None


def test_bfs_path_routes_around_block():
    m = GameMap(-3, 3, -3, 3)
    m.block(Hex(1, 0))  # block the direct step

    path = bfs_path(m, Hex(0, 0), Hex(2, 0))
    assert path is not None
    assert Hex(1, 0) not in path
    assert path[-1] == Hex(2, 0)
