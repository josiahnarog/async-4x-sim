from __future__ import annotations

from sim.hexgrid import Hex, hex_distance
from tactical.battle_state import BattleState


def render_ascii_map(
    battle: BattleState,
    *,
    radius: int = 4,
    center: Hex = Hex(0, 0),
) -> str:
    """Render a simple ASCII hex map centered on `center`.

    Uses axial coordinates with pointy-top layout.
    """
    # Map occupancy
    ship_at = {s.pos: s for s in battle.ships.values()}

    lines: list[str] = []

    # We iterate rows by r, but offset every other row for hex look
    for r in range(center.r + radius, center.r - radius - 1, -1):
        line: list[str] = []

        # Indent every other row for visual hex staggering
        indent = "   " if (r - center.r) % 2 != 0 else ""
        line.append(indent)

        for q in range(center.q - radius, center.q + radius + 1):
            h = Hex(q, r)
            if hex_distance(h, center) > radius:
                continue

            if h in ship_at:
                ship = ship_at[h]
                # Use first character of ship_id for now
                ch = ship.ship_id[0].upper()
            else:
                ch = "."

            line.append(f"{ch}  ")

        lines.append("".join(line).rstrip())

    return "\n".join(lines)
