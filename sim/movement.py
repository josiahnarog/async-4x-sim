# sim/movement.py

from sim.hexgrid import Hex
from sim.turn_engine import GameState
from sim.units import UnitGroup

DEFAULT_MOVE_RANGE = 3  # for now; later per unit type / tech / damage

def are_adjacent(a: Hex, b: Hex) -> bool:
    return b in a.neighbors()

def validate_destination_in_range(start: Hex, dest: Hex, move_range: int) -> bool:
    # Hex distance in axial coords
    dq = abs(start.q - dest.q)
    dr = abs(start.r - dest.r)
    ds = abs((start.q + start.r) - (dest.q + dest.r))
    dist = max(dq, dr, ds)
    return dist <= move_range

def move_group(game: GameState, group: UnitGroup, dest: Hex, move_range: int = DEFAULT_MOVE_RANGE) -> str:
    start = group.location

    if start == dest:
        return f"{group.group_id} is already at {dest}."

    if not validate_destination_in_range(start, dest, move_range):
        return f"Illegal move: {start} -> {dest} exceeds range {move_range}."

    # Stacking allowed: multiple groups can occupy a hex
    group.location = dest
    return f"{group.group_id} moved {start} -> {dest}."
