from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sim.hexgrid import Hex, hex_distance
from tactical.facing import Facing
from tactical.movement import compute_move_forward
from tactical.ship_systems import ShipSystems

if TYPE_CHECKING:
    from tactical.hull_types import HullType


@dataclass(frozen=True, slots=True)
class ShipState:
    """Tactical ship state (MVP).

    Turn model:
      - Spending MP (moving or idle) charges turning, capped at turn_cost.
      - Turning is free once fully charged (turn_charge == turn_cost).
      - After any turn, turn_charge resets to 0.
    """

    ship_id: str
    owner_id: str

    pos: Hex
    facing: Facing

    mp: int  # movement points remaining this activation/turn
    turn_cost: int  # MP required (spent) to earn a turn
    turn_charge: int = 0  # in [0, turn_cost]

    systems: ShipSystems | None = None
    hull_type: HullType | None = None

    # ---------------------------------------------------------------------
    # Invariants / helpers
    # ---------------------------------------------------------------------

    def __post_init__(self) -> None:
        if self.turn_cost <= 0:
            raise ValueError(f"turn_cost must be >= 1, got {self.turn_cost!r}")
        if not (0 <= self.turn_charge <= self.turn_cost):
            raise ValueError(
                f"turn_charge must be in [0, turn_cost={self.turn_cost}], "
                f"got {self.turn_charge!r}"
            )

    def _clamped_charge(self, charge: int) -> int:
        if charge < 0:
            return 0
        if charge > self.turn_cost:
            return self.turn_cost
        return charge

    def reachable_positions(
        self,
        cap: int,
        occupied: frozenset[Hex] = frozenset(),
    ) -> dict[tuple[Hex, Facing], int]:
        """Return {(dest, dest_facing): min_mp_cost} for all positions reachable in ≤ cap MP.

        Uses exact 0-1 BFS.  This is the single canonical reachability check
        shared by the AI and stage_move validation.
        """
        from tactical.movement import bfs_reachable
        return bfs_reachable(
            self.pos, self.facing, self.turn_charge, self.turn_cost, cap, occupied
        )

    def min_mp_to_reach(self, dest: Hex, dest_facing: Facing) -> int:
        """Lower-bound estimate of MP needed to reach dest at dest_facing.

        Only exact for 0 or 1 turns; underestimates for 2+ turns (charge resets
        after each turn so you cannot bank it across turns).  Kept for quick
        pre-filtering; use reachable_positions() for authoritative checks.
        """
        dist = hex_distance(self.pos, dest)
        facing_delta = (int(dest_facing) - int(self.facing)) % 6
        turns_needed = min(facing_delta, 6 - facing_delta)
        return max(dist, turns_needed * self.turn_cost - self.turn_charge)

    def can_turn(self) -> bool:
        return self.turn_charge >= self.turn_cost

    # ---------------------------------------------------------------------
    # Spending MP (charges turning)
    # ---------------------------------------------------------------------

    def spend_mp(self, amount: int) -> ShipState:
        """Spend MP without moving (idle thrust), charging turn meter."""
        if amount < 0:
            raise ValueError("amount must be >= 0")
        if amount > self.mp:
            raise ValueError(f"Insufficient MP: mp={self.mp}, amount={amount}")

        new_mp = self.mp - amount
        new_charge = self._clamped_charge(self.turn_charge + amount)
        return ShipState(
            ship_id=self.ship_id,
            owner_id=self.owner_id,
            pos=self.pos,
            facing=self.facing,
            mp=new_mp,
            turn_cost=self.turn_cost,
            turn_charge=new_charge,
            systems=self.systems,
            hull_type=self.hull_type,
        )

    def move_forward(self, steps: int = 1, *, occupied: set[Hex] | None = None) -> ShipState:
        """Move forward `steps` hexes, spending MP and charging turn meter.

        Occupancy rule (MVP):
          - ships may pass through occupied hexes
          - ships may NOT end movement in an occupied hex
        """
        end, new_mp, _ = compute_move_forward(self.pos, self.facing, mp=self.mp, steps=steps, occupied=occupied)
        new_charge = self._clamped_charge(self.turn_charge + steps)
        return ShipState(
            ship_id=self.ship_id,
            owner_id=self.owner_id,
            pos=end,
            facing=self.facing,
            mp=new_mp,
            turn_cost=self.turn_cost,
            turn_charge=new_charge,
            systems=self.systems,
            hull_type=self.hull_type,
        )

    # ---------------------------------------------------------------------
    # Turning (free, gated by charge, resets charge)
    # ---------------------------------------------------------------------

    def turn_left(self) -> ShipState:
        if not self.can_turn():
            raise ValueError(
                f"Cannot turn: turn_charge={self.turn_charge}, turn_cost={self.turn_cost}"
            )
        return ShipState(
            ship_id=self.ship_id,
            owner_id=self.owner_id,
            pos=self.pos,
            facing=self.facing.left(1),
            mp=self.mp,
            turn_cost=self.turn_cost,
            turn_charge=0,
            systems=self.systems,
            hull_type=self.hull_type,
        )

    def turn_right(self) -> ShipState:
        if not self.can_turn():
            raise ValueError(
                f"Cannot turn: turn_charge={self.turn_charge}, turn_cost={self.turn_cost}"
            )
        return ShipState(
            ship_id=self.ship_id,
            owner_id=self.owner_id,
            pos=self.pos,
            facing=self.facing.right(1),
            mp=self.mp,
            turn_cost=self.turn_cost,
            turn_charge=0,
            systems=self.systems,
            hull_type=self.hull_type,
        )

    def missing_turn_charge(self) -> int:
        """How many more MP-equivalents must be spent to earn a turn."""
        return max(0, self.turn_cost - self.turn_charge)

    def turn_left_auto(self) -> ShipState:
        """If needed, spend MP to finish charging, then turn left (one step)."""
        missing = self.missing_turn_charge()
        s = self
        if missing > 0:
            if s.mp < missing:
                raise ValueError(f"Insufficient MP to charge turn: mp={s.mp}, missing={missing}")
            s = s.spend_mp(missing)
        return s.turn_left()

    def turn_right_auto(self) -> ShipState:
        """If needed, spend MP to finish charging, then turn right (one step)."""
        missing = self.missing_turn_charge()
        s = self
        if missing > 0:
            if s.mp < missing:
                raise ValueError(f"Insufficient MP to charge turn: mp={s.mp}, missing={missing}")
            s = s.spend_mp(missing)
        return s.turn_right()
