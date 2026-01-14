from __future__ import annotations

from dataclasses import dataclass

from tactical.battle_state import BattleState, ShipID


@dataclass(frozen=True, slots=True)
class ActivationState:
    """Tracks tactical activation order and enforces who may act (MVP).

    Determinism:
      - The activation order for a round is a concrete list of ShipIDs.
      - By default it is derived from BattleState.ship_ids_sorted().

    This is intentionally minimal; later we can:
      - incorporate initiative stats
      - handle destroyed/retreated ships mid-round
      - integrate async/AI control
    """

    order: tuple[ShipID, ...]
    index: int = 0
    round_no: int = 1

    @staticmethod
    def from_battle(battle: BattleState) -> ActivationState:
        return ActivationState(order=tuple(battle.ship_ids_sorted()), index=0, round_no=1)

    def active_ship_id(self) -> ShipID:
        if not self.order:
            raise ValueError("No ships in activation order")
        if self.index < 0 or self.index >= len(self.order):
            raise ValueError(f"Activation index out of range: {self.index}")
        return self.order[self.index]

    def is_active(self, ship_id: ShipID) -> bool:
        return ship_id == self.active_ship_id()

    def advance(self) -> ActivationState:
        """Advance to the next ship. If we pass the end, start a new round."""
        if not self.order:
            raise ValueError("No ships in activation order")

        next_index = self.index + 1
        if next_index < len(self.order):
            return ActivationState(order=self.order, index=next_index, round_no=self.round_no)

        # New round: reset to first ship.
        return ActivationState(order=self.order, index=0, round_no=self.round_no + 1)

    def require_active(self, ship_id: ShipID) -> None:
        if not self.is_active(ship_id):
            raise PermissionError(f"Ship {ship_id!r} is not active (active={self.active_ship_id()!r})")


@dataclass(frozen=True, slots=True)
class TacticalTurn:
    """Combines BattleState + ActivationState into a single tactical sub-game state."""

    battle: BattleState
    activation: ActivationState

    @staticmethod
    def start(battle: BattleState) -> TacticalTurn:
        return TacticalTurn(battle=battle, activation=ActivationState.from_battle(battle))

    def active_ship_id(self) -> ShipID:
        return self.activation.active_ship_id()

    def move_active_ship_forward(self, ship_id: ShipID, steps: int = 1) -> TacticalTurn:
        """Enforce activation, then apply a movement mutation."""
        self.activation.require_active(ship_id)
        new_battle = self.battle.move_ship_forward(ship_id, steps=steps)
        return TacticalTurn(battle=new_battle, activation=self.activation)

    def end_activation(self, ship_id: ShipID) -> TacticalTurn:
        """End the current ship's activation (advance to next)."""
        self.activation.require_active(ship_id)
        return TacticalTurn(battle=self.battle, activation=self.activation.advance())
