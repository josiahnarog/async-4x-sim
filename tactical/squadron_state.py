from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from sim.hexgrid import Hex
from tactical.weapons import WeaponType


SquadronID = str


@dataclass(frozen=True, slots=True)
class FighterLoadout:
    """Per-fighter weapon configuration for a squadron.

    All fighters in the squadron carry identical loadouts; total output
    scales linearly with squadron strength.

    internal  — unlimited-ammo weapons (G, L, E, …); used in both dogfights
                and attack runs.
    external  — limited-ammo weapons (R, …); used only in attack runs vs ships.
                Cannot be used in dogfights (R.can_target_fighters is False).
    external_shots_remaining — shots per fighter remaining.  Decrements by 1
                each time the squadron fires an external salvo.  Penalties
                disappear when this reaches 0.

    Derived movement/maneuverability penalties (per design):
        effective_mp  = base_mp - 2            while any external shots remain
        effective_mvr = base_mvr - external_shots_remaining
    """

    base_mvr: int                           # maneuverability, from fighter generation
    base_mp:  int                           # movement points before ordnance penalty
    internal: tuple[WeaponType, ...]        # unlimited — e.g. (G, G, G)
    external: tuple[WeaponType, ...] = ()   # limited   — e.g. (R,)
    external_shots_remaining: int = 0       # shots per fighter; 0 if no external weapons

    # ------------------------------------------------------------------
    # Derived stats
    # ------------------------------------------------------------------

    @property
    def effective_mvr(self) -> int:
        """MVR after ordnance penalty (-1 per external shot remaining)."""
        return max(0, self.base_mvr - self.external_shots_remaining)

    @property
    def effective_mp(self) -> int:
        """MP after ordnance penalty (-2 flat while any external shots remain)."""
        return max(0, self.base_mp - (2 if self.external_shots_remaining > 0 else 0))

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
