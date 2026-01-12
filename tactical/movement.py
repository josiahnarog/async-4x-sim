from __future__ import annotations

from dataclasses import dataclass

from sim.hexgrid import Hex
from tactical.facing import Facing, FACING_OFFSETS


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

