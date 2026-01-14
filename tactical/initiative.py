from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol
import random


class RNG(Protocol):
    def randint(self, a: int, b: int) -> int: ...


@dataclass(frozen=True, slots=True)
class Initiative:
    """Initiative results for a tactical encounter.

    Current rule (MVP):
      - Each side rolls 1d10
      - Ties are resolved by re-rolling ONLY the tied sides, repeatedly, until unique.
      - Ordering is then strictly by roll value (no lexical tie-break).
    """

    rolls: dict[str, int]  # side_id -> d10 roll (1..10)

    @staticmethod
    def roll(sides: Iterable[str], rng: RNG | None = None) -> Initiative:
        r = rng or random.Random()
        side_ids = sorted(set(sides))
        if not side_ids:
            return Initiative(rolls={})

        rolls = {sid: r.randint(1, 10) for sid in side_ids}

        # Re-roll ties until all rolls are unique.
        # Expected to terminate quickly; deterministic given RNG seed.
        while True:
            buckets: dict[int, list[str]] = {}
            for sid, val in rolls.items():
                buckets.setdefault(val, []).append(sid)

            tied = [sids for sids in buckets.values() if len(sids) > 1]
            if not tied:
                break

            for group in tied:
                for sid in group:
                    rolls[sid] = r.randint(1, 10)

        return Initiative(rolls=rolls)

    def order_low_to_high(self) -> list[str]:
        return sorted(self.rolls.keys(), key=lambda sid: self.rolls[sid])

    def order_high_to_low(self) -> list[str]:
        return sorted(self.rolls.keys(), key=lambda sid: -self.rolls[sid])
