# sim/hexgrid.py

class Hex:
    def __init__(self, q, r):
        self.q = q
        self.r = r

    def __eq__(self, other):
        return isinstance(other, Hex) and self.q == other.q and self.r == other.r

    def __hash__(self):
        return hash((self.q, self.r))

    def __repr__(self):
        return f"({self.q},{self.r})"

    def neighbors(self):
        directions = [
            (1, 0), (1, -1), (0, -1),
            (-1, 0), (-1, 1), (0, 1)
        ]
        return [Hex(self.q + dq, self.r + dr) for dq, dr in directions]


def hex_distance(a: Hex, b: Hex) -> int:
    # axial distance via cube coords
    ax, az = a.q, a.r
    ay = -ax - az
    bx, bz = b.q, b.r
    by = -bx - bz
    return max(abs(ax - bx), abs(ay - by), abs(az - bz))


def greedy_path(start: Hex, goal: Hex, max_steps: int) -> list[Hex]:
    """
    Very simple path: at each step, move to a neighbor that reduces distance.
    Good enough for now (no obstacles). Returns list INCLUDING start? We'll return steps excluding start.
    """
    path = []
    current = start
    steps = 0

    while current != goal and steps < max_steps:
        nbrs = current.neighbors()
        # pick the neighbor that minimizes distance to goal
        best = min(nbrs, key=lambda h: hex_distance(h, goal))
        # If we can't get closer (shouldn't happen on open grid), stop
        if hex_distance(best, goal) >= hex_distance(current, goal):
            break
        path.append(best)
        current = best
        steps += 1

    return path
