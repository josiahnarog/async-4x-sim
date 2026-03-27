# Campaign Layer Design

This document captures the core design principles for the strategic/campaign layer.
It covers the time model, UX philosophy, sensor and fog-of-war mechanics, and
the principles that govern how combat is made to happen at the right frequency
and scale.  It is a living document; sections marked **[TBD]** await playtesting.

---

## Design Inspirations

The campaign layer draws from two primary inspirations and deliberately combines
their strongest qualities.

**Starfire / Imperial Starfire (tabletop)**
Provides the core mechanical framework: warp-point navigation, multi-scale hex
coordinates (galaxy → system → tactical), ship design from discrete components,
and the feel of commanding a space navy where individual ships matter.

**Subterfuge (mobile, Kongregate 2015)**
Provides the UX philosophy for real-time async play.  Subterfuge's central
insight is that a continuous-time strategy game becomes tractable when the player
can *scrub* freely through time — rewinding to review what happened and
fast-forwarding to see projected futures.  This transforms what would otherwise
be an anxious, must-check-constantly experience into one that rewards deliberate
strategic thinking.

---

## The Time Model

### Continuous time, async turns

The game runs on a continuous clock (game-years, subdivided into game-days).
Players do not need to be online simultaneously.  Orders are submitted
asynchronously; the simulation advances continuously and players review state
whenever they log in.

Fleet transits, orbital movements, and battles all occur at specific computed
moments on this clock.  Nothing waits for player acknowledgement except a
player's *own* order submissions.

### The time scrubber

The primary navigation control for the campaign map is a **time scrubber** —
a slider that moves the displayed game state backwards and forwards in time.

Scrubbing backwards reveals history: fleet movements, battles resolved, planets
colonized.  Scrubbing forwards projects the future based on committed orders and
known physics.

What the future projection shows:
- Orbital positions of all stars, planets, moons, and asteroid belts
- Committed fleet courses and arrival times
- Warp point traversal schedules
- Projected intercept points where courses will intersect

What the future projection does *not* show:
- Enemy fleet positions beyond current sensor range
- The effect of orders not yet submitted
- Outcomes of battles not yet resolved

This distinction — certain physics vs. uncertain intent — is what gives the
scrubber its strategic depth.  A player can see exactly where a planet will be
in 40 game-days; they cannot see where an enemy fleet will be unless they have
sensors on it.

### Ghost paths and intercept projection

When a fleet is selected, the scrubber displays its **ghost path**: the full
projected course as a translucent trail extending into the future, terminating
at the ordered destination.

When an intercept order is issued (fleet ordered toward a moving target), the
system computes and displays:
- The fleet's projected course
- The target's projected course (if known via sensors)
- The computed intercept point — where the two paths meet

If the target changes course, the intercept recomputes in real time as the
player scrubs.  This makes the geometry of interception tangible and satisfying:
you can visually confirm you will catch a fleeing enemy, or that you will arrive
at a planet before the enemy does.

The same projection applies to weapon ranges: at the computed intercept point,
the UI can display whether the attacker will be within weapons range, and from
which arc.  This creates the conditions for *pre-battle strategic play* —
maneuvering for arc advantage before a shot is fired.

### Intercept calculation model

Intercept geometry works differently depending on target type.

**Orbital bodies (planets, moons, asteroid hexes):**
The target's position at every future time T is fully deterministic — it follows
a known Keplerian path.  Given:
- Interceptor position at T=0 and its speed (hex/day)
- Target position function `pos(T)`

Find the smallest T = Ti such that `hex_dist(interceptor_pos(Ti), target_pos(Ti)) == 0`
(or within weapons range for a strike mission).  The ghost paths displayed are:
- Target: `pos(0)` → `pos(Ti)` along its orbital arc
- Interceptor: straight-line (or BFS shortest path) from `pos(0)` to `pos(Ti)`

This is deterministic and stable unless the interceptor itself changes (damage,
speed reduction, new orders).

**Enemy fleets:**
The target's future position is projected from its *current known velocity and
heading*, treated as a straight-line extrapolation until new information arrives.
The same intercept calculation is performed on this projected path.

Crucially, the intercept must be **recalculated continuously** as new information
arrives:
- If the target changes course (detected via sensors), the projection updates
  and a new Ti is computed
- If the target accelerates or decelerates, the projection updates
- If the interceptor loses speed (damage, fuel state), its Ti increases and
  may exceed the mission window

This means intercept orders carry an implicit **"recompute on change" contract**:
the intercepting fleet continuously re-solves for Ti as the game clock advances,
automatically adjusting course toward the updated intercept point.  The player
sees this happening on the scrubber as the ghost path bends to track the
updated projection.

**When intercept becomes impossible:**
If the target accelerates beyond the interceptor's reach, or changes course
such that no valid Ti exists within fuel/endurance limits, the intercept order
is flagged as failed and the fleet holds position or falls back to a contingency
order.  The player sees this as the ghost paths diverging rather than meeting.

**Design intent:**
The goal is not to solve the full pursuit problem perfectly — it is to give the
player a clear, honest projection of what will happen given current information,
updated fluidly as that information changes.  The intercept calculation is a
*commitment device*: issuing an intercept order says "chase this target; update
course as needed."  The player uses the scrubber to evaluate whether that
commitment is wise before issuing it.

---

## Space as a Living Environment

### Orbital mechanics

Every stellar body (non-primary stars, planets, moons, asteroid belt hexes)
orbits according to simplified Keplerian mechanics.  Orbital periods are
derived from the body's distance from its parent and the parent's mass.

