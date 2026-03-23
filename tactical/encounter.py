from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from sim.hexgrid import Hex, hex_distance
from tactical.battle_state import BattleState, ShipID
from tactical.combat import FireEvent
from tactical.facing import Facing
from tactical.fighter_combat import resolve_combat_small
from tactical.fighter_events import FighterCombatEvent
from tactical.initiative import Initiative, RNG
from tactical.squadron_state import SquadronID
from tactical.turn_orders import ShipFireOrder, ShipMoveOrder, SquadronOrder


class Phase(str, Enum):
    MOVE_SUBMISSION   = "move_submission"
    COMBAT_SUBMISSION = "combat_submission"
    COMBAT_SMALL      = "combat_small"
    COMPLETE          = "complete"


@dataclass(frozen=True, slots=True)
class Encounter:
    """Tactical encounter state machine — simultaneous-submission model.

    Phase flow:
        MOVE_SUBMISSION  → (all sides commit) → _resolve_movement()
        COMBAT_SUBMISSION → (all sides commit) → _resolve_fire()
        COMBAT_SMALL     (fighters: not yet implemented)
        COMPLETE

    Design invariants:
      - Neither side sees the other's staged orders before committing.
      - Fire resolution is simultaneous: all fire is computed against the
        pre-combat BattleState snapshot; damage is applied in one pass after
        all shots are resolved.
      - Collision resolution: higher initiative claims a contested hex;
        lower-initiative ship's move is cancelled (it stays in place).
    """

    battle:     BattleState
    initiative: Initiative
    phase:      Phase

    # MOVE_SUBMISSION bookkeeping
    _move_orders:    dict[ShipID, ShipMoveOrder]
    _move_committed: frozenset[str]   # side_ids that have committed moves

    # COMBAT_SUBMISSION bookkeeping
    # None value = explicit pass (ship will not fire this turn)
    _fire_orders:    dict[ShipID, Optional[ShipFireOrder]]
    _fire_committed: frozenset[str]   # side_ids that have committed fire orders

    # MP cap at encounter start, used for move-distance validation
    _mp_capacity: dict[ShipID, int]

    # COMBAT_SMALL bookkeeping
    _squadron_orders:    dict[SquadronID, SquadronOrder]
    _squadron_committed: frozenset[str]   # side_ids that have committed squadron orders

    # MOVE_SUBMISSION carrier launch staging
    _launch_orders: dict[str, list]   # ShipID → list[LaunchOrder]

    # Fog of war: per-side knowledge of enemy unit detection levels
    # side_id → {unit_id → detection_level}
    _knowledge: dict[str, dict[str, int]] = field(default_factory=dict)

    # Weapon systems revealed by firing: ship_id → frozenset of system indices
    # Persists across turns (a revealed weapon stays revealed).
    _revealed_systems: dict[str, frozenset[int]] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Factory                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def start(battle: BattleState, *, rng: RNG | None = None) -> "Encounter":
        from tactical.sensor_rules import compute_detections
        sides = {s.owner_id for s in battle.ships.values()}
        init  = Initiative.roll(sides, rng=rng)
        mp_cap = {sid: ship.mp for sid, ship in battle.ships.items()}
        knowledge = {side: compute_detections(battle, side) for side in sides}
        return Encounter(
            battle              = battle,
            initiative          = init,
            phase               = Phase.MOVE_SUBMISSION,
            _move_orders        = {},
            _move_committed     = frozenset(),
            _fire_orders        = {},
            _fire_committed     = frozenset(),
            _mp_capacity        = mp_cap,
            _squadron_orders    = {},
            _squadron_committed = frozenset(),
            _launch_orders      = {},
            _knowledge          = knowledge,
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def sides(self) -> frozenset[str]:
        return frozenset(s.owner_id for s in self.battle.ships.values())

    def ships_for_side(self, side_id: str) -> list[ShipID]:
        sids = [sid for sid, s in self.battle.ships.items() if s.owner_id == side_id]
        return sorted(
            sids,
            key=lambda sid: (self.battle.ships[sid].pos.q, self.battle.ships[sid].pos.r, sid),
        )

    def _require_phase(self, phase: Phase) -> None:
        if self.phase != phase:
            raise ValueError(
                f"Expected phase {phase.value!r}, current phase is {self.phase.value!r}"
            )

    def _require_not_committed(self, side_id: str, committed: frozenset[str]) -> None:
        if side_id in committed:
            raise PermissionError(
                f"Side {side_id!r} has already committed orders for this phase"
            )

    def _ship_owner(self, ship_id: ShipID) -> str:
        if ship_id not in self.battle.ships:
            raise KeyError(f"Unknown ship: {ship_id!r}")
        return self.battle.ships[ship_id].owner_id

    # ------------------------------------------------------------------ #
    # MOVE_SUBMISSION                                                       #
    # ------------------------------------------------------------------ #

    def stage_move(
        self,
        side_id: str,
        ship_id: ShipID,
        dest: Hex,
        dest_facing: Facing,
        *,
        path_cost: Optional[int] = None,
        path: tuple[Hex, ...] = (),
        final_turn_charge: Optional[int] = None,
    ) -> "Encounter":
        """Stage a movement order for ship_id.  May be called repeatedly to
        override a previous order, as long as the side hasn't committed yet.

        path_cost: if provided, used for MP validation instead of hex_distance
        (allows curved paths that use more MP than the straight-line distance).
        path: full sequence of hexes traversed (including start); used for
        transit interception detection during movement resolution.
        final_turn_charge: if provided, this exact value is stored in the order
        and applied to turn_charge after movement resolves.  Draft-based callers
        should always supply this (from d["turn_charge"]).  For direct-hex moves
        it is computed analytically below.
        """
        self._require_phase(Phase.MOVE_SUBMISSION)
        self._require_not_committed(side_id, self._move_committed)
        if self._ship_owner(ship_id) != side_id:
            raise PermissionError(f"Ship {ship_id!r} not controlled by side {side_id!r}")

        ship = self.battle.ships[ship_id]
        cap  = self._mp_capacity.get(ship_id, ship.mp)

        if path_cost is not None:
            # Draft-based move: trust the caller's cost (already turn-enforced
            # incrementally by the draft UI).
            total_cost = path_cost
            if final_turn_charge is None:
                # Caller should supply this; approximate as a fallback.
                turns_made = total_cost // ship.turn_cost if ship.turn_cost > 0 else 0
                final_turn_charge = (
                    min(max(0, ship.turn_charge + total_cost - turns_made * ship.turn_cost),
                        ship.turn_cost)
                    if ship.turn_cost > 0 else 0
                )
        else:
            # Direct hex move: compute minimum MP needed from scratch.
            dist         = hex_distance(ship.pos, dest)
            facing_delta = (int(dest_facing) - int(ship.facing)) % 6
            turns_needed = min(facing_delta, 6 - facing_delta)
            # Minimum total MP = enough to move AND to earn all needed turns.
            # Formula: max(dist, turns_needed * turn_cost - current_charge)
            # Derivation: total_mp + charge ≥ turns_needed * turn_cost
            total_cost = max(dist, turns_needed * ship.turn_cost - ship.turn_charge)
            if final_turn_charge is None:
                # After turns_needed turns the remaining charge is:
                #   initial_charge + total_cost - turns_needed * turn_cost
                # clamped to [0, turn_cost].
                if ship.turn_cost > 0:
                    remaining = ship.turn_charge + total_cost - turns_needed * ship.turn_cost
                    final_turn_charge = min(max(0, remaining), ship.turn_cost)
                else:
                    final_turn_charge = 0

        if total_cost > cap:
            raise ValueError(
                f"Ship {ship_id!r} cannot reach {dest} facing {int(dest_facing)}: "
                f"movement cost {total_cost} exceeds MP capacity {cap}"
            )

        new_orders = {**self._move_orders, ship_id: ShipMoveOrder(
            dest=dest, dest_facing=dest_facing, path=path, total_mp_cost=total_cost,
            final_turn_charge=final_turn_charge,
        )}
        return dataclasses.replace(self, _move_orders=new_orders)

    def stage_launch(
        self,
        side_id: str,
        carrier_id: str,
        squadron_id: str,
    ) -> "Encounter":
        """Stage a launch order: carrier will deploy squadron at start of movement.

        Validates ownership, docking status, and active Bl count.
        May be called multiple times to stage multiple launches (one per active Bl).
        """
        from tactical.turn_orders import LaunchOrder
        self._require_phase(Phase.MOVE_SUBMISSION)
        self._require_not_committed(side_id, self._move_committed)
        if self._ship_owner(carrier_id) != side_id:
            raise PermissionError(f"Ship {carrier_id!r} not controlled by side {side_id!r}")

        if squadron_id not in self.battle.squadrons:
            raise KeyError(f"Unknown squadron: {squadron_id!r}")
        sq = self.battle.squadrons[squadron_id]
        if sq.docked_at != carrier_id:
            raise ValueError(
                f"Squadron {squadron_id!r} is not docked at {carrier_id!r}"
            )

        carrier = self.battle.ships[carrier_id]
        bl_count = carrier.systems.launch_bay_count() if carrier.systems else 0
        existing = self._launch_orders.get(carrier_id, [])
        if len(existing) >= bl_count:
            raise ValueError(
                f"No active launch bays remaining on {carrier_id!r} "
                f"(has {bl_count}, already staging {len(existing)})"
            )

        new_launches = {**self._launch_orders, carrier_id: existing + [LaunchOrder(squadron_id=squadron_id)]}
        return dataclasses.replace(self, _launch_orders=new_launches)

    def commit_movement(self, side_id: str, rng: RNG) -> tuple["Encounter", list[FighterCombatEvent]]:
        """Mark side_id as done submitting move orders.

        When all sides have committed, movement is resolved automatically.
        Ships that did not submit a move order remain in place.
        Returns (new_encounter, transit_events) where transit_events contains
        any attack runs triggered by ships moving through enemy squadron hexes.
        """
        self._require_phase(Phase.MOVE_SUBMISSION)
        self._require_not_committed(side_id, self._move_committed)

        new_committed = self._move_committed | {side_id}
        enc = dataclasses.replace(self, _move_committed=new_committed)
        if new_committed >= enc.sides():
            return enc._resolve_movement(rng)
        return enc, []

    def _resolve_movement(self, rng: RNG) -> tuple["Encounter", list[FighterCombatEvent]]:
        """All sides have committed.  Resolve movement simultaneously."""
        from tactical.movement_resolution import resolve_movement
        new_battle, events = resolve_movement(
            self.battle,
            self._move_orders,
            self._launch_orders,
            self.initiative,
            rng,
        )
        enc = dataclasses.replace(
            self,
            battle          = new_battle,
            phase           = Phase.COMBAT_SUBMISSION,
            _move_orders    = {},
            _move_committed = frozenset(),
            _launch_orders  = {},
        )
        return enc, events

    # ------------------------------------------------------------------ #
    # COMBAT_SUBMISSION                                                     #
    # ------------------------------------------------------------------ #

    def stage_fire(
        self,
        side_id: str,
        ship_id: ShipID,
        target_id: ShipID,
    ) -> "Encounter":
        """Stage a fire order for ship_id targeting target_id.

        May be called repeatedly to override, as long as the side hasn't committed.
        Raises ValueError immediately if the target is in the attacker's blind spot.
        """
        self._require_phase(Phase.COMBAT_SUBMISSION)
        self._require_not_committed(side_id, self._fire_committed)
        if self._ship_owner(ship_id) != side_id:
            raise PermissionError(f"Ship {ship_id!r} not controlled by side {side_id!r}")
        if target_id not in self.battle.ships:
            raise KeyError(f"Unknown target: {target_id!r}")
        if ship_id == target_id:
            raise ValueError(f"Ship {ship_id!r} cannot target itself")

        # Global blind-spot check: no weapon can fire dead astern.
        from tactical.arcs import assert_can_fire
        attacker = self.battle.ships[ship_id]
        target   = self.battle.ships[target_id]
        assert_can_fire(int(attacker.facing), attacker.pos, target.pos, ship_id, target_id)

        new_orders = {**self._fire_orders, ship_id: ShipFireOrder(target_id=target_id)}
        return dataclasses.replace(self, _fire_orders=new_orders)

    def pass_fire(self, side_id: str, ship_id: ShipID) -> "Encounter":
        """Mark ship_id as explicitly not firing this turn."""
        self._require_phase(Phase.COMBAT_SUBMISSION)
        self._require_not_committed(side_id, self._fire_committed)
        if self._ship_owner(ship_id) != side_id:
            raise PermissionError(f"Ship {ship_id!r} not controlled by side {side_id!r}")

        new_orders = {**self._fire_orders, ship_id: None}
        return dataclasses.replace(self, _fire_orders=new_orders)

    def commit_fire(self, side_id: str, rng: RNG) -> tuple["Encounter", list[FireEvent]]:
        """Mark side_id as done submitting fire orders.

        When all sides have committed, fire is resolved automatically.
        Ships that submitted no order (and no explicit pass) simply do not fire.
        Returns (new_encounter, events) — events are non-empty only when resolution
        is triggered.
        """
        self._require_phase(Phase.COMBAT_SUBMISSION)
        self._require_not_committed(side_id, self._fire_committed)

        new_committed = self._fire_committed | {side_id}
        enc = dataclasses.replace(self, _fire_committed=new_committed)
        if new_committed >= enc.sides():
            return enc._resolve_fire(rng)
        return enc, []

    def _resolve_fire(self, rng: RNG) -> tuple["Encounter", list[FireEvent]]:
        """All sides committed.  Resolve all fire simultaneously."""
        from tactical.fire_resolution import resolve_fire
        new_battle, all_events, new_revealed = resolve_fire(
            self.battle,
            self._fire_orders,
            self._revealed_systems,
            rng,
        )

        # Check for battle end before advancing phase.
        end_ev = self._battle_end_event(new_battle)
        if end_ev is not None:
            all_events.append(end_ev)
            enc = dataclasses.replace(
                self,
                battle             = new_battle,
                phase              = Phase.COMPLETE,
                _fire_orders       = {},
                _fire_committed    = frozenset(),
                _revealed_systems  = new_revealed,
            )
            return enc, all_events

        enc = dataclasses.replace(
            self,
            battle             = new_battle,
            phase              = Phase.COMBAT_SMALL,
            _fire_orders       = {},
            _fire_committed    = frozenset(),
            _revealed_systems  = new_revealed,
        )
        # If no squadrons are deployed, skip COMBAT_SMALL entirely.
        if not enc.battle.squadrons:
            enc, turn_events = enc.next_turn()
            return enc, all_events + turn_events
        return enc, all_events

    # ------------------------------------------------------------------ #
    # COMBAT_SMALL                                                         #
    # ------------------------------------------------------------------ #

    def stage_squadron_order(
        self,
        side_id: str,
        squadron_id: SquadronID,
        order: SquadronOrder,
    ) -> "Encounter":
        """Stage an INTERCEPT or STRIKE order for squadron_id.

        May be called repeatedly to override, as long as the side hasn't committed.
        """
        self._require_phase(Phase.COMBAT_SMALL)
        self._require_not_committed(side_id, self._squadron_committed)
        if squadron_id not in self.battle.squadrons:
            raise KeyError(f"Unknown squadron: {squadron_id!r}")
        sq = self.battle.squadrons[squadron_id]
        if sq.owner_id != side_id:
            raise PermissionError(
                f"Squadron {squadron_id!r} not controlled by side {side_id!r}"
            )

        new_orders = {**self._squadron_orders, squadron_id: order}
        return dataclasses.replace(self, _squadron_orders=new_orders)

    def commit_squadron_orders(
        self,
        side_id: str,
        rng: RNG,
    ) -> tuple["Encounter", list[FighterCombatEvent]]:
        """Mark side_id as done submitting squadron orders.

        When all sides have committed, COMBAT_SMALL resolves automatically.
        Squadrons that received no order stay in place and do not engage.
        Returns (new_encounter, events) — events are non-empty only when
        resolution fires.
        """
        self._require_phase(Phase.COMBAT_SMALL)
        self._require_not_committed(side_id, self._squadron_committed)

        new_committed = self._squadron_committed | {side_id}
        enc = dataclasses.replace(self, _squadron_committed=new_committed)
        if new_committed >= enc.sides():
            return enc._resolve_combat_small(rng)
        return enc, []

    def _resolve_combat_small(
        self,
        rng: RNG,
    ) -> tuple["Encounter", list[FighterCombatEvent]]:
        """All sides committed.  Resolve fighter movement and combat."""
        from tactical.events import RecoveryEvent
        from tactical.turn_orders import RecoverOrder

        all_events: list = []
        new_battle = self.battle

        # Process recovery orders before fighter combat.
        # Each active Bl can support at most one recovery per turn.
        recoveries_this_turn: dict[str, int] = {}  # carrier_id → count
        non_recovery_orders: dict = {}
        for sq_id, order in self._squadron_orders.items():
            if not isinstance(order, RecoverOrder):
                non_recovery_orders[sq_id] = order
                continue
            carrier_id = order.carrier_id
            if sq_id not in new_battle.squadrons or carrier_id not in new_battle.ships:
                continue
            sq = new_battle.squadrons[sq_id]
            carrier = new_battle.ships[carrier_id]
            if sq.pos != carrier.pos:
                continue  # not at carrier hex — silently ignore
            if carrier.systems is None:
                continue
            bl_count = carrier.systems.launch_bay_count()
            if recoveries_this_turn.get(carrier_id, 0) >= bl_count:
                continue  # no Bl slots remaining — silently ignore
            has_empty_bh = any(
                s.is_active() and s.token == "Bh" and s.occupant is None
                for s in carrier.systems
            )
            if not has_empty_bh:
                continue  # no Bh room — silently ignore
            new_sys = carrier.systems.dock_squadron(sq_id)
            carrier = dataclasses.replace(carrier, systems=new_sys)
            new_battle = new_battle.with_ship(carrier)
            new_sq = sq.dock(carrier_id)
            new_battle = new_battle.with_squadron(new_sq)
            recoveries_this_turn[carrier_id] = recoveries_this_turn.get(carrier_id, 0) + 1
            all_events.append(RecoveryEvent(squadron_id=sq_id, carrier_id=carrier_id))

        new_battle, fighter_events = resolve_combat_small(
            new_battle,
            non_recovery_orders,
            rng=rng,
        )
        all_events.extend(fighter_events)

        # Check for battle end before advancing to next turn.
        end_ev = self._battle_end_event(new_battle)
        if end_ev is not None:
            all_events.append(end_ev)
            enc = dataclasses.replace(
                self,
                battle              = new_battle,
                phase               = Phase.COMPLETE,
                _squadron_orders    = {},
                _squadron_committed = frozenset(),
            )
            return enc, all_events

        enc = dataclasses.replace(
            self,
            battle              = new_battle,
            _squadron_orders    = {},
            _squadron_committed = frozenset(),
        )
        enc, turn_events = enc.next_turn()
        return enc, all_events + turn_events

    def next_turn(self) -> tuple["Encounter", list]:
        """Advance to a fresh MOVE_SUBMISSION phase for the next turn.

        Recomputes each ship's MP capacity from its current systems state so
        that engine damage is reflected in movement allowance going forward.
        Turn charge is preserved (it persists across turns by design).

        Returns (new_encounter, events) where events may contain:
          - FuelWarningEvent  — squadron has 1 turn of fuel left (fires now,
                                squadron still active next turn)
          - UnitDestroyedEvent(cause=FUEL_EXHAUSTED) — squadron ran out of
                                fuel and is destroyed
        """
        from tactical.events import DestructionCause, FuelWarningEvent, UnitDestroyedEvent
        from tactical.turn_orders import InterceptOrder

        new_ships: dict[ShipID, object] = {}
        new_mp_capacity: dict[ShipID, int] = {}

        for ship_id, ship in self.battle.ships.items():
            cap = self._mp_capacity_for(ship)
            new_ships[ship_id] = dataclasses.replace(ship, mp=cap)
            new_mp_capacity[ship_id] = cap

        # Decrement endurance; emit warnings and destruction events.
        new_squads = {}
        turn_events: list = []
        for sqid, sq in self.battle.squadrons.items():
            if not sq.is_deployed:
                new_squads[sqid] = sq  # docked squadrons are preserved as-is
                continue
            if sq.endurance == 1:
                # Will reach 0 after this decrement — warn before destroying.
                turn_events.append(FuelWarningEvent(sqid))
            updated = sq.decrement_endurance()
            if updated.endurance > 0:
                new_squads[sqid] = updated
            else:
                # Fuel exhausted — squadron destroyed.
                turn_events.append(UnitDestroyedEvent(sqid, DestructionCause.FUEL_EXHAUSTED))

        # Preserve InterceptOrders as standing patrol orders across turns.
        # StrikeOrders are one-time and are cleared.
        carried_squadron_orders = {
            sq_id: order
            for sq_id, order in self._squadron_orders.items()
            if isinstance(order, InterceptOrder) and sq_id in new_squads
        }

        from tactical.sensor_rules import compute_detections, update_knowledge
        new_battle_state = dataclasses.replace(self.battle, ships=new_ships, squadrons=new_squads)
        all_sides = {s.owner_id for s in new_ships.values()}
        new_knowledge = {}
        for side in all_sides:
            current = compute_detections(new_battle_state, side)
            new_knowledge[side] = update_knowledge(self._knowledge.get(side, {}), current)

        enc = dataclasses.replace(
            self,
            battle              = new_battle_state,
            phase               = Phase.MOVE_SUBMISSION,
            _move_orders        = {},
            _move_committed     = frozenset(),
            _fire_orders        = {},
            _fire_committed     = frozenset(),
            _mp_capacity        = new_mp_capacity,
            _squadron_orders    = carried_squadron_orders,
            _squadron_committed = frozenset(),
            _launch_orders      = {},
            _knowledge          = new_knowledge,
        )
        return enc, turn_events

    @staticmethod
    def _battle_end_event(battle: BattleState):
        """Return a BattleEndEvent if the battle is over, else None.

        A side is eliminated when every one of its ships has is_destroyed()
        True (all non-shield/armor systems gone).  Both sides can be eliminated
        simultaneously via simultaneous fire — that's a draw.
        """
        from tactical.events import BattleEndEvent
        all_sides  = {s.owner_id for s in battle.ships.values()}
        alive      = {
            s.owner_id for s in battle.ships.values()
            if s.systems is None or not s.systems.is_destroyed()
        }
        if alive < all_sides:          # at least one side eliminated
            return BattleEndEvent(surviving_sides=frozenset(alive))
        return None

    @staticmethod
    def _mp_capacity_for(ship) -> int:
        """Compute current MP capacity from a ship's live systems state."""
        if ship.systems is not None:
            epr = ship.hull_type.engine_power_ratio if ship.hull_type is not None else None
            mp  = ship.systems.movement_points(engine_power_ratio=epr)
            if ship.hull_type is not None:
                mp = min(mp, ship.hull_type.max_speed)
            return mp
        return ship.mp  # no systems: keep current value
