# sim/turn_engine.py

from typing import Dict, List, Optional
from sim.hexgrid import Hex, hex_distance, greedy_path
from sim.units import UnitGroup, PlayerID

class GameState:
    def __init__(self):
        self.players: List[PlayerID] = []
        self.active_player: Optional[PlayerID] = None
        self.unit_groups: Dict[str, UnitGroup] = {}  # group_id -> UnitGroup
        self.turn_number: int = 1
        self.log: List[str] = []

    def add_group(self, group: UnitGroup) -> None:
        self.unit_groups[group.group_id] = group

    def get_group(self, group_id: str):
        return self.unit_groups.get(group_id)

    def groups_at(self, hex: Hex) -> List[UnitGroup]:
        return [g for g in self.unit_groups.values() if g.location == hex]

    def end_turn(self):
        idx = self.players.index(self.active_player)
        self.active_player = self.players[(idx + 1) % len(self.players)]
        if self.active_player == self.players[0]:
            self.turn_number += 1

    # --- NEW: movement + interception ---

    def resolve_combat(self, attacker, defender, location: Hex):
        """
        Placeholder combat: attacker always wins.
        Replace later with your real combat rules + reveal logic.
        """
        self.log.append(f"COMBAT at {location}: {attacker.group_id} vs {defender.group_id} -> {attacker.group_id} wins")
        self.remove_group(defender.group_id)

    def move_group(self, group_id: str, dest: Hex) -> tuple[bool, str]:
        """
        Returns (ok, message). Basic rules for now:
        - group exists
        - belongs to active player
        - dest is adjacent (range=1 prototype)
        - can't move into friendly-occupied hex (optional rule; keep for now)
        """
        g = self.get_group(group_id)
        if not g:
            return False, "No such group."

        if g.owner != self.active_player:
            return False, "You don't control that group."

        # Range-1 prototype: must be adjacent
        if not self.is_adjacent(g.location, dest):
            return False, "Illegal move (must move to an adjacent hex for now)."

        # Optional stacking rule: disallow moving onto friendly groups
        occupants = self.groups_at(dest)
        if any(o.owner == self.active_player for o in occupants):
            return False, "Illegal move (destination occupied by your own group)."

        # Move
        g.location = dest
        self.log.append(f"{self.active_player} moved {g.group_id} to {dest}")
        return True, f"Moved {g.group_id} to {dest}"

    @staticmethod
    def is_adjacent(a: Hex, b: Hex) -> bool:
        # If your Hex class doesn’t have neighbors yet, implement adjacency here.
        # Axial neighbors:
        dirs = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
        return any((a.q + dq == b.q and a.r + dr == b.r) for dq, dr in dirs)

