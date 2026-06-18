from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from sim.hexgrid import Hex
from tactical.facing import Facing, FACING_OFFSETS


def bfs_reachable(
    pos: Hex,
    facing: Facing,
    turn_charge: int,
    turn_cost: int,
    cap: int,
    occupied: frozenset[Hex] = frozenset(),
) -> dict[tuple[Hex, Facing], int]:
    """Return {(dest, dest_facing): min_mp_cost} for all positions reachable in ≤ cap MP.

    Exact 0-1 BFS over (position, facing, charge) states.  Models the rules:
      - move forward 1 hex : 1 MP, charge = min(charge + 1, turn_cost)
      - spend 1 MP idle    : 1 MP, charge = min(charge + 1, turn_cost)
      - turn left/right    : 0 MP, requires charge >= turn_cost, charge resets to 0

    This is the canonical Python reachability check; the JS BFS mirrors it.
    """
    tc     = max(turn_cost, 1)
    init_c = min(turn_charge, tc)

    start  = (pos.q, pos.r, int(facing), init_c)
    best: dict[tuple, int] = {start: 0}
    dq: deque = deque([(pos.q, pos.r, int(facing), init_c, 0)])
    result: dict[tuple[Hex, Facing], int] = {}

    while dq:
        q, r, f, c, mp = dq.popleft()
        if best.get((q, r, f, c), cap + 1) < mp:
            continue  # stale entry

        cur = Hex(q, r)
        cur_f = Facing(f)
        if cur != pos or cur_f != facing:
            key = (cur, cur_f)
            if key not in result or result[key] > mp:
                result[key] = mp

        # Turns — zero MP cost; charge resets to 0
        if c >= tc:
            for df in (-1, 1):
                nf = (f + df) % 6
                ns = (q, r, nf, 0)
                if best.get(ns, cap + 1) > mp:
                    best[ns] = mp
                    dq.appendleft((q, r, nf, 0, mp))

        if mp >= cap:
            continue

        nmp = mp + 1
        nc  = min(c + 1, tc)

        # Move forward 1 hex
        dq_off, dr_off = FACING_OFFSETS[f]
        nq, nr = q + dq_off, r + dr_off
        if Hex(nq, nr) not in occupied:
            ns = (nq, nr, f, nc)
            if best.get(ns, cap + 1) > nmp:
                best[ns] = nmp
                dq.append((nq, nr, f, nc, nmp))

        # Spend 1 MP idle (earn charge without moving)
        ns = (q, r, f, nc)
        if best.get(ns, cap + 1) > nmp:
            best[ns] = nmp
            dq.append((q, r, f, nc, nmp))

    return result


def forward_neighbor(pos: Hex, facing: Facing) -> Hex:
    """Return the hex directly in front of `pos` given `facing`."""
    dq, dr = FACING_OFFSETS[int(facing)]
    return Hex(pos.q + dq, pos.r + dr)


def step_forward(pos: Hex, facing: Facing, steps: int = 1) -> Hex:
    """Move `steps` times straight forward.

    Deterministic, pure, no collision/terrain rules yet.
    """
    if steps < 0:
        raise ValueError("steps must be >= 0")
    cur = pos
    for _ in range(steps):
        cur = forward_neighbor(cur, facing)
    return cur


@dataclass(frozen=True, slots=True)
class MoveResult:
    """Tiny helper result for early tactical movement plumbing."""
    start: Hex
    end: Hex
    facing: Facing
    cost: int


def compute_move_forward(
    start: Hex,
    facing: Facing,
    mp: int,
    steps: int = 1,
    *,
    occupied: set[Hex] | None = None,
) -> tuple[Hex, int, MoveResult]:
    """Spend MP to move forward.

    Rules (MVP):
      - cost == steps
      - pass-through is allowed (we do NOT check intermediate hexes)
      - destination hex must not be occupied (if `occupied` is provided)
      - if mp < steps -> raise ValueError

    Returns: (new_pos, new_mp, MoveResult)
    """
    if steps < 0:
        raise ValueError("steps must be >= 0")
    if mp < steps:
        raise ValueError(f"Insufficient MP: mp={mp}, steps={steps}")

    if steps == 0:
        end = start
    else:
        end = step_forward(start, facing, steps)

    if occupied is not None and end in occupied:
        raise ValueError(f"Destination occupied: {end}")

    new_mp = mp - steps
    return end, new_mp, MoveResult(start=start, end=end, facing=facing, cost=steps)

