from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from tactical.battle_state import BattleState, ShipID
from tactical.initiative import Initiative, RNG


class Phase(str, Enum):
    MOVEMENT = "movement"
    COMBAT_LARGE = "combat_large"
    COMBAT_SMALL = "combat_small"
    COMPLETE = "complete"


def _ceil_div(a: int, b: int) -> int:
    if b <= 0:
        raise ValueError("b must be >= 1")
    if a <= 0:
        return 0
    return (a + b - 1) // b


@dataclass(frozen=True, slots=True)
class Encounter:
    """Tactical encounter state machine (MVP).

    Changes vs earlier:
      - MP refresh happens at the start of EACH movement subphase.
      - Required spend for a ship in a subphase is computed from that subphase's refreshed MP:
          required = ceil(mp_start_this_subphase / movement_subphases)
      - Initiative ties are resolved by rerolling tied sides (see Initiative.roll).
    """

    battle: BattleState
    initiative: Initiative

    phase: Phase = Phase.MOVEMENT

    movement_subphases: int = 3
    movement_subphase_index: int = 0  # 0..movement_subphases-1

    # Movement side whose move is currently executing (low -> high)
    active_side_index: int = 0

    # Baseline MP "design cap" per ship at encounter start (used when no ShipSystems)
    mp_capacity_base: dict[ShipID, int] = None

    # MP at start of THIS movement subphase (after refresh)
    mp_start_this_subphase: dict[ShipID, int] = None

    # MP spent in THIS movement subphase per ship
    mp_spent_this_subphase: dict[ShipID, int] = None

    # Combat bookkeeping
    spent_to_fire: set[ShipID] = None
    active_combat_side_index: int = 0

    # ---------------------------- construction -----------------------------

    @staticmethod
    def start(battle: BattleState, *, rng: RNG | None = None, movement_subphases: int = 3) -> Encounter:
        if movement_subphases <= 0:
            raise ValueError("movement_subphases must be >= 1")

        sides = {s.owner_id for s in battle.ships.values()}
        init = Initiative.roll(sides, rng=rng)

        base = {sid: ship.mp for sid, ship in battle.ships.items()}

        enc0 = Encounter(
            battle=battle,
            initiative=init,
            phase=Phase.MOVEMENT,
            movement_subphases=movement_subphases,
            movement_subphase_index=0,
            active_side_index=0,
            mp_capacity_base=base,
            mp_start_this_subphase={},
            mp_spent_this_subphase={},
            spent_to_fire=set(),
            active_combat_side_index=0,
        )
        return enc0._refresh_movement_subphase_mp()

    # ---------------------------- ordering helpers -----------------------------

    def movement_side_order(self) -> list[str]:
        return self.initiative.order_low_to_high()

    def combat_side_order(self) -> list[str]:
        return self.initiative.order_high_to_low()

    def active_side(self) -> str:
        order = self.movement_side_order()
        if not order:
            raise ValueError("No sides in encounter")
        return order[self.active_side_index % len(order)]

    def active_combat_side(self) -> str:
        order = self.combat_side_order()
        if not order:
            raise ValueError("No sides in encounter")
        return order[self.active_combat_side_index % len(order)]

    def ships_for_side(self, side_id: str) -> list[ShipID]:
        sids = [sid for sid, s in self.battle.ships.items() if s.owner_id == side_id]
        return sorted(sids, key=lambda sid: (self.battle.ships[sid].pos.q, self.battle.ships[sid].pos.r, sid))

    # ---------------------------- MP refresh + requirements -----------------------------

    def _capacity_for_ship(self, ship_id: ShipID) -> int:
        ship = self.battle.ships[ship_id]
        # If we have ship systems, use its movement points as current capacity.
        if ship.systems is not None:
            return ship.systems.movement_points()
        # Otherwise fall back to baseline captured at encounter start.
        return int(self.mp_capacity_base.get(ship_id, ship.mp))

    def _refresh_movement_subphase_mp(self) -> Encounter:
        """Refresh ship.mp for the start of the current movement subphase.

        Does NOT touch turn_charge (your rule: it persists unless a turn is taken).
        """
        new_ships = dict(self.battle.ships)
        mp_start: dict[ShipID, int] = {}

        for sid, ship in self.battle.ships.items():
            cap = self._capacity_for_ship(sid)
            # Refresh MP to capacity
            refreshed = type(ship)(
                ship_id=ship.ship_id,
                owner_id=ship.owner_id,
                pos=ship.pos,
                facing=ship.facing,
                mp=cap,
                turn_cost=ship.turn_cost,
                turn_charge=ship.turn_charge,  # persists across phases/turns
                systems=ship.systems,
            )
            new_ships[sid] = refreshed
            mp_start[sid] = cap

        new_battle = BattleState(new_ships)
        return Encounter(
            battle=new_battle,
            initiative=self.initiative,
            phase=self.phase,
            movement_subphases=self.movement_subphases,
            movement_subphase_index=self.movement_subphase_index,
            active_side_index=self.active_side_index,
            mp_capacity_base=self.mp_capacity_base,
            mp_start_this_subphase=mp_start,
            mp_spent_this_subphase={},  # fresh per subphase
            spent_to_fire=self.spent_to_fire,
            active_combat_side_index=self.active_combat_side_index,
        )

    def required_spend_this_subphase(self, ship_id: ShipID) -> int:
        start = int(self.mp_start_this_subphase.get(ship_id, 0))
        return _ceil_div(start, self.movement_subphases)

    def spent_this_subphase(self, ship_id: ShipID) -> int:
        return int(self.mp_spent_this_subphase.get(ship_id, 0))

    def _record_spend(self, ship_id: ShipID, delta_spent: int) -> dict[ShipID, int]:
        new_map = dict(self.mp_spent_this_subphase)
        new_map[ship_id] = new_map.get(ship_id, 0) + max(0, delta_spent)
        return new_map

    # ---------------------------- movement actions -----------------------------

    def _require_movement_phase(self) -> None:
        if self.phase != Phase.MOVEMENT:
            raise ValueError(f"Not in movement phase (phase={self.phase})")

    def _require_active_side(self, side_id: str) -> None:
        if side_id != self.active_side():
            raise PermissionError(f"Side {side_id!r} is not active (active={self.active_side()!r})")

    def move_ship_forward(self, side_id: str, ship_id: ShipID, steps: int = 1) -> Encounter:
        self._require_movement_phase()
        self._require_active_side(side_id)

        ship = self.battle.ships[ship_id]
        if ship.owner_id != side_id:
            raise PermissionError(f"Ship {ship_id!r} not controlled by side {side_id!r}")

        before_mp = ship.mp
        new_battle = self.battle.move_ship_forward(ship_id, steps=steps)
        after_mp = new_battle.ships[ship_id].mp
        delta = before_mp - after_mp

        return Encounter(
            battle=new_battle,
            initiative=self.initiative,
            phase=self.phase,
            movement_subphases=self.movement_subphases,
            movement_subphase_index=self.movement_subphase_index,
            active_side_index=self.active_side_index,
            mp_capacity_base=self.mp_capacity_base,
            mp_start_this_subphase=self.mp_start_this_subphase,
            mp_spent_this_subphase=self._record_spend(ship_id, delta),
            spent_to_fire=self.spent_to_fire,
            active_combat_side_index=self.active_combat_side_index,
        )

    def turn_ship_left(self, side_id: str, ship_id: ShipID, *, auto_spend: bool = False) -> Encounter:
        """Turn left (one facing step). If auto_spend, spend missing MP to charge first."""
        self._require_movement_phase()
        self._require_active_side(side_id)

        ship = self.battle.ships[ship_id]
        if ship.owner_id != side_id:
            raise PermissionError(f"Ship {ship_id!r} not controlled by side {side_id!r}")

        before_mp = ship.mp
        new_ship = ship.turn_left_auto() if auto_spend else ship.turn_left()
        after_mp = new_ship.mp
        delta = before_mp - after_mp  # counts toward subphase spend if auto_spend

        new_battle = self.battle.with_ship(new_ship)
        return Encounter(
            battle=new_battle,
            initiative=self.initiative,
            phase=self.phase,
            movement_subphases=self.movement_subphases,
            movement_subphase_index=self.movement_subphase_index,
            active_side_index=self.active_side_index,
            mp_capacity_base=self.mp_capacity_base,
            mp_start_this_subphase=self.mp_start_this_subphase,
            mp_spent_this_subphase=self._record_spend(ship_id, delta),
            spent_to_fire=self.spent_to_fire,
            active_combat_side_index=self.active_combat_side_index,
        )

    def turn_ship_right(self, side_id: str, ship_id: ShipID, *, auto_spend: bool = False) -> Encounter:
        """Turn right (one facing step). If auto_spend, spend missing MP to charge first."""
        self._require_movement_phase()
        self._require_active_side(side_id)

        ship = self.battle.ships[ship_id]
        if ship.owner_id != side_id:
            raise PermissionError(f"Ship {ship_id!r} not controlled by side {side_id!r}")

        before_mp = ship.mp
        new_ship = ship.turn_right_auto() if auto_spend else ship.turn_right()
        after_mp = new_ship.mp
        delta = before_mp - after_mp

        new_battle = self.battle.with_ship(new_ship)
        return Encounter(
            battle=new_battle,
            initiative=self.initiative,
            phase=self.phase,
            movement_subphases=self.movement_subphases,
            movement_subphase_index=self.movement_subphase_index,
            active_side_index=self.active_side_index,
            mp_capacity_base=self.mp_capacity_base,
            mp_start_this_subphase=self.mp_start_this_subphase,
            mp_spent_this_subphase=self._record_spend(ship_id, delta),
            spent_to_fire=self.spent_to_fire,
            active_combat_side_index=self.active_combat_side_index,
        )

    def spend_mp(self, side_id: str, ship_id: ShipID, amount: int) -> Encounter:
        self._require_movement_phase()
        self._require_active_side(side_id)

        ship = self.battle.ships[ship_id]
        if ship.owner_id != side_id:
            raise PermissionError(f"Ship {ship_id!r} not controlled by side {side_id!r}")

        before_mp = ship.mp
        new_ship = ship.spend_mp(amount)
        after_mp = new_ship.mp
        delta = before_mp - after_mp

        new_battle = self.battle.with_ship(new_ship)
        return Encounter(
            battle=new_battle,
            initiative=self.initiative,
            phase=self.phase,
            movement_subphases=self.movement_subphases,
            movement_subphase_index=self.movement_subphase_index,
            active_side_index=self.active_side_index,
            mp_capacity_base=self.mp_capacity_base,
            mp_start_this_subphase=self.mp_start_this_subphase,
            mp_spent_this_subphase=self._record_spend(ship_id, delta),
            spent_to_fire=self.spent_to_fire,
            active_combat_side_index=self.active_combat_side_index,
        )

    def end_side_movement(self, side_id: str) -> Encounter:
        self._require_movement_phase()
        self._require_active_side(side_id)

        ship_ids = self.ships_for_side(side_id)
        for sid in ship_ids:
            required = self.required_spend_this_subphase(sid)
            spent = self.spent_this_subphase(sid)
            if spent < required:
                raise ValueError(
                    f"Side {side_id!r} cannot end movement: ship {sid!r} spent {spent} < required {required}"
                )

        order = self.movement_side_order()
        next_side_index = self.active_side_index + 1

        # More sides in this subphase => advance active side
        if next_side_index < len(order):
            return Encounter(
                battle=self.battle,
                initiative=self.initiative,
                phase=self.phase,
                movement_subphases=self.movement_subphases,
                movement_subphase_index=self.movement_subphase_index,
                active_side_index=next_side_index,
                mp_capacity_base=self.mp_capacity_base,
                mp_start_this_subphase=self.mp_start_this_subphase,
                mp_spent_this_subphase=self.mp_spent_this_subphase,
                spent_to_fire=self.spent_to_fire,
                active_combat_side_index=self.active_combat_side_index,
            )

        # End of subphase: next subphase or transition to combat.
        next_subphase = self.movement_subphase_index + 1
        if next_subphase < self.movement_subphases:
            enc_next = Encounter(
                battle=self.battle,
                initiative=self.initiative,
                phase=self.phase,
                movement_subphases=self.movement_subphases,
                movement_subphase_index=next_subphase,
                active_side_index=0,
                mp_capacity_base=self.mp_capacity_base,
                mp_start_this_subphase=self.mp_start_this_subphase,
                mp_spent_this_subphase={},  # will be replaced by refresh
                spent_to_fire=self.spent_to_fire,
                active_combat_side_index=self.active_combat_side_index,
            )
            return enc_next._refresh_movement_subphase_mp()

        # Movement complete -> start combat (large units)
        return Encounter(
            battle=self.battle,
            initiative=self.initiative,
            phase=Phase.COMBAT_LARGE,
            movement_subphases=self.movement_subphases,
            movement_subphase_index=self.movement_subphase_index,
            active_side_index=0,
            mp_capacity_base=self.mp_capacity_base,
            mp_start_this_subphase=self.mp_start_this_subphase,
            mp_spent_this_subphase=self.mp_spent_this_subphase,
            spent_to_fire=set(),
            active_combat_side_index=0,
        )

    # ---------------------------- combat (large) scaffolding -----------------------------

    def _require_combat_large(self) -> None:
        if self.phase != Phase.COMBAT_LARGE:
            raise ValueError(f"Not in COMBAT_LARGE phase (phase={self.phase})")

    def active_large_combat_side(self) -> str:
        self._require_combat_large()
        return self.active_combat_side()

    def choose_unit_to_fire(self, side_id: str, ship_id: ShipID) -> Encounter:
        self._require_combat_large()
        if side_id != self.active_large_combat_side():
            raise PermissionError(f"Side {side_id!r} is not active (active={self.active_large_combat_side()!r})")

        ship = self.battle.ships[ship_id]
        if ship.owner_id != side_id:
            raise PermissionError(f"Ship {ship_id!r} not controlled by side {side_id!r}")
        if ship_id in self.spent_to_fire:
            raise ValueError(f"Ship {ship_id!r} already spent in this combat subphase")

        new_spent = set(self.spent_to_fire)
        new_spent.add(ship_id)

        return Encounter(
            battle=self.battle,
            initiative=self.initiative,
            phase=self.phase,
            movement_subphases=self.movement_subphases,
            movement_subphase_index=self.movement_subphase_index,
            active_side_index=self.active_side_index,
            mp_capacity_base=self.mp_capacity_base,
            mp_start_this_subphase=self.mp_start_this_subphase,
            mp_spent_this_subphase=self.mp_spent_this_subphase,
            spent_to_fire=new_spent,
            active_combat_side_index=self.active_combat_side_index,
        )

    def pass_fire(self, side_id: str, ship_id: ShipID) -> Encounter:
        return self.choose_unit_to_fire(side_id, ship_id)

    def advance_combat_turn(self) -> Encounter:
        self._require_combat_large()
        order = self.combat_side_order()

        next_idx = self.active_combat_side_index + 1
        if next_idx < len(order):
            return Encounter(
                battle=self.battle,
                initiative=self.initiative,
                phase=self.phase,
                movement_subphases=self.movement_subphases,
                movement_subphase_index=self.movement_subphase_index,
                active_side_index=self.active_side_index,
                mp_capacity_base=self.mp_capacity_base,
                mp_start_this_subphase=self.mp_start_this_subphase,
                mp_spent_this_subphase=self.mp_spent_this_subphase,
                spent_to_fire=self.spent_to_fire,
                active_combat_side_index=next_idx,
            )

        all_ships = set(self.battle.ships.keys())
        if self.spent_to_fire >= all_ships:
            return Encounter(
                battle=self.battle,
                initiative=self.initiative,
                phase=Phase.COMBAT_SMALL,
                movement_subphases=self.movement_subphases,
                movement_subphase_index=self.movement_subphase_index,
                active_side_index=self.active_side_index,
                mp_capacity_base=self.mp_capacity_base,
                mp_start_this_subphase=self.mp_start_this_subphase,
                mp_spent_this_subphase=self.mp_spent_this_subphase,
                spent_to_fire=set(),
                active_combat_side_index=0,
            )

        return Encounter(
            battle=self.battle,
            initiative=self.initiative,
            phase=self.phase,
            movement_subphases=self.movement_subphases,
            movement_subphase_index=self.movement_subphase_index,
            active_side_index=self.active_side_index,
            mp_capacity_base=self.mp_capacity_base,
            mp_start_this_subphase=self.mp_start_this_subphase,
            mp_spent_this_subphase=self.mp_spent_this_subphase,
            spent_to_fire=self.spent_to_fire,
            active_combat_side_index=0,
        )
