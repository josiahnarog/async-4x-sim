from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class RNG(Protocol):
    def randint(self, a: int, b: int) -> int: ...


@dataclass(frozen=True, slots=True)
class VolleyResult:
    incoming_hits: int
    pd_shots: int
    pd_hits: int
    intercepted: int
    remaining_hits: int


def resolve_missile_volley(
    *,
    incoming_hits: int,
    pd_shots: int,
    pd_to_hit: int,
    rng: RNG,
) -> VolleyResult:
    """
    Resolve point defense against an incoming missile volley.

    Rules:
      - PD only engages *hits*
      - PD capacity is per volley
      - each PD hit intercepts exactly one missile hit
    """
    if incoming_hits <= 0 or pd_shots <= 0 or pd_to_hit <= 0:
        return VolleyResult(
            incoming_hits=incoming_hits,
            pd_shots=0,
            pd_hits=0,
            intercepted=0,
            remaining_hits=incoming_hits,
        )

    shots = min(pd_shots, incoming_hits)
    pd_hits = 0

    for _ in range(shots):
        roll = int(rng.randint(1, 10))
        if roll >= pd_to_hit:
            pd_hits += 1

    intercepted = min(pd_hits, incoming_hits)
    remaining = incoming_hits - intercepted

    return VolleyResult(
        incoming_hits=incoming_hits,
        pd_shots=shots,
        pd_hits=pd_hits,
        intercepted=intercepted,
        remaining_hits=remaining,
    )
