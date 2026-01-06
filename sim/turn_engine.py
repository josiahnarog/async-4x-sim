# sim/turn_engine.py

from __future__ import annotations

from typing import Dict, Set, Optional, List, Tuple

from sim.hexgrid import Hex, hex_distance, greedy_path
from sim.units import UnitGroup, PlayerID


class GameState:
    def __init__(self):
        self.players: List[PlayerID] = []
        self.active_player: Optional[PlayerID] = None
        self.unit_groups: Dict[str, UnitGroup] = {}  # group_id -> UnitGroup
        self.turn_number: int = 1
        self.log: List[str] = []
        self.revealed_to: Dict[PlayerID, Set[str]] = {}  # viewer -> set(group_id)
        self.marker_for_viewer: Dict[PlayerID, Dict[str, str]] = {}  # viewer -> {group_id: "M1"}
        self.group_for_viewer_marker: Dict[PlayerID, Dict[str, str]] = {}  # viewer -> {"M1": group_id}
        self.next_marker_index: Dict[PlayerID, int] = {}  # viewer -> next int

    # -----------------------------
    # Basic state helpers
    # -----------------------------
    def add_group(self, group: UnitGroup) -> None:
        self.unit_groups[group.group_id] = group

    def remove_group(self, group_id: str) -> None:
        if group_id in self.unit_groups:
            del self.unit_groups[group_id]

    def _ensure_viewer_tables(self, viewer: PlayerID) -> None:
        if viewer not in self.revealed_to:
            self.revealed_to[viewer] = set()
        if viewer not in self.marker_for_viewer:
            self.marker_for_viewer[viewer] = {}
        if viewer not in self.group_for_viewer_marker:
            self.group_for_viewer_marker[viewer] = {}
        if viewer not in self.next_marker_index:
            self.next_marker_index[viewer] = 1

    def is_revealed(self, viewer: PlayerID, group_id: str) -> bool:
        self._ensure_viewer_tables(viewer)
        return group_id in self.revealed_to[viewer]

    def reveal_group_to(self, viewer: PlayerID, group_id: str) -> None:
        self._ensure_viewer_tables(viewer)
        self.revealed_to[viewer].add(group_id)

        # Optional: when revealed, you can remove its marker mapping for that viewer
        # so it doesn't linger:
        m = self.marker_for_viewer[viewer].pop(group_id, None)
        if m:
            self.group_for_viewer_marker[viewer].pop(m, None)

    def reveal_hex_to_players(self, hex_, viewers) -> list[str]:
        """
        Reveal all groups in hex_ to each viewer.
        Returns a list of log/event strings.
        """
        events: list[str] = []
        groups = self.groups_at(hex_)

        for v in viewers:
            self._ensure_viewer_tables(v)
            # Reveal each group in that hex to this viewer
            for g in groups:
                if not self.is_revealed(v, g.group_id):
                    self.reveal_group_to(v, g.group_id)

            # Optional: add a summary event line (useful for debugging)
            if groups:
                summary = ", ".join(
                    f"{g.group_id}:{g.unit_type.name}x{g.count} t{g.tech_level}"
                    for g in groups
                )
                events.append(f"REVEAL to {v} at {hex_}: {summary}")

        return events

    def get_group(self, group_id: str) -> Optional[UnitGroup]:
        return self.unit_groups.get(group_id)

    def get_marker_id(self, viewer: PlayerID, group_id: str) -> str:
        """
        Stable per-viewer marker for an enemy group when not revealed.
        Returns like "M1", "M2", ...
        """
        self._ensure_viewer_tables(viewer)

        # If already assigned, return
        existing = self.marker_for_viewer[viewer].get(group_id)
        if existing:
            return existing

        # Assign a new marker
        n = self.next_marker_index[viewer]
        marker = f"M{n}"
        self.next_marker_index[viewer] = n + 1

        self.marker_for_viewer[viewer][group_id] = marker
        self.group_for_viewer_marker[viewer][marker.upper()] = group_id
        return marker

    def resolve_group_id_from_token(self, viewer: PlayerID, token: str) -> Optional[str]:
        """
        Allows REPL to accept either a real group_id (for own groups) OR a marker like M3.
        For unrevealed enemy groups, the player will only know the marker.
        """
        self._ensure_viewer_tables(viewer)

        t = token.strip()
        # direct group id
        if t in self.unit_groups:
            return t

        # marker
        return self.group_for_viewer_marker[viewer].get(t.upper())

    def groups_at(self, hex_: Hex) -> List[UnitGroup]:
        return [g for g in self.unit_groups.values() if g.location == hex_]

    def groups_at_owned_by(self, hex_: Hex, owner: PlayerID) -> List[UnitGroup]:
        return [g for g in self.groups_at(hex_) if g.owner == owner]

    def groups_at_enemy_of(self, hex_: Hex, owner: PlayerID) -> List[UnitGroup]:
        return [g for g in self.groups_at(hex_) if g.owner != owner]

    def end_turn(self) -> None:
        idx = self.players.index(self.active_player)
        self.active_player = self.players[(idx + 1) % len(self.players)]
        if self.active_player == self.players[0]:
            self.turn_number += 1

    # -----------------------------
    # Combat (placeholder)
    # -----------------------------
    def resolve_combat_simple(self, attacker_owner: PlayerID, hex_: Hex) -> List[str]:
        """
        Placeholder combat with fog-of-war reveal:
          1) reveal all groups in the combat hex to all involved players
          2) attacker wins
          3) all defender groups in the hex are destroyed
        Later: implement your boardgame's real combat and reveal logic.
        """
        events: List[str] = []

        attackers = self.groups_at_owned_by(hex_, attacker_owner)
        defenders = self.groups_at_enemy_of(hex_, attacker_owner)

        involved_players = {attacker_owner}
        for g in attackers:
            involved_players.add(g.owner)
        for g in defenders:
            involved_players.add(g.owner)

        # Reveal all groups in this hex to all involved players (before casualties)
        events.extend(self.reveal_hex_to_players(hex_, viewers=list(involved_players)))

        if not defenders:
            events.append(f"Combat at {hex_} had no defenders (unexpected).")
            return events

        for d in list(defenders):
            events.append(f"Defender {d.group_id} destroyed.")
            self.remove_group(d.group_id)

        return events

        for d in defenders:
            events.append(f"Defender {d.group_id} destroyed.")
            self.remove_group(d.group_id)

        return events

    # -----------------------------
    # Movement (step-by-step + interception)
    # -----------------------------
    def move_group(self, group_id: str, dest: Hex) -> Tuple[bool, str]:
        """
        Move a single group up to its movement allowance (per UnitType).
        Movement is resolved step-by-step along greedy_path() so we can detect interception.
        Interception rule:
          - if the moving group enters a hex that contains ANY enemy group(s),
            combat triggers immediately and movement stops in that hex.

        Stacking:
          - friendly stacking is allowed (multiple groups per hex).
        """
        g = self.get_group(group_id)
        if not g:
            return False, "No such group."

        if g.owner != self.active_player:
            return False, "You don't control that group."

        start = g.location
        if start == dest:
            return False, f"{g.group_id} is already at {dest}."

        move_allowance = g.movement
        dist = hex_distance(start, dest)
        if dist > move_allowance:
            return False, f"Out of range (distance {dist}, movement {move_allowance})."

        path = greedy_path(start, dest, max_steps=move_allowance)
        if not path or path[-1] != dest:
            return False, f"Could not find a path to {dest} (pathing is still prototype)."

        # Walk the path
        for step_hex in path:
            g.location = step_hex

            # Check interception AFTER entering the hex
            enemies_here = self.groups_at_enemy_of(step_hex, g.owner)
            if enemies_here:
                self.log.append(f"{g.group_id} intercepts enemy at {step_hex}.")
                for e in self.resolve_combat_simple(g.owner, step_hex):
                    self.log.append(e)
                return True, f"{g.group_id} moved to {step_hex} and engaged the enemy!"

        self.log.append(f"{g.group_id} moved from {start} to {dest}.")
        return True, f"Moved {g.group_id} to {dest}."

    def move_fleet(self, source: Hex, dest: Hex) -> List[str]:
        """
        Convenience for REPL: move all groups owned by the active player at `source` to `dest`.
        This treats a 'fleet' as a stack of groups at a location.

        Returns a list of human-readable messages (also appended to log).
        """
        if self.active_player is None:
            return ["No active player set."]

        groups = [g for g in self.groups_at_owned_by(source, self.active_player)]
        if not groups:
            return [f"No friendly groups at {source}."]

        msgs: List[str] = []
        # snapshot IDs so moving one group doesn't change which are selected
        group_ids = [g.group_id for g in groups]
        for gid in group_ids:
            ok, msg = self.move_group(gid, dest)
            msgs.append(msg)
            # if a move triggers combat, other groups may still move (tabletop often allows stack movement);
            # keep it simple for now and continue.
        return msgs

