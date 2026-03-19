# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
python -m pip install -r requirements.txt

# Run development server (web UI at http://127.0.0.1:8000/)
python -m uvicorn app:app --reload

# Run interactive REPL
python main.py

# Run all tests
pytest

# Run a single test file
pytest tests/test_combat.py

# Run a specific test
pytest tests/test_combat.py::test_function_name
```

## Project Phases

This repo contains two distinct engines:

- **Strategic Engine (v1)** — `sim/`, `app.py`, `db.py`. **Complete and stable.** Turn-based async 4X with abstract unit stacks, auto-resolved combat, SQLite persistence, and a minimal web UI. Do not extend or refactor this unless explicitly asked.
- **Tactical Engine (v2)** — `tactical/`. **Active development.** Ship-level tactical combat on a hex grid. This is the current focus.

## Architecture

The codebase has two primary combat layers — strategic and tactical — built on top of a hex-grid simulation core.

### Core Simulation (`sim/`)

- **`turn_engine.py`** — Central `GameState` class. Owns players, unit groups, colonies, fog of war, and turn/round progression. The primary entry point for any game-state mutation.
- **`hexgrid.py`** — Hex grid with axial coordinates, distance, and neighbor utilities.
- **`units.py`** / **`unit_types.py`** — `UnitGroup` model and predefined unit type constants (Scout, Battleship, Raider, etc.).
- **`orders.py`** — Frozen dataclasses for `MoveOrder`, `ColonizeOrder`, `MineOrder`.
- **`persistence.py`** — Full JSON serialization/deserialization of `GameState`.
- **`movement.py`** / **`pathfinding.py`** — Movement mechanics and A* pathfinding on the hex grid.
- **`map.py`** / **`map_content.py`** — Map structure and hex content (planets, minerals, homeworlds).
- **`render_ascii.py`** — Fog-aware ASCII map rendering.

### Strategic Combat (`sim/combat/`)

Handles fleet-vs-fleet combat at the game-state level, triggered during turn resolution:

- **`resolver.py`** — Collects battles and applies damage.
- **`targeting.py`** — Targeting policies (focus-fire).
- **`utils.py`** — Initiative ranking, volley sorting, damage application (hits → hull destruction).

### Tactical Encounters (`tactical/`)

A separate, detailed ship-level combat system with its own state machine:

- **`encounter.py`** — State machine for multi-phase encounters (movement, large/small combat phases).
- **`battle_state.py`** — Ship and fleet state during a tactical encounter.
- **`to_hit.py`** — Hit probability calculations (shared logic used across systems).
- **`weapons.py`** / **`missile_volley.py`** — Weapon fire and missile volley mechanics with point defense.
- **`ship_state.py`** / **`ship_systems.py`** — Per-ship damage tracking and systems.
- **`arcs.py`** — Firing arc geometry: `relative_bearing`, `arc_of`, blind-spot constants.
- **`hull_types.py`** — `HullType` dataclass (FG/DD/CA) with EPR, engines-per-room, max speed.
- **`combat.py`** — `resolve_large_fire` and `resolve_fire_all`; arc enforcement lives here.
- **`web.py`** — FastAPI router for the tactical web UI (`/tactical/`). Single-session global state (placeholder for future per-game persistence).

### Interfaces

- **`app.py`** — FastAPI application. Mounts the strategic game UI and the tactical router (`/tactical/`).
- **`main.py`** — Entry point; routes to `tactical/repl.py`.
- **`tactical/repl.py`** — Interactive CLI for tactical play. Primary development interface.
- **`db.py`** — SQLite persistence layer (games and snapshots tables).
- **`scenarios/simple_scenario.py`** — Default two-player strategic game initialization.
- **`templates/tactical.html`** — Tactical web UI: canvas hex map (flat-top, radius 8) + command input.

### Data Flow

1. Players submit orders via web API (`app.py`) or tactical REPL (`tactical/repl.py`).
2. Strategic orders are queued on `GameState` in `turn_engine.py`; tactical commands mutate `Encounter` state directly.
3. On turn submission, `turn_engine.py` processes movement, interception, and combat (delegating to `sim/combat/` or `tactical/`).
4. Strategic state is persisted via `persistence.py` → `db.py` (SQLite). Tactical state is currently in-memory only.

## Key Conventions

- **Damage model**: Damage is tracked as hull hits; partial damage accumulates until a ship is destroyed.
- **Fog of war**: All rendering and state exposure is filtered through per-player fog awareness.
- **Multiplayer enforcement**: `app.py` blocks mutations from non-active players — only the player whose turn it is may issue orders.
- **Dataclasses**: Orders and most value objects use frozen `@dataclass` for immutability.

## Tactical Engine — System Details

### To-Hit Rule (Critical Invariant)

**Never violate this rule anywhere in the codebase:**

> Hit if: `roll ≤ target` — higher target = easier to hit

Uses a d10 system. Example: target 3 → 30% hit chance (rolls 1–3). All hit resolution is centralized through `roll_hits_target(...)` in `tactical/to_hit.py`.

### Ship Systems

Ships are composed of ordered systems stored as structured objects (not raw strings). Displayed in compact form, e.g. `SSSAAALL(III)(III)`. Systems are ordered left-to-right; **damage order matters**. Key system codes:

| Code | System |
|------|--------|
| S | Shield |
| A | Armor |
| L | Laser |
| E | Electron Beam |
| F | Force Beam |
| R | Standard Missile launcher |
| D | Point Defense |
| I | Internal (engine room) |

Parsing, rendering, and deterministic damage application are handled by `ShipSystems` in `tactical/ship_systems.py`.

### Weapon Rules

- **Laser (L)** — skips shields
- **Electron Beam** — skips armor + hull; half damage vs shields
- **Force Beam** — no skip rules
- **Standard Missile (R)** — range-based to-hit and damage tables; `-` means cannot fire at that range

### Missile & Point Defense

A volley = all missiles from one firing unit. Each intact `R` launcher contributes shots. PD (`D` systems) fires only at incoming hits, 3 shots per `D` per volley, to-hit target of 3. Each PD hit cancels one missile hit. Resolved via `resolve_missile_volley(...)` in `tactical/missile_volley.py`.

### Firing Arcs

Centralized in `tactical/arcs.py`. Bearings are relative to the observer's facing: 0 = dead ahead, 1 = 60° right, …, 3 = dead astern, …, 5 = 60° left.

**Blind spot**: relative bearing 3 only (dead astern — a 60° cone). A unit cannot fire at a target in its own blind spot. Enforced in `resolve_large_fire` (covers all call paths including the REPL `shoot` command).

**Rear-arc bonus**: if the attacker is at bearing 3 from the *target's* facing, `target_delta += 2` (20% easier on d10).

**PD suppression**: PD is fully disabled against missiles fired from the target's blind spot (attacker at bearing 3 from target).

**`WeaponArc`** (in `weapons.py`): `ALL` (default — any non-blind-spot bearing) or `FORWARD` (bearing 0 only). Per-weapon arc violations skip that weapon in `resolve_fire_all`; `resolve_large_fire` raises `ValueError`.

### Hull Types

Defined in `tactical/hull_types.py`. `HullType` fields: `designation`, `name`, `engine_power_ratio` (EPR, as `Fraction`), `engines_per_room`, `max_speed`.

**EPR semantics**: engines required *per MP* — `MP = active_engine_count / EPR`. FG=2/3, DD=1, CA=2.

**Engine room rule**: engines in a parenthesised group (e.g. `(III)`) contribute 0 MP if any system in the group is destroyed. Implemented in `ShipSystems._active_engine_count()`.

### Tactical Turn Structure (Simultaneous-Submission Model)

Three phases per turn (see `docs/tactical_combat_design.md` for the full spec):

| Phase | `Encounter` state | How it works |
|-------|-------------------|--------------|
| **MOVE_SUBMISSION** | `phase == Phase.MOVE_SUBMISSION` | Each side calls `stage_move(side, ship, dest, facing)` then `commit_movement(side)`. When all sides have committed, `_resolve_movement()` fires automatically. |
| **COMBAT_SUBMISSION** | `phase == Phase.COMBAT_SUBMISSION` | Each side calls `stage_fire(side, ship, target)` or `pass_fire(side, ship)`, then `commit_fire(side, rng)`. When all sides have committed, `_resolve_fire(rng)` fires automatically. |
| **COMBAT_SMALL** | `phase == Phase.COMBAT_SMALL` | Fighter combat — not yet implemented. |

**Collision resolution**: when two ships submit moves to the same hex, higher initiative (from `Initiative.rolls`) wins; lower-initiative ship's move is cancelled (it stays in place).

**Simultaneity rule**: all fire is resolved against the pre-combat `BattleState` snapshot; damage is accumulated per target and applied in one pass after all shots. A ship destroyed mid-volley still fires back.

**Movement validation**: destination distance must be ≤ ship's MP capacity at encounter start (`_mp_capacity`). No turn-cost enforcement for MVP — ships may freely choose any facing at their destination.

**`turn_orders.py`**: `ShipMoveOrder(dest, dest_facing)` and `ShipFireOrder(target_id)` — the order dataclasses staged during submission phases.

## Developer Preferences

- **Small, incremental changes.** Prefer drop-in snippets over large refactors.
- **Deterministic behavior everywhere.** Tests use a seeded RNG; never break stable test ordering.
- **REPL-first iteration.** The tactical REPL (`python main.py`) is the primary development interface — use `scenario missiles`, `map`, `shoot A1 B1 R`, `fireall A1 B1` etc. to validate behavior interactively.
- **Pure functions preferred.** Explicit state transitions over implicit side effects.
- **Do not rewrite working systems.** Especially anything in v1 (`sim/`, `app.py`).

## Design Documents

- **`docs/tactical_combat_design.md`** — Full turn structure and fighter mechanics design.
  Read this before implementing anything in `tactical/` related to phases, fighters, or
  the movement simulation. Supersedes any conflicting notes in this file.

## Known Issues / Next Work

- **Damage does not reduce movement points.** Systems (including engine rooms) are marked destroyed by damage, but `ShipState.mp` is not recalculated after taking hits. Movement capacity should be recomputed from `ShipSystems` after each damage application.
- **COMBAT_SMALL not implemented.** Fighter mechanics are designed in `docs/tactical_combat_design.md` but not yet coded. For now, `_resolve_fire` automatically calls `next_turn()` to skip `COMBAT_SMALL` and return to `MOVE_SUBMISSION` for the next turn.
- **`next_turn()` recomputes MP from live systems**, so engine damage does reduce movement on subsequent turns. The remaining gap: `ShipState.mp` still reflects the previous turn's capacity mid-turn (between damage application and the next `next_turn()` call).
