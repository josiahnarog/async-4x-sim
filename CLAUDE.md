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

- **Strategic Engine (v1)** — `sim/`, `app.py`, `db.py`. Likely to be partially or fully deprecated and replaced by a different strategic interface once the tactical layer is complete. Do not extend or refactor unless explicitly asked. Keep it in place — cost of removal now is higher than leaving it.
- **Tactical Engine (v2)** — `tactical/`. **Active development.** Ship-level tactical combat on a hex grid. This is the sole current focus.

## Development Roadmap

The project develops in the following sequence. Each phase is roughly independent, though later phases depend on earlier ones being solid.

1. **Tight combat loop** *(current)* — Close all gaps in the core encounter mechanics: fighter lifecycle, turn-cost enforcement, win/loss detection, partial movement, break-off.
2. **Combat features** — Additional weapons and systems (carriers, sensors, fog of war, re-arm/refuel mechanics). Additional hull types in scenarios. Basic AI for enemy ships. Expanded default scenarios for playtesting.
3. **Persistence and multiplayer** — Per-game tactical persistence (SQLite, keyed by game ID). Web hosting. Async multiplayer via turn-based submission.
4. **Ship design interface** — Rules-enforced ship construction with systems validation, cost calculation, and construction-point budgets. Enables instant-battle scenarios (player-vs-player or player-vs-AI) with a fair point budget.
5. **Strategic campaign** — System and interstellar maps, random map generation, economy, colonization, construction queues, technology trees. May borrow elements from the v1 strategic engine.

## Architecture

### Tactical Engine (`tactical/`) — primary codebase

- **`encounter.py`** — State machine: `MOVE_SUBMISSION → COMBAT_SUBMISSION → COMBAT_SMALL → next_turn()`. Immutable frozen dataclass; all mutations return new instances.
- **`battle_state.py`** — Ships and squadrons during an encounter. `with_ship()`, `with_squadron()`, etc.
- **`fighter_combat.py`** — COMBAT_SMALL resolver: squadron movement, intercept engagement, dogfights, attack runs.
- **`squadron_state.py`** — `SquadronState` and `FighterLoadout`; effective MVR/MP with ordnance penalties.
- **`turn_orders.py`** — `ShipMoveOrder` (with `path`), `ShipFireOrder`, `InterceptOrder`, `StrikeOrder`.
- **`combat.py`** — `resolve_large_fire` and `resolve_fire_all`; arc enforcement.
- **`weapons.py`** / **`missile_volley.py`** — Weapon specs and missile/PD resolution.
- **`ship_state.py`** / **`ship_systems.py`** — Per-ship damage and systems (compact display e.g. `SSSAAALL(III)`).
- **`arcs.py`** — Firing arc geometry: `relative_bearing`, blind-spot constants, rear-arc bonus.
- **`hull_types.py`** — `HullType` (FG/DD/CA/CV): EPR, engines-per-room, max speed.
- **`to_hit.py`** — Centralised hit resolution. **Invariant: hit if `roll ≤ target`.**
- **`web.py`** — FastAPI router (`/tactical/`). Single-session global state (pending persistence work).
- **`repl.py`** — Interactive CLI; primary development interface.

### Supporting files

- **`app.py`** — Mounts the tactical router; root redirects to `/tactical/`.
- **`main.py`** — Launches uvicorn on port 8001.
- **`templates/tactical.html`** — Canvas hex map (flat-top, radius 8) + command input + log.
- **`sim/hexgrid.py`** — Hex grid with axial coordinates; used by both engines.

### Strategic Engine (`sim/`, deprecated-pending)

Do not modify. If strategic concepts are needed for the campaign layer, design fresh rather than extending the v1 code.

## Tactical Engine — Critical Rules

### To-Hit Invariant

> **Hit if: `roll ≤ target`** — higher target = easier to hit.

d10 system. All resolution goes through `roll_hits_target(...)` in `tactical/to_hit.py`. Never bypass this.

### Ship Systems

Ordered left-to-right; **damage order matters**. Compact notation: `SSSAAALL(III)(III)`.

