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

### Interfaces

- **`app.py`** — FastAPI application. Handles game creation, command dispatch, snapshots for rollback, and multiplayer turn enforcement (only the active player can mutate state).
- **`repl/repl.py`** — Interactive CLI for local play.
- **`db.py`** — SQLite persistence layer (games and snapshots tables).
- **`scenarios/simple_scenario.py`** — Default two-player game initialization.

### Data Flow

1. Players submit orders via web API (`app.py`) or REPL (`repl/repl.py`).
2. Orders are queued on `GameState` in `turn_engine.py`.
3. On turn submission, `turn_engine.py` processes movement, interception, and combat (delegating to `sim/combat/` or `tactical/`).
4. State is persisted via `persistence.py` → `db.py` (SQLite).

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
| I | Internal |
| R | Standard Missile launcher |
| D | Point Defense |

Parsing, rendering, and deterministic damage application are handled by `ShipSystems` in `tactical/ship_systems.py`.

### Weapon Rules

- **Laser (L)** — skips shields
- **Electron Beam** — skips armor + hull; half damage vs shields
- **Force Beam** — no skip rules
- **Standard Missile (R)** — range-based to-hit and damage tables; `-` means cannot fire at that range

### Missile & Point Defense

A volley = all missiles from one firing unit. Each intact `R` launcher contributes shots. PD (`D` systems) fires only at incoming hits, 3 shots per `D` per volley, to-hit target of 3. Each PD hit cancels one missile hit. Resolved via `resolve_missile_volley(...)` in `tactical/missile_volley.py`.

### Tactical Turn Structure

**Movement phase**: 3 sub-phases (default). Initiative determines order (low → high moves first). Each ship spends ~⅓ of its MP per sub-phase; turn charge persists across sub-phases.

**Movement rules**: Ships spend MP to move forward. Turning requires accumulating turn charge; once threshold is met the turn is free and charge resets. A ship may pass through an occupied hex but cannot end movement there.

**Combat phase**: Large unit combat — high initiative fires first, alternating activation, each unit fires once or passes. Small unit combat (fighters/gunships) is planned but not yet implemented.

## Developer Preferences

- **Small, incremental changes.** Prefer drop-in snippets over large refactors.
- **Deterministic behavior everywhere.** Tests use a seeded RNG; never break stable test ordering.
- **REPL-first iteration.** The tactical REPL (`python main.py`) is the primary development interface — use `scenario missiles`, `map`, `shoot A1 B1 R` etc. to validate behavior interactively.
- **Pure functions preferred.** Explicit state transitions over implicit side effects.
- **Do not rewrite working systems.** Especially anything in v1 (`sim/`, `app.py`).
