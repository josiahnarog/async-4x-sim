from __future__ import annotations
from collections import deque
from typing import Dict, Optional, List

from sim.hexgrid import Hex
from sim.map import GameMap


# Deterministic neighbor order for BFS (axial directions):
# This order is your tie-break. Pick one and keep it forever.
DIRS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]


def ordered_neighbors(h: Hex) -> List[Hex]:
    return [Hex(h.q + dq, h.r + dr) for dq, dr in DIRS]


def bfs_path(game_map: GameMap, start: Hex, goal: Hex) -> Optional[List[Hex]]:
    """
    Returns a path as a list of hexes EXCLUDING start and INCLUDING goal.
    Returns None if no path exists or goal not passable.
    Deterministic due to fixed neighbor order.
    """
    if start == goal:
        return []

    if not game_map.is_passable(start):
        return None
    if not game_map.is_passable(goal):
        return None

    frontier = deque([start])
    came_from: Dict[Hex, Optional[Hex]] = {start: None}

    while frontier:
        current = frontier.popleft()
        if current == goal:
            break

        for nxt in ordered_neighbors(current):
            if not game_map.is_passable(nxt):
                continue
            if nxt in came_from:
                continue
            came_from[nxt] = current
            frontier.append(nxt)

    if goal not in came_from:
        return None

    # Reconstruct backwards from goal -> start
    path_rev: List[Hex] = []
    cur = goal
    while cur != start:
        path_rev.append(cur)
        cur = came_from[cur]
        assert cur is not None  # for type checkers

    path_rev.reverse()
    return path_rev