| Code | System | Notes |
|------|--------|-------|
| S | Shield | |
| A | Armor | |
| L | Laser | skips shields |
| E | Electron Beam | skips armor+hull; half dmg vs shields |
| F | Force Beam | no skip rules |
| R | Standard Missile | range table; `can_target_fighters=False` |
| D | Point Defense | 3 shots/D/volley, to-hit 3; also fires at incoming fighters |
| I | Internal (engine room) | parenthesised groups: whole group = 0 MP if any destroyed |
| G | Gun/Autocannon | fighter-scale; `anti_fighter_modifier=2`, `can_target_fighters=True` |
| Bh | Hangar Bay | CV only; each active Bh stores/refits/refuels 1 squadron |
| Bl | Launch Bay | CV only; each active Bl can launch or recover 1 squadron per turn |

### Fighter Squadrons

- **Strength** = number of fighters (max 5). Offensive output scales linearly with strength.
- **Dogfight damage**: each hit kills exactly 1 fighter (`dmg = 1`), regardless of weapon damage value.
- **Attack run damage**: weapon damage value applies normally to target ship systems.
- **MVR modifier**: `attacker_mvr - target_mvr` added to to-hit in dogfights.
- **Ordnance penalties**: `-2 MP` while external shots remain; `-1 MVR per shot remaining`.
- **Intercept orders persist** across turns as standing patrol orders. Strike orders are one-shot.
- **Intercept radius**: `remaining_mp_after_reaching_patrol + 1`. Checked against all enemy positions after movement.

### Firing Arcs

- **Blind spot**: relative bearing 3 (dead astern). No weapon can fire here.
- **Rear-arc bonus**: attacker at bearing 3 from *target's* facing → `target_delta += 2`.
- **PD suppression**: PD disabled if attacker is in target's blind spot.
- **`WeaponArc`**: `ALL` (default) or `FORWARD` (bearing 0 only).

### Turn Structure

| Phase | Trigger | Resolution |
|-------|---------|------------|
| `MOVE_SUBMISSION` | `commit_movement(side, rng)` → returns `(Encounter, [transit_events])` | Ships move simultaneously; collisions resolved by initiative; transit through enemy squadron hex → free attack run |
| `COMBAT_SUBMISSION` | `commit_fire(side, rng)` → returns `(Encounter, [fire_events])` | Simultaneous fire against pre-combat snapshot; damage applied in one pass |
| `COMBAT_SMALL` | `commit_squadron_orders(side, rng)` → returns `(Encounter, [fighter_events])` | Squadrons move, intercept, dogfight, attack run; auto-skipped if no squadrons |

**Hull types** — EPR semantics: `MP = active_engine_count / EPR`.

| Hull | EPR | Max speed | Turn cost |
|------|-----|-----------|-----------|
| FG (Frigate) | 2/3 | 5 | 2 |
| DD (Destroyer) | 1 | 5 | 2 |
| CA (Cruiser) | 2 | 4 | 3 |
| CV (Carrier) | 2 | 4 | 3 |

## Developer Preferences

- **Small, incremental changes.** Prefer drop-in snippets over large refactors.
- **Deterministic tests.** Seeded RNG; never break stable test ordering.
- **REPL-first iteration.** `python main.py` launches the web UI; REPL available via `tactical/repl.py` directly.
- **Pure functions.** Explicit state transitions; avoid implicit side effects.
- **Frozen dataclasses.** Orders and value objects use `@dataclass(frozen=True, slots=True)`.

## Design Documents

- **`docs/tactical_combat_design.md`** — Full turn structure and fighter mechanics spec. Read before implementing anything in `tactical/` related to phases, fighters, or movement. Supersedes any conflicting notes in this file.

## Known Issues / Immediate Next Work

- **Turn-cost enforcement (high priority)**: Ships freely choose any facing at their destination. The turn system (spending MP to charge a turn) is tracked in `ShipMoveOrder` and drafts but not validated at commitment time.
- **Fighter endurance expiry**: Endurance decrements each turn but squadrons are never removed when it hits 0. Add auto-recall.
- **Partial fighter movement**: Squadrons that can't reach a strike target stay put instead of moving as far as MP allows.
- **Break-off mechanic**: Engaged squadrons cannot disengage. Need a `BreakOffOrder` or similar.
- **Mid-turn movement damage** (lower priority): `ShipState.mp` reflects previous turn's capacity mid-turn. `next_turn()` recomputes correctly so this only affects the gap between damage application and turn end.