This means:
- Planets are at different positions on every visit
- Travel times to a planet depend on when you leave, not just distance
- Asteroid belts rotate as a ring; individual belt hexes move along it
- Binary stars create gravitational complexity in their systems

Watching orbital motion on the time scrubber is intended to be visually
satisfying — the sense that the galaxy is alive and moving independently of
player action is a core aesthetic goal.

### Warp points are fixed

Warp points are fixed relative to their system's stellar primary.  They do not
orbit; they are gravitational or spatial anomalies anchored to the star.  This
means:
- Transit times through warp points are predictable and stable
- Warp points are natural choke points and strategic objectives
- Interstellar travel time calculation is simple: distance in sH between the
  warp point and your fleet, at strategic movement speed

This is a deliberate simplification.  The fixed nature of warp points is what
makes them valuable as strategic objectives and makes interstellar travel
tractable to plan.

---

## Sensor and Fog of War

### The core principle

Information is a weapon.  Sensor superiority should translate directly into
tactical and strategic advantage: you can choose the time, place, and geometry
of battle; your opponent cannot.

### Sensor range and detection

Each ship and installation has a sensor rating.  Within sensor range, enemy
units are visible: their position, heading, speed, and (at close range) ship
class.  Beyond sensor range, the enemy is invisible.

Sensor range is not a hard cutoff — it degrades probabilistically with distance
and is affected by:
- Cloak / stealth technology
- Nebula or interference hexes
- The mass and emissions signature of the target (larger ships are harder to hide)
- Whether the target is active (maneuvering, firing) vs. cold-running

### What you know vs. what you infer

The scrubber distinguishes three states for enemy units:

1. **Confirmed** (within sensor range now): shown in full colour with ghost path
2. **Last known** (was visible, now out of range): shown as a ghost at the last
   known position, with a projected cone of possible positions expanding forward
   in time
3. **Unknown** (never detected): not shown

The expanding uncertainty cone for last-known contacts is a key gameplay
element.  A fleet that slips out of sensor range could have changed course; the
cone shows all plausible positions.  Committing to an intercept based on a
last-known contact is a calculated risk.

### Counter-sensors and cloak

Technology investment in cloak reduces your emissions signature, effectively
shrinking the range at which enemies can detect you.  Counter-sensor technology
increases your ability to detect cloaked ships.

A cloaked fleet approaching a planet creates genuine tension: defenders must
decide whether to sortie to investigate an uncertain contact or hold at the
warp point.  Attackers must decide whether to maintain cloak (slower, limits
options) or go active to maximize speed at the cost of detection.

---

## Making Combat Happen

### The geography of inevitable conflict

Space is large and fleets are small.  Left entirely to physics, fleets would
rarely meet.  The design deliberately creates **geographic funnels** where
conflict is structurally likely:

**Warp points**: the only way between systems.  Any fleet transiting must pass
through a fixed, known location.  Defending a warp point is always an option;
attackers must commit to a transit that reveals their presence.

**Inhabited planets**: the economic objectives of the game.  A fleet that
threatens a planet forces the defender to respond.  The planet's orbital
position at the time of attack must be predicted by the attacker (using the
scrubber), and matched by the defender's response trajectory.

**Resupply constraints**: ships have finite endurance and magazine capacity.
Deep-space ambushes are possible but the attacker must eventually return to a
base, creating a window for the defender to regroup or pursue.

### Speed differentials create tactical options

Not all ships move at the same strategic speed.  Lighter, faster fleets can
choose the time and place of engagement; heavier fleets can absorb more damage
but cannot easily disengage.  This creates meaningful decisions about fleet
composition: a fast raiding force can strike and withdraw before a slow battle
fleet can respond, but cannot hold a warp point against a determined defense.

### Combat is intense when it happens

Because the geometry of the approach is visible on the scrubber, both players
arrive at a battle having thought through the engagement.  The tactical layer
(hex combat, firing arcs, fighter operations) then resolves the conflict with
sufficient granularity to reward preparation, ship design, and in-the-moment
tactical skill.

The goal is that battles feel like the *conclusion* of a strategic contest —
the player who maneuvered better arrives with an arc advantage, a fresher
magazine, or an intercepting fighter screen already in position.  Tactical
skill matters, but it is the reward for good strategy, not a substitute for it.

---

## Scale Hierarchy

```
Galaxy Map (warp point graph)
    |
    |  warp point transit
    v
System Map  (sH hex grid, 1 hex = 1 system hex ≈ 1.443 AU)
    |
    |  zoom / drill-down
    v
Tactical Map  (TH hex grid, 1 TH = 1/2880 sH ≈ 74 940 km)
```

Each level is a real coordinate space, not a visual abstraction.  Objects have
authoritative coordinates at both the sH and TH scale.  A planet at sH (q, r)
is always at TH (0, 0) within its own strategic hex; its moons are arrayed
around it in TH space.

This explicit hierarchy is what makes the intercept geometry tractable: the
same orbital mechanics engine that drives the scrubber animation also feeds
the course-planning and intercept-computation tools.

---

## Design Principles Summary

| Principle | Implementation |
|-----------|----------------|
| Space feels alive | Orbital mechanics; bodies move independently of player action |
| Information is a weapon | Sensor range, cloak, uncertainty cones |
| Scrubbing is the primary UX | Continuous time model; all futures are projectable |
| Combat is inevitable at chokepoints | Warp points and planets as mandatory objectives |
| Good strategy rewards tactical play | Geometry of approach determines starting conditions |
| Intercept is satisfying | Ghost paths, intercept point display, arc projection |
| Async is first-class | No simultaneous play required; scrubber covers absence |
