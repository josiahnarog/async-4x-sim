from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from tactical.attack_context import AttackContext, ToHitMod


def combine_mods(mods: Iterable[ToHitMod]) -> ToHitMod:
    r = t = roll = 0
    for m in mods:
        r += m.range_shift
        t += m.target_delta
        roll += m.roll_delta
    return ToHitMod(range_shift=r, target_delta=t, roll_delta=roll)


def clamp_int(x: int, lo: int, hi: int) -> int:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


@dataclass(frozen=True, slots=True)
class ToHitResolution:
    """
    Resolved numbers for a single to-hit check.

    If target is None => impossible to hit at this effective range.
    Canonical hit rule: (roll + roll_delta) <= target
    """
    target: Optional[int]
    roll_delta: int
    effective_range: int


def resolve_to_hit(
    *,
    base_to_hit: Optional[int],
    ctx: AttackContext,
    mods: ToHitMod,
    clamp_target: bool = True,
) -> ToHitResolution:
    """
    Convert base table lookup + modifiers into final (target, roll_delta, effective_range).

    base_to_hit should already be looked up at ctx.effective_range.
    """
    if base_to_hit is None:
        return ToHitResolution(
            target=None,
            roll_delta=mods.roll_delta,
            effective_range=ctx.effective_range,
        )

    target = base_to_hit + mods.target_delta

    if clamp_target:
        target = clamp_int(target, 0, 10)

    return ToHitResolution(
        target=target,
        roll_delta=mods.roll_delta,
        effective_range=ctx.effective_range,
    )


@dataclass(frozen=True, slots=True)
class ToHitCheck:
    """
    One fully-evaluated to-hit check (good for logs/tests).

    Hit semantics in this project:
      - Higher target is easier
      - A hit occurs when (roll + roll_delta) <= target
      - target=None => impossible
    """
    base_target: Optional[int]
    target: Optional[int]
    roll: int
    modified_roll: int
    hit: bool


def roll_hits_target(
    *,
    roll: int,
    base_target: Optional[int],
    target_delta: int = 0,
    roll_delta: int = 0,
    clamp_target: bool = True,
    min_target: int = 0,
    max_target: int = 10,
) -> ToHitCheck:
    """
    Canonical hit logic for the whole codebase.

    DO NOT replicate comparisons elsewhere. Use this function.

    Semantics:
      hit iff (roll + roll_delta) <= (base_target + target_delta)
      where higher base_target is easier.

    base_target=None means "cannot hit" (e.g. '-' range cutoff).
    """
    modified_roll = roll + roll_delta

    if base_target is None:
        return ToHitCheck(
            base_target=None,
            target=None,
            roll=roll,
            modified_roll=modified_roll,
            hit=False,
        )

    target = base_target + target_delta
    if clamp_target:
        target = clamp_int(target, min_target, max_target)

    return ToHitCheck(
        base_target=base_target,
        target=target,
        roll=roll,
        modified_roll=modified_roll,
        hit=(modified_roll <= target),
    )


def check_hit(*, roll: int, res: ToHitResolution) -> bool:
    """
    Backwards-compatible helper.
    Prefer roll_hits_target(...) in new code.
    """
    if res.target is None:
        return False
    return (roll + res.roll_delta) <= res.target

