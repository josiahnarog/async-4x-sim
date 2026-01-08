# sim/turn_engine.py

from __future__ import annotations

from enum import Enum, auto
from typing import Dict, Set, Optional, List, Tuple

from sim.colonies import Colony
from sim.hexgrid import Hex, hex_distance
from sim.combat.targeting import focus_fire
from sim.map_content import HexContent
from sim.units import UnitGroup, PlayerID
from sim.orders import MoveOrder, Order
from sim.map import GameMap
from sim.pathfinding import bfs_path
from sim.combat.resolver import resolve_combat as resolve_combat_impl, collect_battles


class InterceptionOutcome(Enum):
    STOP_AND_MARK_COMBAT = auto()
    PASS_THROUGH = auto()
    PASS_THROUGH_DESTROY_NONCOMBAT = auto()


class GameState:
    def __init__(self):
        self.players: List[PlayerID] = []
        self.active_player: Optional[PlayerID] = None
        self.unit_groups: Dict[str, UnitGroup] = {}  # group_id -> UnitGroup
        self.colonies: dict[Hex, Colony] = {}
        self.turn_number: int = 1
        self.log: List[str] = []
        self.revealed_to: Dict[PlayerID, Set[str]] = {}  # viewer -> set(group_id)
        self.marker_for_viewer: Dict[PlayerID, Dict[str, str]] = {}  # viewer -> {group_id: "M1"}
        self.group_for_viewer_marker: Dict[PlayerID, Dict[str, str]] = {}  # viewer -> {"M1": group_id}
        self.next_marker_index: Dict[PlayerID, int] = {}  # viewer -> next int
        # --- Orders (per-player pending plan) ---
        self.pending_orders = {}  # PlayerID -> list[Order]
        self.game_map = GameMap(q_min=-5, q_max=5, r_min=-5, r_max=5)
        self.targeting_policy = focus_fire
        self.next_group_id: dict[PlayerID, int] = {}

    def interception_policy(self, mover, enemy_groups, at_hex: Hex) -> InterceptionOutcome:
        # 1) All enemies non-combatants => destroy and pass through
        if self._all_noncombat(enemy_groups):
            return InterceptionOutcome.PASS_THROUGH_DESTROY_NONCOMBAT

        # 2) Cloak beats sensors => pass through (no destruction)
        max_enemy_sensors = max((g.sensor_level for g in enemy_groups), default=0)
        if mover.cloak_level > max_enemy_sensors:
            return InterceptionOutcome.PASS_THROUGH

        # 3) Otherwise stop and fight
        return InterceptionOutcome.STOP_AND_MARK_COMBAT

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
                    f"{g.group_id}:{g.unit_type.name}x{g.count}"
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

    from sim.hexgrid import Hex

    def groups_at(self, loc) -> list:
        # Accept Hex or (q,r)
        if isinstance(loc, Hex):
            q, r = loc.q, loc.r
        else:
            q, r = loc  # assume tuple-like

        out = []
        for g in self.unit_groups.values():
            gloc = g.location
            if isinstance(gloc, Hex):
                if gloc.q == q and gloc.r == r:
                    out.append(g)
            else:
                # If some older groups still store tuples
                if gloc[0] == q and gloc[1] == r:
                    out.append(g)
        return out

    def groups_at_owned_by(self, hex_: Hex, owner: PlayerID) -> List[UnitGroup]:
        return [g for g in self.groups_at(hex_) if g.owner == owner]

    def groups_at_enemy_of(self, hex_: Hex, owner: PlayerID) -> List[UnitGroup]:
        return [g for g in self.groups_at(hex_) if g.owner != owner]

    def has_colony(self, h: Hex) -> bool:
        return h in self.colonies

    def get_colony(self, h: Hex):
        return self.colonies.get(h)

    def end_turn(self) -> None:
        idx = self.players.index(self.active_player)
        self.active_player = self.players[(idx + 1) % len(self.players)]
        if self.active_player == self.players[0]:
            self.turn_number += 1

    def find_contested_hexes(self) -> set[Hex]:
        contested: set[Hex] = set()
        by_hex: dict[Hex, set] = {}
        for g in self.unit_groups.values():
            by_hex.setdefault(g.location, set()).add(g.owner)
        for hx, owners in by_hex.items():
            if len(owners) >= 2:
                contested.add(hx)
        return contested

    # -----------------------------
    # Combat (placeholder)
    # -----------------------------

    def resolve_combat(self, attacker_owner: PlayerID, hex_: Hex) -> list[str]:
        return resolve_combat_impl(self, attacker_owner, hex_)

    def _all_noncombat(self, groups) -> bool:
        return all(not g.unit_type.is_combatant for g in groups)

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

        path = bfs_path(self.game_map, start, dest)
        if path is None:
            return False, f"No path to {dest} (blocked or out of bounds)."

        # path length is number of steps
        if len(path) > move_allowance:
            return False, f"Out of range via path (steps {len(path)}, movement {move_allowance})."

        # Walk the path
        for step_hex in path:
            g.location = step_hex

            enemies_here = [x for x in self.groups_at(step_hex) if x.owner != g.owner]
            if enemies_here:
                self.log.append(f"{g.group_id} intercepts enemy at {step_hex}.")
                for e in self.resolve_combat(g.owner, step_hex):
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

    def apply_move_movement_phase(self, group_id: str, dest: Hex) -> tuple[bool, str, Hex, set[Hex], list[str]]:
        """
        Movement phase move:
          - Uses BFS path
          - May STOP on enemy contact (policy)
          - NEVER resolves combat here
        Returns:
          (ok, message, final_hex, combat_sites)
        """
        notes: list[str] = []
        g = self.get_group(group_id)
        if not g:
            return False, "No such group.", dest, set(), notes

        if g.owner != self.active_player:
            return False, "You don't control that group.", g.location, set(), notes

        start = g.location
        if start == dest:
            return False, f"{g.group_id} is already at {dest}.", start, set(), notes

        path = bfs_path(self.game_map, start, dest)
        if path is None:
            return False, f"No path to {dest} (blocked or out of bounds).", start, set(), notes

        if len(path) > g.movement:
            return False, f"Out of range via path (steps {len(path)}, movement {g.movement}).", start, set(), notes

        combat_sites: set[Hex] = set()

        for step_hex in path:
            # Move 1 step
            g.location = step_hex
            self.log.append(f"DEBUG path {g.group_id}: {path}")
            self.log.append(f"DEBUG step={step_hex} occ={[g.group_id for g in self.groups_at(step_hex)]}")

            # Enemy contact check at this hex
            enemies_here = [x for x in self.groups_at(step_hex) if x.owner != g.owner]
            if enemies_here:
                outcome = self.interception_policy(g, enemies_here, step_hex)

                if outcome == InterceptionOutcome.PASS_THROUGH:
                    # allow continuing through; no combat site
                    continue

                if outcome == InterceptionOutcome.PASS_THROUGH_DESTROY_NONCOMBAT:

                    for e in list(enemies_here):
                        note = f"{e.group_id} destroyed during interception at {step_hex}."
                        self.log.append(note)
                        notes.append(note)
                        self.remove_group(e.group_id)
                    continue

                # STOP_AND_MARK_COMBAT
                combat_sites.add(step_hex)
                self.log.append(f"{g.group_id} halted by enemy contact at {step_hex} (combat pending).")
                return True, f"{g.group_id} halted at {step_hex} (combat pending).", step_hex, combat_sites, notes

        # Completed full path without contact
        self.log.append(f"{g.group_id} moved from {start} to {dest}.")
        return True, f"Moved {g.group_id} to {dest}.", dest, combat_sites, notes

    # -----------------------------
    # Exploration
    # -----------------------------

    from sim.map_content import HexContent  # wherever you defined it

    def resolve_exploration_phase(self) -> list[Hex]:
        explored_hexes: list[Hex] = []

        # copy because we may remove groups during actions
        for g in list(self.unit_groups.values()):
            if self.get_group(g.group_id) is None:
                continue

            h = g.location

            # 1) Exploration reveal (only if unexplored)
            if not self.game_map.is_explored(h):
                events = self.resolve_exploration_hex(h, g)
                explored_hexes.append(h)
                self.game_map.set_explored(h)
                for e in events:
                    self.log.append(e)

            # might have been destroyed by exploration (e.g., horror)
            g_live = self.get_group(g.group_id)
            if g_live is None:
                continue

            # 2) End-of-turn actions on explored hex (colonize/mine/deliver)
            for e in self.resolve_end_of_turn_hex_actions(g_live):
                self.log.append(e)

        return explored_hexes

    def resolve_exploration_hex(self, hex_, explorer):
        events = []
        content = self.game_map.get_hex_content(hex_)

        events.append(f"Exploration at {hex_}: {content.name}")

        if content == HexContent.HOMEWORLD:
            # Already handled at setup
            pass

        elif content == HexContent.PLANET_STANDARD:
            events.append("  Discovered habitable planet.")

        elif content == HexContent.PLANET_BARREN:
            events.append("  Discovered barren planet.")

        elif content == HexContent.SUPERNOVA:
            events.append("  Supernova! Ship forced to retreat.")
            prev = self.get_previous_hex(explorer)
            explorer.location = prev
            self.game_map.block_hex(hex_)

        elif content == HexContent.MINERALS:
            events.append("  Mineral deposit discovered.")

        elif content == HexContent.HORROR:
            events.append("  HORROR! All units destroyed.")
            for g in list(self.groups_at(hex_)):
                self.remove_group(g.group_id)
            self.game_map.set_hex_content(hex_, HexContent.CLEAR)

        elif content == HexContent.CLEAR:
            events.append("  Empty space.")

        return events

    from sim.map_content import HexContent
    from sim.colonies import Colony  # if you have it

    def resolve_end_of_turn_hex_actions(self, g) -> list[str]:
        """
        Actions that can occur on already-explored hexes.
        Hooked so you can make them optional later.
        """
        h = g.location
        if not self.game_map.is_explored(h):
            return []

        content = self.game_map.get_hex_content(h)
        events: list[str] = []

        # Optional hooks (auto for now)
        if self.should_auto_colonize(g, h, content):
            events.extend(self.try_colonize(g, h, content))

        if self.should_auto_mine(g, h, content):
            events.extend(self.try_pickup_minerals(g, h, content))

        # OPTIONAL but very useful: auto-deliver if sitting on friendly colony
        events.extend(self.try_deliver_minerals(g, h))

        return events

    def should_auto_colonize(self, g, h, content) -> bool:
        return True  # later: check a queued "colonize" order

    def should_auto_mine(self, g, h, content) -> bool:
        return True  # later: check a queued "mine" order

    def player_has_terraforming(self, player) -> bool:
        return False  # hook for later tech system

    def try_colonize(self, g, h, content) -> list[str]:
        events: list[str] = []

        if not getattr(g.unit_type, "can_colonize", False):
            return events

        if content not in (HexContent.PLANET_STANDARD, HexContent.PLANET_BARREN):
            return events

        if self.has_colony(h):
            return events

        if content == HexContent.PLANET_BARREN and not self.player_has_terraforming(g.owner):
            return events

        # establish colony (level 0)
        self.colonies[h] = Colony(owner=g.owner, level=0, homeworld=False)

        # consume ONE ship from the group
        g.count -= 1
        events.append(f"{g.group_id} colonized {h}: colony established (Level 0), 1 ship consumed.")

        if g.count <= 0:
            self.remove_group(g.group_id)
            events.append(f"{g.group_id} removed (no ships remain).")

        return events

    def try_pickup_minerals(self, g, h, content) -> list[str]:
        events: list[str] = []

        if not getattr(g.unit_type, "can_mine", False):
            return events

        if content != HexContent.MINERALS:
            return events

        # cargo capacity: one load per ship in the group
        cargo = int(getattr(g, "cargo_minerals", 0))
        capacity = max(0, int(g.count))

        if cargo >= capacity:
            return events  # already full

        # For now, minerals hex represents a single load
        setattr(g, "cargo_minerals", cargo + 1)
        events.append(f"{g.group_id} picked up minerals at {h} (cargo {cargo + 1}/{capacity}).")

        # Minerals are removed from the map after pickup
        self.game_map.set_hex_content(h, HexContent.CLEAR)

        return events

    def try_deliver_minerals(self, g, h) -> list[str]:
        """
        OPTIONAL: Deliver minerals if sitting on a friendly colony.
        For now, we just 'bank' a flag on the colony for next econ turn.
        """
        cargo = int(getattr(g, "cargo_minerals", 0))
        if cargo <= 0:
            return []

        col = self.colonies.get(h)
        if col is None:
            return []
        if col.owner != g.owner:
            return []

        # Track minerals delivered for the next econ turn (simple accumulator)
        if not hasattr(col, "minerals_delivered"):
            col.minerals_delivered = 0
        col.minerals_delivered += cargo

        setattr(g, "cargo_minerals", 0)
        return [f"{g.group_id} delivered {cargo} mineral load(s) to colony at {h}."]

    # -----------------------------
    # Orders (step-by-step + interception)
    # -----------------------------

    def _ensure_order_queue(self, player):
        if player not in self.pending_orders:
            self.pending_orders[player] = []

    def queue_move(self, group_id: str, dest: Hex) -> tuple[bool, str]:
        """
        Queue a move order for the active player. Does NOT change game state.
        Validation here is intentionally light; the authoritative validation
        happens on submit (so future rules changes don't break old queues).
        """
        self._ensure_order_queue(self.active_player)

        group_id = group_id.upper()
        g = self.get_group(group_id)
        if not g:
            return False, "No such group."
        if g.owner != self.active_player:
            return False, "You don't control that group."

        self.pending_orders[self.active_player].append(MoveOrder(group_id=group_id, dest=dest))
        return True, f"Queued: move {group_id} to {dest}"

    def list_orders(self, player=None) -> list[Order]:
        if player is None:
            player = self.active_player
        self._ensure_order_queue(player)
        return list(self.pending_orders[player])

    def undo_last_order(self) -> tuple[bool, str]:
        self._ensure_order_queue(self.active_player)
        if not self.pending_orders[self.active_player]:
            return False, "No orders to undo."
        last = self.pending_orders[self.active_player].pop()
        return True, f"Undid: {last}"

    def clear_orders(self) -> tuple[bool, str]:
        self._ensure_order_queue(self.active_player)
        n = len(self.pending_orders[self.active_player])
        self.pending_orders[self.active_player].clear()
        return True, f"Cleared {n} order(s)."

    def submit_orders(self) -> list[str]:
        self._ensure_order_queue(self.active_player)
        orders = self.pending_orders[self.active_player]
        if not orders:
            return ["No orders to submit."]

        events: list[str] = []
        events.append(f"SUBMIT: {self.active_player} ({len(orders)} order(s))")

        # -----------------
        # 1) MOVEMENT PHASE
        # -----------------
        combat_sites: set[Hex] = set()
        events.append("PHASE: Movement")

        ended_hexes: set[Hex] = set()

        for idx, order in enumerate(list(orders), start=1):
            if isinstance(order, MoveOrder):
                ok, msg, final_hex, sites, notes = self.apply_move_movement_phase(order.group_id, order.dest)
                combat_sites |= sites
                if ok:
                    ended_hexes.add(final_hex)
                events.append(f"  {idx}. {order} -> {msg}")
                for n in notes:
                    events.append(f"     {n}")

        # Clear orders after movement application (boardgame style)
        orders.clear()

        # Determine additional combat sites (convergence):
        # Any hex that is contested after movement becomes a combat site.
        contested = self.find_contested_hexes()
        combat_sites |= contested

        # --------------
        # 2) COMBAT PHASE
        # --------------
        events.append("PHASE: Combat")
        battles = collect_battles(self, combat_sites)

        if not battles:
            events.append("  (no battles)")
        else:
            for b in battles:
                events.append(f"  Combat at {b.location}")
                for e in self.resolve_combat(self.active_player, b.location):
                    events.append(f"    {e}")

        # -------------------
        # 3) EXPLORATION PHASE
        # -------------------

        events.append("PHASE: Exploration")
        explored_now = self.resolve_exploration_phase()
        for hx in explored_now:
            events.append(f"  Explored {hx}")

        # Append to log
        for e in events:
            self.log.append(e)

        # End turn
        self.end_turn()
        events.append(f"Now active: {self.active_player}")
        return events

    def allocate_group_id(self, owner: PlayerID) -> str:
        n = self.next_group_id.get(owner, 1)
        self.next_group_id[owner] = n + 1
        return f"{owner}{n}"

    from sim.hexgrid import Hex
    from sim.map_content import HexContent

    def debug_reveal_hex(self, h: Hex) -> list[str]:
        """
        Debug-only: marks a hex explored and reports its stored content.
        Does NOT trigger exploration side effects (horror/supernova), because this
        is intended as a REPL testing tool.
        """
        if not hasattr(self, "game_map") or self.game_map is None:
            return ["No map present."]

        if not self.game_map.in_bounds(h):
            return [f"{h} is out of bounds."]

        if self.game_map.is_explored(h):
            content = self.game_map.get_hex_content(h)
            return [f"{h} already explored: {content.name}"]

        self.game_map.set_explored(h)
        content = self.game_map.get_hex_content(h)
        return [f"Revealed {h}: {content.name}"]

    def debug_reveal_all_hexes(self) -> list[str]:
        """
        Debug-only: marks every in-bounds hex explored.
        """
        if not hasattr(self, "game_map") or self.game_map is None:
            return ["No map present."]

        gm = self.game_map
        count = 0
        for r in range(gm.r_min, gm.r_max + 1):
            for q in range(gm.q_min, gm.q_max + 1):
                h = Hex(q, r)
                if not gm.in_bounds(h):
                    continue
                if not gm.is_explored(h):
                    gm.set_explored(h)
                    count += 1
        return [f"Revealed all hexes ({count} newly explored)."]

    def manual_colonize(self, group_id: str) -> list[str]:
        g = self.get_group(group_id)
        if not g:
            return ["No such group."]

        if g.owner != self.active_player:
            return ["You don't control that group."]

        h = g.location
        if not self.game_map.is_explored(h):
            return ["Cannot colonize an unexplored hex."]

        content = self.game_map.get_hex_content(h)
        events = self.try_colonize(g, h, content)

        return events or ["No colonization possible here."]

    def manual_mine(self, group_id: str) -> list[str]:
        g = self.get_group(group_id)
        if not g:
            return ["No such group."]

        if g.owner != self.active_player:
            return ["You don't control that group."]

        h = g.location
        if not self.game_map.is_explored(h):
            return ["Cannot mine an unexplored hex."]

        content = self.game_map.get_hex_content(h)
        events = self.try_pickup_minerals(g, h, content)

        return events or ["No mining possible here."]
