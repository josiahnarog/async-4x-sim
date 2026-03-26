from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from sim.hexgrid import Hex
from tactical.fighter_class import FighterClass
from tactical.weapons import WEAPONS, WeaponType


SquadronID = str


@dataclass(frozen=True, slots=True)
class FighterLoadout:
    """Per-fighter weapon configuration for a squadron.

    All fighters in the squadron carry identical loadouts; total output
    scales linearly with squadron strength.

    fighter_class — defines the base stats (mvr, mp) for this generation of
                fighter.  Ordnance penalties are computed against these base
                values and disappear as external shots are expended.
    internal  — unlimited-ammo weapons (G, L, E, …); used in both dogfights
                and attack runs.
    external  — limited-ammo weapons (R, …); used only in attack runs vs ships.
                Cannot be used in dogfights (R.can_target_fighters is False).
    external_shots_remaining — shots per fighter remaining.  Decrements by 1
                each time the squadron fires an external salvo.  Penalties
                disappear when this reaches 0.

    Derived movement/maneuverability penalties:
        effective_mp  = base_mp - max(ordnance_mp_penalty)   while any external shots remain
        effective_mvr = base_mvr - sum(ordnance_mvr_penalty_per_shot for each remaining shot)

    Penalties are read from WeaponSpec.ordnance_mp_penalty and
    ordnance_mvr_penalty_per_shot so future weapon types can carry different
    values without touching this class.
    """

    fighter_class: FighterClass             # defines base_mvr and base_mp
    internal: tuple[WeaponType, ...]        # unlimited — e.g. (G, G, G)
    external: tuple[WeaponType, ...] = ()   # limited   — e.g. (R,)
    external_shots_remaining: int = 0       # shots per fighter; 0 if no external weapons

    # ------------------------------------------------------------------
    # Base stats (delegated to fighter_class)
    # ------------------------------------------------------------------

    @property
    def base_mvr(self) -> int:
        return self.fighter_class.base_mvr

    @property
    def base_mp(self) -> int:
        return self.fighter_class.base_mp

    # ------------------------------------------------------------------
    # Derived stats
    # ------------------------------------------------------------------

    @property
    def effective_mvr(self) -> int:
        """MVR after ordnance penalty.

        Each remaining external shot contributes its weapon's
        ordnance_mvr_penalty_per_shot.  Uses external[:external_shots_remaining]
        as a proxy for which slots still carry a round (shots expended last-first).
        """
        remaining_weapons = self.external[: self.external_shots_remaining]
        penalty = sum(
            WEAPONS[wt].ordnance_mvr_penalty_per_shot
            for wt in remaining_weapons
            if wt in WEAPONS
        )
        return max(0, self.base_mvr - penalty)

    @property
    def effective_mp(self) -> int:
        """MP after ordnance penalty.

        While any external shots remain, applies the highest
        ordnance_mp_penalty found across the external weapon types.
        """
        if self.external_shots_remaining <= 0:
            return self.base_mp
        penalty = max(
            (WEAPONS[wt].ordnance_mp_penalty for wt in self.external if wt in WEAPONS),
            default=0,
        )
        return max(0, self.base_mp - penalty)

    # ------------------------------------------------------------------
    # Mutations (pure)
    # ------------------------------------------------------------------

    def expend_external_shot(self) -> FighterLoadout:
        """Return updated loadout after firing one external salvo."""
        if self.external_shots_remaining <= 0:
            raise ValueError("No external shots remaining")
        return dataclasses.replace(
            self, external_shots_remaining=self.external_shots_remaining - 1
        )


@dataclass(frozen=True, slots=True)
class SquadronState:
    """Tactical fighter squadron state.

    Squadrons are facing-less: they can move in any direction without a
    turning cost, reflecting the agility of individual fighters.

    strength tracks surviving fighters.  Offensive output scales linearly
    — a strength-3 squadron with loadout (G, G) fires 6 gun shots total
    (3 fighters × 2 guns).

    Engagement is positional: a squadron is in a dogfight whenever its hex
    contains at least one enemy squadron.  No explicit engagement flag is
    stored — it is derived from BattleState at resolution time.
    """

    squadron_id: SquadronID
    owner_id:    str
    pos:         Hex

    strength:     int  # current fighters alive (0 = destroyed)
    max_strength: int  # 5 for a standard squadron

    loadout:      FighterLoadout

    endurance:     int  # turns of operation remaining
    max_endurance: int

    docked_at: str | None = None  # carrier ship_id when docked, None when deployed

    # ------------------------------------------------------------------
    # Derived stats (convenience wrappers onto loadout)
    # ------------------------------------------------------------------

    @property
    def effective_mvr(self) -> int:
        return self.loadout.effective_mvr

    @property
    def effective_mp(self) -> int:
        return self.loadout.effective_mp

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    @property
    def is_deployed(self) -> bool:
        """False when the squadron is docked aboard a carrier."""
        return self.docked_at is None

    def is_destroyed(self) -> bool:
        return self.strength <= 0

    # ------------------------------------------------------------------
    # Mutations (pure)
    # ------------------------------------------------------------------

    def take_casualties(self, n: int) -> SquadronState:
        """Remove n fighters (PD kills or dogfight losses)."""
        return dataclasses.replace(self, strength=max(0, self.strength - n))

    def expend_external_shot(self) -> SquadronState:
        """Consume one external salvo (called after an attack run fires missiles)."""
        return dataclasses.replace(self, loadout=self.loadout.expend_external_shot())

    def decrement_endurance(self) -> SquadronState:
        """Called at end of each turn the squadron is deployed."""
        return dataclasses.replace(self, endurance=max(0, self.endurance - 1))

    def move_to(self, dest: Hex) -> SquadronState:
        """Return squadron at new position (facing-less move)."""
        return dataclasses.replace(self, pos=dest)

    def dock(self, carrier_id: str) -> SquadronState:
        """Return squadron in docked state aboard carrier_id."""
        return dataclasses.replace(self, docked_at=carrier_id)

    def undock(self, pos: Hex) -> SquadronState:
        """Return squadron deployed at pos."""
        return dataclasses.replace(self, docked_at=None, pos=pos)
