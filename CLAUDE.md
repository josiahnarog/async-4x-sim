# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
python -m pip install -r requirements.txt

# Run development server (tactical UI at http://127.0.0.1:8001/tactical/)
python main.py

# Run all tests
pytest

# Run a single test file
pytest tests/test_combat.py

# Run a specific test
pytest tests/test_combat.py::test_function_name
```

## Project Status

The repository contains two engines. **Only the tactical engine is actively developed.**

- **Strategic Engine (v1)** — `sim/`, `app.py`, `db.py`. Likely to be partially or fully deprecated. Do not extend or refactor unless explicitly asked.
- **Tactical Engine (v2)** — `tactical/`. **Active development.** Ship-level tactical combat on a hex grid.

## Development Roadmap

1. **Tight combat loop** *(complete)* — Win/loss detection, endurance/fuel expiry, transit simultaneity, magazine ammo, carrier launch/recovery, turn-cost enforcement, fighter class/loadout system all done.
2. **Combat features** *(in progress)* — Fog of war, sensor suites, carrier Bl enforcement done. **Next: carrier refuel/rearm** (landed squadrons restore endurance/ordnance). Then: AI opponents, expanded scenarios for playtesting.
3. **Persistence and multiplayer** *(largely complete)* — Per-game SQLite persistence, multi-game lobby, display ID alignment done. Remaining: async multiplayer turn submission.
4. **Ship design interface** — Rules-enforced ship construction with systems validation, cost calculation, and construction-point budgets.
5. **Strategic campaign** — System and interstellar maps, random map generation, economy, colonization, construction queues, technology trees.

## Architecture

### Tactical Engine (`tactical/`) — primary codebase

- **`encounter.py`** — State machine: `MOVE_SUBMISSION → COMBAT_SUBMISSION → COMBAT_SMALL → next_turn()`. Immutable frozen dataclass; all mutations return new instances. Also holds `_launch_orders` for carrier launch staging.
- **`battle_state.py`** — Ships and squadrons during an encounter. `with_ship()`, `with_squadron()`, `without_squadron()`.
- **`fighter_combat.py`** — COMBAT_SMALL resolver: squadron movement, intercept engagement, dogfights, attack runs. Skips docked squadrons.
- **`fighter_class.py`** — `FighterClass` dataclass (`designation`, `name`, `base_mvr`, `base_mp`); named instance `F1` (Gen 1 Fighter, mvr=4, mp=10, 1 internal mount, 2 external mounts); `FIGHTER_CLASSES` dict keyed by designation.
- **`squadron_state.py`** — `SquadronState` and `FighterLoadout`; `FighterLoadout.fighter_class` references a `FighterClass` for base stats; ordnance penalties computed dynamically; `docked_at` field for carrier docking; `is_deployed` property; `dock()`/`undock()` mutations.
- **`turn_orders.py`** — `ShipMoveOrder`, `ShipFireOrder`, `InterceptOrder`, `StrikeOrder`, `BreakOffOrder`, `LaunchOrder`, `RecoverOrder`.
- **`combat.py`** — `resolve_large_fire` and `resolve_fire_all`; arc enforcement; `FireEvent` includes `ammo_consumed`.
- **`weapons.py`** / **`missile_volley.py`** — Weapon specs (`requires_ammo` flag) and missile/PD resolution.
- **`ship_state.py`** / **`ship_systems.py`** — Per-ship damage and systems. `System` has `charges` (ammo) and `occupant` (squadron ID for Bh). `render_compact()` annotates with `[...]`. `consume_ammo_for()` / `ammo_count_for()`. `dock_squadron()` / `undock_squadron()`.
- **`events.py`** — `FireEvent`, `UnitDestroyedEvent`, `FuelWarningEvent`, `BattleEndEvent`, `LaunchEvent`, `RecoveryEvent`.
- **`arcs.py`** — Firing arc geometry: `relative_bearing`, blind-spot constants, rear-arc bonus.
- **`hull_types.py`** — `HullType` (FG/DD/CA/CV): EPR, engines-per-room, max speed, turn_cost.
- **`to_hit.py`** — Centralised hit resolution. **Invariant: hit if `roll ≤ target`.**
- **`scenarios.py`** — `default_scenario()`: two frigates (A1/B1) + two CVs (A2/B2) + four deployed squadrons.
- **`web.py`** — FastAPI router (`/tactical/`). Single-session global state (pending persistence work).
- **`repl.py`** — Interactive CLI; primary development interface.

### Supporting files

- **`app.py`** — Mounts the tactical router; root redirects to `/tactical/`.
- **`main.py`** — Launches uvicorn on port 8001.
- **`templates/tactical.html`** — Canvas hex map (flat-top, pan/zoom) + command input + log. Canvas 640×640; drag to pan, scroll to zoom.
- **`sim/hexgrid.py`** — Hex grid with axial coordinates; used by both engines.

### Strategic Engine (`sim/`, deprecated-pending)

Do not modify. If strategic concepts are needed for the campaign layer, design fresh rather than extending the v1 code.

## Tactical Engine — Critical Rules

### To-Hit Invariant

> **Hit if: `roll ≤ target`** — higher target = easier to hit.

d10 system. All resolution goes through `roll_hits_target(...)` in `tactical/to_hit.py`. Never bypass this.

### Ship Systems

Ordered left-to-right; **damage order matters**. Compact notation: `SSSAAALL(III)(III)R[10]Mg[R:50]`.

`render_compact()` annotates systems that carry state with `[...]`:
- Ammo-bearing systems (R, Mg): show remaining charges — e.g. `R[9]`, `Mg[R:47]`
- Hangar bays (Bh): show occupant or `-` — e.g. `Bh[AF1]`, `Bh[-]`

| Code | System | Notes |
|------|--------|-------|
| S | Shield | |
| A | Armor | |
| L | Laser | skips shields |
| E | Electron Beam | skips armor+hull; half dmg vs shields |
| F | Force Beam | no skip rules |
| N | Needle Beam | penetrates S/A (skips first 30); bays always skipped; roll D10 → Nth eligible system (wrapping); always 1 dmg |
| R | Standard Missile | `requires_ammo=True`; 10 internal charges; feeds from Mg first |
| Mg | Magazine | 50 shared charges; feeds R launchers; left-most drained first |
| D | Point Defense | 3 shots/D/volley, to-hit 3; also fires at incoming fighters |
| I | Internal (engine room) | parenthesised groups: whole group = 0 MP if any destroyed |
| G | Gun/Autocannon | fighter-scale; `anti_fighter_modifier=2`, `can_target_fighters=True` |
| Bh | Hangar Bay | CV only; each active Bh stores 1 squadron; `occupant` field tracks who |
| Bl | Launch Bay | CV only; limits launches per turn (1 launch per active Bl) |

### Ammo Consumption

- `ammo_count_for("R")` → total available: sum of active Mg charges + active R charges.
- `consume_ammo_for("R", n)` → drains leftmost active Mg first, then 1 shot per active R launcher (not greedy).
- Ammo consumption is applied to the attacker simultaneously after all fire resolves (same pattern as damage).
- If `ammo_count_for("R") == 0`, no missiles fire even if launchers are intact.

### Carrier Mechanics

- **Docked state**: `SquadronState.docked_at = carrier_id` (str). Docked squadrons have `is_deployed = False`.
- Docked squadrons are excluded from fighter combat, endurance decrement, and all hex-based logic.
- **`stage_launch(side, carrier_id, squadron_id)`**: called during MOVE_SUBMISSION; validated against active Bl count; launches process at the start of `_resolve_movement` before ships move; emits `LaunchEvent`.
- **`RecoverOrder(carrier_id)`**: submitted as a squadron order in COMBAT_SMALL; squadron must be at carrier's hex; requires empty active Bh; emits `RecoveryEvent`.
- REPL: `launch <carrier> <squadron>`, `recover <squadron> <carrier>`.

### Fighter Squadrons

- **Strength** = number of fighters (max 5). Offensive output scales linearly with strength.
- **Dogfight damage**: each hit kills exactly 1 fighter (`dmg = 1`).
- **Attack run damage**: weapon damage value applies normally to ship systems.
- **MVR modifier**: `attacker_mvr - target_mvr` added to to-hit in dogfights.
- **Ordnance penalties**: `-2 MP` while external shots remain; `-1 MVR per shot remaining`.
- **Intercept orders persist** across turns. Strike orders are one-shot.
- **Intercept radius**: `remaining_mp_after_reaching_patrol + 1`.
- **Endurance (fuel)**: decrements each deployed turn. `FuelWarningEvent` at 1 turn left; `UnitDestroyedEvent(FUEL_EXHAUSTED)` at 0. Docked squadrons do not lose endurance.

### Firing Arcs

- **Blind spot**: relative bearing 3 (dead astern). No weapon can fire here.
- **Rear-arc bonus**: attacker at bearing 3 from *target's* facing → `target_delta += 2`.
- **PD suppression**: PD disabled if attacker is in target's blind spot.
- **`WeaponArc`**: `ALL` (default) or `FORWARD` (bearing 0 only).

### Turn Structure

| Phase | Trigger | Resolution |
|-------|---------|------------|
| `MOVE_SUBMISSION` | `commit_movement(side, rng)` | Launch orders process first; then ships move simultaneously; transit through enemy squadron hex → free attack run |
| `COMBAT_SUBMISSION` | `commit_fire(side, rng)` | Simultaneous fire against pre-combat snapshot; damage and ammo consumption applied in one pass |
| `COMBAT_SMALL` | `commit_squadron_orders(side, rng)` | RecoverOrders processed first; then squadrons move, intercept, dogfight, attack run; auto-skipped if no deployed squadrons |

**Hull types** — EPR semantics: `MP = active_engine_count / EPR`.

| Hull | EPR | Engines/room | Max speed | Turn cost |
|------|-----|-------------|-----------|-----------|
| FG (Frigate) | 2/3 | 1 | 5 | 2 |
| DD (Destroyer) | 1 | 1 | 5 | 3 |
| CA (Cruiser) | 2 | 2 | 4 | 3 |
| CV (Carrier) | 2 | 2 | 4 | 3 |

### Default Scenario

`default_scenario()` in `tactical/scenarios.py`:
- **A1** (FG, Hex 0,0, NE), **A2** (CV, Hex -10,0, NE)
- **B1** (FG, Hex 6,0, S), **B2** (CV, Hex 10,0, SW)
- **AF1** (guns, Hex 1,0), **AF2** (laser+missiles, Hex 0,1)
- **BF1** (laser, Hex 5,0 — endurance=0 for testing), **BF2** (laser+missiles, Hex 6,1)
- A2 and B2 hangar bays are empty (no docked squadrons).

## Developer Preferences

- **Small, incremental changes.** Prefer drop-in snippets over large refactors.
- **Deterministic tests.** Seeded RNG; never break stable test ordering.
- **REPL-first iteration.** `python main.py` launches the web UI; REPL available via `tactical/repl.py` directly.
- **Pure functions.** Explicit state transitions; avoid implicit side effects.
- **Frozen dataclasses.** Orders and value objects use `@dataclass(frozen=True, slots=True)`.

## Design Documents

- **`docs/tactical_combat_design.md`** — Full turn structure and fighter mechanics spec. Read before implementing anything in `tactical/` related to phases, fighters, or movement. Supersedes any conflicting notes in this file.

## Known Issues / Immediate Next Work

- **Carrier refuel/rearm**: Landed squadrons should restore endurance and ordnance while docked. Currently recovery docks the squadron but no refit logic runs.
- **Mid-turn movement damage** (lower priority): `ShipState.mp` reflects previous turn's capacity mid-turn. `next_turn()` recomputes correctly so this only affects the gap between damage application and turn end.
