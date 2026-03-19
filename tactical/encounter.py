from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from sim.hexgrid import Hex
from tactical.battle_state import BattleState, ShipID
from tactical.combat import FireEvent, resolve_fire_all, hex_distance
from tactical.facing import Facing
from tactical.initiative import Initiative, RNG
from tactical.turn_orders import ShipFireOrder, ShipMoveOrder
from tactical.weapons import WEAPONS


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

    # ------------------------------------------------------------------ #
    # Factory                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def start(battle: BattleState, *, rng: RNG | None = None) -> "Encounter":
        sides = {s.owner_id for s in battle.ships.values()}
        init  = Initiative.roll(sides, rng=rng)
        mp_cap = {sid: ship.mp for sid, ship in battle.ships.items()}
        return Encounter(
            battle           = battle,
            initiative       = init,
            phase            = Phase.MOVE_SUBMISSION,
            _move_orders     = {},
            _move_committed  = frozenset(),
            _fire_orders     = {},
            _fire_committed  = frozenset(),
            _mp_capacity     = mp_cap,
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
    ) -> "Encounter":
        """Stage a movement order for ship_id.  May be called repeatedly to
        override a previous order, as long as the side hasn't committed yet.

        path_cost: if provided, used for MP validation instead of hex_distance
        (allows curved paths that use more MP than the straight-line distance).
        """
        self._require_phase(Phase.MOVE_SUBMISSION)
        self._require_not_committed(side_id, self._move_committed)
        if self._ship_owner(ship_id) != side_id:
            raise PermissionError(f"Ship {ship_id!r} not controlled by side {side_id!r}")

        ship = self.battle.ships[ship_id]
        dist = path_cost if path_cost is not None else hex_distance(ship.pos, dest)
        cap  = self._mp_capacity.get(ship_id, ship.mp)
        if dist > cap:
            raise ValueError(
                f"Ship {ship_id!r} cannot reach {dest}: "
                f"movement cost {dist} exceeds MP capacity {cap}"
            )

        new_orders = {**self._move_orders, ship_id: ShipMoveOrder(dest=dest, dest_facing=dest_facing)}
        return dataclasses.replace(self, _move_orders=new_orders)

    def commit_movement(self, side_id: str) -> "Encounter":
        """Mark side_id as done submitting move orders.

        When all sides have committed, movement is resolved automatically.
        Ships that did not submit a move order remain in place.
        """
        self._require_phase(Phase.MOVE_SUBMISSION)
        self._require_not_committed(side_id, self._move_committed)

        new_committed = self._move_committed | {side_id}
        enc = dataclasses.replace(self, _move_committed=new_committed)
        if new_committed >= enc.sides():
            return enc._resolve_movement()
        return enc

    def _resolve_movement(self) -> "Encounter":
        """All sides have committed.  Resolve movement simultaneously."""
        ships = self.battle.ships

        # Desired destination for each ship (default: stay in place)
        desired: dict[ShipID, Hex] = {sid: s.pos for sid, s in ships.items()}
        for ship_id, order in self._move_orders.items():
            desired[ship_id] = order.dest

        # Find destination conflicts
        dest_to_ships: dict[Hex, list[ShipID]] = {}
        for sid, dest in desired.items():
            dest_to_ships.setdefault(dest, []).append(sid)

        # Resolve conflicts: higher initiative wins, losers are cancelled
        cancelled: set[ShipID] = set()
        for dest, claimants in dest_to_ships.items():
            if len(claimants) <= 1:
                continue
            ranked = sorted(
                claimants,
                key=lambda sid: self.initiative.rolls.get(ships[sid].owner_id, 0),
                reverse=True,
            )
            for loser in ranked[1:]:
                cancelled.add(loser)

        # Apply movement for non-cancelled ships that submitted orders
        new_ships = dict(ships)
        for ship_id, order in self._move_orders.items():
            if ship_id in cancelled:
                continue
            ship = new_ships[ship_id]
            dist = hex_distance(ship.pos, order.dest)
            new_ships[ship_id] = dataclasses.replace(
                ship,
                pos    = order.dest,
                facing = order.dest_facing,
                mp     = max(0, ship.mp - dist),
            )

        return dataclasses.replace(
            self,
            battle          = BattleState(new_ships),
            phase           = Phase.COMBAT_SUBMISSION,
            _move_orders    = {},
            _move_committed = frozenset(),
        )

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
        attacker = self.battle.ships[ship_id]
        target   = self.battle.ships[target_id]
        dq = target.pos.q - attacker.pos.q
        dr = target.pos.r - attacker.pos.r
        from tactical.arcs import relative_bearing, REAR_BEARINGS
        rb = relative_bearing(int(attacker.facing), dq, dr)
        if rb in REAR_BEARINGS:
            raise ValueError(
                f"{ship_id} cannot fire at {target_id}: "
                f"target is in blind spot (relative bearing {rb})"
            )

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
        """All sides committed.  Resolve all fire simultaneously.

        Simultaneity rule: every attacker fires against the pre-combat BattleState
        snapshot (so a ship destroyed by fire this phase still fires back).
        Damage from all events is accumulated per target and applied in one pass
        after all shots are resolved.
        """
        snapshot   = self.battle
        all_events: list[FireEvent] = []

        # Accumulate (raw_damage, WeaponSpec) per target
        damage_queue: dict[ShipID, list] = {}

        for ship_id, order in self._fire_orders.items():
            if order is None:
                continue
            target_id = order.target_id
            if ship_id not in snapshot.ships or target_id not in snapshot.ships:
                continue
            try:
                _, events = resolve_fire_all(
                    snapshot,
                    attacker_id=ship_id,
                    target_id=target_id,
                    rng=rng,
                )
            except (ValueError, KeyError):
                # Arc violation or other invalid order — silently skip
                continue

            all_events.extend(events)
            for ev in events:
                if ev.hit and ev.raw_damage > 0:
                    damage_queue.setdefault(ev.target_id, []).append(
                        (ev.raw_damage, WEAPONS[ev.weapon])
                    )

        # Apply all accumulated damage to each target, starting from snapshot state
        new_battle = snapshot
        for target_id, damages in damage_queue.items():
            ship = new_battle.ships[target_id]
            if ship.systems is None:
                continue
            new_systems = ship.systems
            for dmg, spec in damages:
                new_systems = new_systems.apply_weapon_damage(dmg, weapon=spec)
            new_battle = new_battle.with_ship(dataclasses.replace(ship, systems=new_systems))

        enc = dataclasses.replace(
            self,
            battle          = new_battle,
            phase           = Phase.COMBAT_SMALL,
            _fire_orders    = {},
            _fire_committed = frozenset(),
        )
        # COMBAT_SMALL (fighters) not yet implemented — advance to next turn automatically.
        return enc.next_turn(), all_events

    def next_turn(self) -> "Encounter":
        """Advance to a fresh MOVE_SUBMISSION phase for the next turn.

        Recomputes each ship's MP capacity from its current systems state so
        that engine damage is reflected in movement allowance going forward.
        Turn charge is preserved (it persists across turns by design).
        """
        new_ships: dict[ShipID, object] = {}
        new_mp_capacity: dict[ShipID, int] = {}

        for ship_id, ship in self.battle.ships.items():
            cap = self._mp_capacity_for(ship)
            new_ships[ship_id] = dataclasses.replace(ship, mp=cap)
            new_mp_capacity[ship_id] = cap

        return dataclasses.replace(
            self,
            battle          = BattleState(new_ships),
            phase           = Phase.MOVE_SUBMISSION,
            _move_orders    = {},
            _move_committed = frozenset(),
            _fire_orders    = {},
            _fire_committed = frozenset(),
            _mp_capacity    = new_mp_capacity,
        )

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
