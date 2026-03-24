# Tactical Combat Design

This document describes the intended turn structure and combat mechanics for the tactical
engine (`tactical/`). It reflects design decisions made as of March 2026 and supersedes
any conflicting notes in CLAUDE.md. Sections marked **[TBD]** are deferred to playtesting.

---

## Turn Structure

Each tactical turn has three phases, resolved in order. Both players submit orders for each
phase simultaneously; neither player sees the other's submission before committing.

| Phase | Name | What players submit |
|-------|------|---------------------|
| 1 | Large unit movement | Movement orders for all large units |
| 2 | Large unit shooting | Targeting decisions for all large units |
| 3 | Fighter movement & combat | Role assignments and movement orders for all fighters |

"Large units" are all non-fighter ships (frigates, destroyers, cruisers, etc.).

---

## Phase 1 — Large Unit Movement

Both players simultaneously submit movement orders for their large units. Orders are
resolved simultaneously — there is no first-mover advantage within this phase.

**Collision rule:** if two opposing large units would occupy the same hex at the end of
movement, higher initiative claims the hex and the lower-initiative unit stops in the last
valid hex along its path.

**Future extension:** there is a path-intersection simulation approach (similar to Phase 3)
that could allow large units to react to each other mid-movement. This is deferred; for now
movement is resolved by comparing final positions only.

---

## Phase 2 — Large Unit Shooting

Both players simultaneously submit targeting decisions for all their large units. All fire
resolves simultaneously against the positions established at the end of Phase 1.

**Simultaneity rule:** a ship that is destroyed by fire in this phase still fires back. Damage
is applied after all shots are resolved, not mid-volley.

**Point defense vs. fighters:**
- PD *may* fire on fighters that are directly engaging the carrying ship.
- PD *may* fire on unengaged enemy fighters within PD range.
- PD *may not* fire on fighters currently engaged in a dogfight (too intermixed and
  maneuvering too violently for area weapons to safely target).
- PD fires on incoming missiles as normal (this takes priority; **[TBD]** whether PD can
  split fire between missiles and fighters in the same volley).

---

## Phase 3 — Fighter Movement & Combat

Both players simultaneously submit orders for their fighters. All fighter movement and
combat is then resolved automatically by a step-by-step simulation. Neither player makes
further decisions during resolution; they observe the replay afterward.

### Fighter Roles

Each fighter squadron is assigned one role per turn:

| Role | Description |
|------|-------------|
| **Strike** | Follows a path toward a designated target — either a large unit or a specific enemy fighter squadron. |
| **CAP** (Combat Air Patrol) | Assigned to protect a specific friendly large unit. Moves to remain near that ward and uses remaining MP as an intercept zone around it. |
| **Interceptor** | Holds position or moves slowly. Uses reserved MP as an intercept radius to engage any enemy fighter that enters range. |

A Strike fighter targeting another fighter pursues it dynamically during the simulation,
updating its intercept path as the target moves (pursuit logic, not a fixed pre-planned path).

### Intercept Radius

The core mechanic of the fighter phase: **a fighter's intercept radius equals its remaining
unspent MP at any point during the simulation.**

- A stationary interceptor with total MP 6 begins the phase with intercept radius 6, plus
  a small base sensor range (1 hex by default; **[TBD]** as a per-fighter-type constant).
- As a fighter spends MP on movement, its intercept radius shrinks accordingly.
- If an enemy fighter comes within the interceptor's current radius at any point during the
  simulation, the interceptor spends MP equal to the distance to close and engage.
- After spending MP to close, the remaining radius is reduced by that distance. A single
  interceptor cannot engage unlimited targets per turn — it has a finite MP budget.

This means MP is a unified action budget: spent on movement, on closing to engage, or
held in reserve as intercept coverage. The tactical choice each turn is how to allocate it.

**CAP intercept radius** works identically: after a CAP fighter moves to remain near its
ward (spending some MP), its remaining MP becomes its intercept zone around that position.
A ward that moves far forces its CAP fighters to spend more MP following it, leaving a
smaller intercept zone.

### Time-Step Simulation

The fighter phase is resolved over **N discrete time steps** (N is a tunable constant,
defaulting to a value ≥ the maximum possible fighter MP so the fastest fighter moves at
most one hex per step).

**Movement accumulator (Bresenham-style):** each fighter accumulates movement credit each
step rather than moving fractional hexes:

```
accumulator += fighter.total_MP
if accumulator >= N:
    advance one hex along path
    accumulator -= N
```

This ensures:
- All fighters are in motion simultaneously throughout the full phase.
- A faster fighter covers more ground *per time step*, not more time steps — its advantage
  is speed, not extra turns.
- Each fighter moves exactly its total MP in hexes over the full phase.
- No fractional hex positions are needed.

**Per-step resolution order:**
1. Advance all fighters by one accumulator tick.
2. For each interceptor (including CAP fighters near their ward): check whether any enemy
   fighter is within its current intercept radius. If yes, trigger engagement.
3. Resolve all triggered engagements for this step (see Dogfight Resolution below).
4. Remove destroyed squadrons; mark furballed squadrons as inactive for remaining steps.
5. Victorious fighters continue with their remaining MP and orders.

### Intercept Priority

When an interceptor is simultaneously within range of multiple enemy fighters in the same
step, it engages the **closest target first**. If distances are equal, **[TBD]** (coin flip
or player-specified priority list as an optional override).

### Dogfight Resolution

When an interceptor engages a strike squadron:

