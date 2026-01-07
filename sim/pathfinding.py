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


def bfs_path(game_map, start: Hex, goal: Hex):
    if start == goal:
        return []

    frontier = deque([start])
    came_from = {start: None}

    while frontier:
        current = frontier.popleft()
        if current == goal:
            break

        for nxt in current.neighbors():
            if not game_map.in_bounds(nxt):
                continue
            if game_map.is_blocked(nxt):
                continue
            if nxt in came_from:
                continue
            came_from[nxt] = current
            frontier.append(nxt)

    if goal not in came_from:
        return None

    # Reconstruct: from goal back to start
    path = []
    cur = goal
    while cur != start:
        path.append(cur)
        cur = came_from[cur]
    path.reverse()
    return path
