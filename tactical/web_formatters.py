"""Formatting helpers for tactical web event display."""
from __future__ import annotations

from itertools import groupby


def fmt_shots(shots, to_hit: int | None = None) -> str:
    """Compact roll list: '3✓ 7✗ 2✓'."""
    parts = []
    for s in shots:
        mark = "✓" if s.hit else "✗"
        parts.append(f"{s.roll}{mark}")
    return " ".join(parts)


def fmt_dogfight(ev) -> list[str]:
    lines = [f"  DOGFIGHT {ev.attacker_id}→{ev.target_id}  mvr={ev.mvr_delta:+}"
             f"  casualties={ev.total_casualties}"]
    for weapon, group in groupby(ev.shots, key=lambda s: s.weapon):
        shots = list(group)
        th = shots[0].to_hit
        rolls = fmt_shots(shots)
        hits = sum(1 for s in shots if s.hit)
        lines.append(f"    [{weapon.value}] to_hit={th}  {rolls}  hits={hits}")
    return lines


def fmt_attack_run(ev, label: str = "ATTACK RUN") -> list[str]:
    pd_rolls = " ".join(
        f"{r}{'✓' if r <= 3 else '✗'}" for r in ev.pd_rolls
    ) or "—"
    lines = [
        f"  {label} {ev.attacker_id}→{ev.target_id}",
        f"    PD: [{pd_rolls}]  killed={ev.fighters_killed_by_pd}"
        f"  survivors={ev.surviving_strength}",
    ]
    for weapon, group in groupby(ev.weapon_shots, key=lambda s: s.weapon):
        shots = list(group)
        th = shots[0].to_hit
        rolls = fmt_shots(shots)
        hits = sum(1 for s in shots if s.hit)
        dmg  = sum(s.damage for s in shots)
        lines.append(f"    [{weapon.value}] to_hit={th}  {rolls}  hits={hits}  dmg={dmg}")
    lines.append(f"    total ship damage: {ev.total_ship_damage}")
    return lines


def fmt_fire(ev) -> str:
    if getattr(ev, "missile_rolls", None) is not None:
        to_hit = ev.to_hit
        rolls = ", ".join(
            f"{r}{'✓' if to_hit is not None and r <= to_hit else '✗'}"
            for r in ev.missile_rolls
        )
        pd_part = ""
        if ev.pd_rolls:
            pd_rolls = ", ".join(
                f"{r}{'✓' if r <= 3 else '✗'}" for r in ev.pd_rolls
            )
            pd_part = f" pd=[{pd_rolls}] pd_int={ev.pd_intercepted}"
        else:
            pd_part = f" pd_int={ev.pd_intercepted}"
        return (f"{ev.attacker_id}→{ev.target_id} {ev.weapon.value} r={ev.range} "
                f"to_hit={ev.to_hit} rolls=[{rolls}] hits={ev.missile_hits}"
                f"{pd_part} rem={ev.remaining_hits} dmg={ev.raw_damage}")
    return (f"{ev.attacker_id}→{ev.target_id} {ev.weapon.value} r={ev.range} "
            f"roll={ev.roll} to_hit={ev.to_hit} hit={ev.hit} dmg={ev.raw_damage}")