1. **Dogfight occurs** at the hex where engagement was triggered.
2. **Strike destroys interceptors:** the strike squadron continues along its remaining path
   with its remaining MP. It may trigger further intercept zones it passes through.
3. **Strike does not destroy interceptors:** both squadrons enter a **furball** and are
   inactive for the remainder of this phase.

**Chain intercepts:** a strike fighter that destroys one interceptor and continues may
encounter further interceptors along its remaining path. Each is resolved in the order
encountered during the simulation. This creates a natural "clearing escort first" dynamic —
sending strike fighters to destroy interceptors ahead of your main strike wave.

### Furball Persistence

A furball persists into the following turn. At the start of that turn, before orders are
submitted, furballed squadrons are noted in the game state. Players have three options for
a furballed squadron:

| Option | Effect |
|--------|--------|
| **Continue fighting** | Automatic; no order needed. Combat continues this turn. |
| **Break off** | Fighter attempts to disengage. Costs MP (exact amount **[TBD]**) and carries a risk of taking damage while turning away. If successful, the squadron is free to act normally. |
| **Break off and re-assign** | As break off, but the freed squadron is immediately given new orders for this turn using its remaining MP after the break-off cost. |

---

## Ammunition

All shipboard ammunition is **fungible** — a single `Mg` (Magazine) pool feeds every consumer aboard the ship regardless of type. This covers:

- `R` (Standard Missile) launcher shots fired in combat.
- Fighter squadron rearming: each external ordnance mount reloaded while docked costs 1 Mg charge per shot (e.g. reloading a squadron with 2 external `R` mounts costs 2 charges from the carrier's Mg pool).

Standard Missile launchers (`R`) carry their own internal charges as a secondary buffer. The ammo system is tracked per-system via `System.charges`.

- Each `R` launcher starts with **10 internal charges**.
- A `Mg` (Magazine) system starts with **50 shared charges** and feeds all `R` launchers (and future consumers) on the same ship.
- **Draw order**: Mg charges are consumed before internal launcher charges. Within Mg, the leftmost active Mg is drained first. When drawing from internal launcher charges, exactly 1 shot is taken from each active launcher in order (not greedy drain from leftmost).
- The number of missiles fired in a volley is `min(active_launchers, total_ammo_available)`.
- Ammo consumption is applied to the attacker simultaneously with damage application (not mid-resolution).
- If a launcher is destroyed, its internal charges are lost (system becomes inactive; `ammo_count_for` only counts active systems).
- **[TBD]**: Implement fungible draw for fighter rearming — currently rearming is not yet implemented.

---

## Carriers

Carriers (`CV` hull type) support fighter launch and recovery via hangar bay (`Bh`) and launch bay (`Bl`) systems.

### Docking State

A squadron with `docked_at = carrier_id` is **docked**. Docked squadrons:
- Are excluded from all fighter combat, intercept checks, and hex-based logic.
- Do **not** lose endurance (fuel) each turn — they are refuelling aboard the carrier.
- Have a placeholder hex position that is ignored while docked.

### Launch

- Staged during `MOVE_SUBMISSION` via `stage_launch(side, carrier_id, squadron_id)`.
- Validated against active `Bl` count (one launch per active `Bl` per turn).
- Processed at the **start** of `_resolve_movement`, before ships move.
- The squadron appears at the carrier's pre-move hex.
- Emits `LaunchEvent`.

### Recovery

- Submitted as `RecoverOrder(carrier_id)` in `COMBAT_SMALL`.
- Processed at the **start** of `_resolve_combat_small`, before fighter combat.
- The squadron must be at the carrier's current hex.
- Requires an empty active `Bh` on the carrier.
- Emits `RecoveryEvent`.
- **[TBD]**: Recovery should also consume a `Bl` slot (currently only checks `Bh`).
- **[TBD]**: Refuel/rearm while docked — restore endurance each turn; restore external ordnance mounts by drawing from the carrier's fungible Mg pool (1 charge per shot reloaded).

---

## Design Notes & Future Extensions

**Collapsing Phases 1 and 3:** allowing large units to also submit "target and pursue"
orders (rather than fixed paths) would eventually allow phases 1 and 3 to merge into a
single simultaneous movement phase for all units. This is architecturally compatible with
the current design. Deferred.

**Fighter types:** the base sensor range constant and MP totals will vary by fighter type
once more hull types are defined. The intercept radius formula does not need to change.

**Simultaneous destruction:** if both sides in a dogfight are destroyed simultaneously,
**[TBD]** — likely both are removed and neither continues.

**Large unit targeting of fighters:** large unit weapons cannot target fighters (too small
and maneuverable). PD is the designated anti-fighter weapon for large units, subject to the
rules in Phase 2 above.

**Engine generations and hull performance:** Each hull type has a base `Spd(TrnCost)` value
using Gen-1 engines (Ia). Future engine generations (e.g. Ib/Ic) improve a hull's max speed
and turn cost by +1/+1 per generation, with the following exception: hulls whose base turn
cost ends in a `-` suffix (e.g. `5(2-)`, `4(4-)`) only gain the turn-cost increment every
*other* generation. For example, a DD (base `5(3)`) with Gen-2 engines becomes `6(3)`;
Gen-3 becomes `6(4)`. A BC (base `4(4-)`) with Gen-2 becomes `5(4)`; Gen-3 becomes `5(5)`.
This means the `-` suffix acts as a half-step delay on the turn-cost improvement track.
Implementation deferred until engine-generation tech tree is built.
