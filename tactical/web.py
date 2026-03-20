from __future__ import annotations

import json
import random
from dataclasses import replace
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/tactical")
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# Single-session global state (replace with per-game persistence later)
# ---------------------------------------------------------------------------

_enc = None
_rng: Optional[random.Random] = None
_log: list[str] = []
_MAX_LOG = 100

# Draft move state — built up by move/tl/tr/spend commands before commit.
# Each entry: ship_id -> {
#   "pos":           Hex,
#   "facing":        int (0-5),
#   "mp_remaining":  int,
#   "turn_charge":   int,
#   "turn_cost":     int,
#   "path":          list[Hex],   # hex waypoints from ship start (inclusive)
#   "mp_used":       int,
# }
_drafts: dict = {}


def _build_default() -> tuple:
    from sim.hexgrid import Hex
    from tactical.battle_state import BattleState
    from tactical.encounter import Encounter
    from tactical.facing import Facing
    from tactical.hull_types import FG
    from tactical.ship_state import ShipState
    from tactical.ship_systems import ShipSystems
    from tactical.squadron_state import FighterLoadout, SquadronState
    from tactical.weapons import WeaponType

    rng = random.Random(1)
    fg = "SSSSSAAAAA(I)FFRRD(I)(I)(I)"
    a = ShipState(ship_id="A1", owner_id="A", pos=Hex(0, 0), facing=Facing.NE,
                  mp=5, turn_cost=2, turn_charge=0,
                  systems=ShipSystems.parse(fg), hull_type=FG)
    b = ShipState(ship_id="B1", owner_id="B", pos=Hex(6, 0), facing=Facing.S,
                  mp=5, turn_cost=2, turn_charge=0,
                  systems=ShipSystems.parse(fg), hull_type=FG)

    af1 = SquadronState(
        squadron_id="AF1", owner_id="A", pos=Hex(1, 0),
        strength=5, max_strength=5,
        loadout=FighterLoadout(base_mvr=4, base_mp=10,
                               internal=(WeaponType.GUN,)),
        endurance=20, max_endurance=20,
    )
    af2 = SquadronState(
        squadron_id="AF2", owner_id="A", pos=Hex(0, 1),
        strength=5, max_strength=5,
        loadout=FighterLoadout(base_mvr=3, base_mp=8,
                               internal=(WeaponType.LASER,),
                               external=(WeaponType.STANDARD_MISSILE,),
                               external_shots_remaining=2),
        endurance=20, max_endurance=20,
    )
    bf1 = SquadronState(
        squadron_id="BF1", owner_id="B", pos=Hex(5, 0),
        strength=5, max_strength=5,
        loadout=FighterLoadout(base_mvr=4, base_mp=10,
                               internal=(WeaponType.GUN,)),
        endurance=20, max_endurance=20,
    )
    bf2 = SquadronState(
        squadron_id="BF2", owner_id="B", pos=Hex(6, 1),
        strength=5, max_strength=5,
        loadout=FighterLoadout(base_mvr=3, base_mp=8,
                               internal=(WeaponType.LASER,),
                               external=(WeaponType.STANDARD_MISSILE,),
                               external_shots_remaining=2),
        endurance=20, max_endurance=20,
    )

    battle = BattleState(
        ships={"A1": a, "B1": b},
        squadrons={"AF1": af1, "AF2": af2, "BF1": bf1, "BF2": bf2},
    )
    enc = Encounter.start(battle, rng=rng)
    return enc, rng


def _reset() -> None:
    global _enc, _rng, _log, _drafts
    _enc, _rng = _build_default()
    _log = []
    _drafts = {}


_reset()


# ---------------------------------------------------------------------------
# Draft-path helpers
# ---------------------------------------------------------------------------

def _get_or_create_draft(ship_id: str) -> dict:
    """Return the draft for ship_id, creating it from the current ship state."""
    if ship_id not in _drafts:
        ship = _enc.battle.ships[ship_id]
        cap  = _enc._mp_capacity.get(ship_id, ship.mp)
        _drafts[ship_id] = {
            "pos":          ship.pos,
            "facing":       int(ship.facing),
            "mp_remaining": cap,
            "turn_charge":  ship.turn_charge,
            "turn_cost":    ship.turn_cost,
            "path":         [ship.pos],
            "mp_used":      0,
        }
    return _drafts[ship_id]


def _draft_move_forward(ship_id: str, steps: int) -> list[str]:
    """Advance ship draft forward `steps` hexes in current draft facing."""
    from sim.hexgrid import Hex
    from tactical.facing import FACING_OFFSETS

    d = _get_or_create_draft(ship_id)
    if steps <= 0:
        return [f"steps must be > 0"]
    if steps > d["mp_remaining"]:
        return [f"Ship {ship_id!r} has only {d['mp_remaining']} MP remaining in this draft"]

    dq, dr = FACING_OFFSETS[d["facing"]]
    pos = d["pos"]
    new_path = list(d["path"])
    for _ in range(steps):
        pos = Hex(pos.q + dq, pos.r + dr)
        new_path.append(pos)

    d["pos"]          = pos
    d["mp_remaining"] -= steps
    d["mp_used"]      += steps
    d["turn_charge"]   = min(d["turn_charge"] + steps, d["turn_cost"])
    d["path"]          = new_path
    return [f"Draft {ship_id}: +{steps} forward → ({pos.q},{pos.r}) "
            f"facing={d['facing']} mp_left={d['mp_remaining']}"]


def _draft_turn(ship_id: str, direction: int) -> list[str]:
    """Turn draft ±1 facing step (direction: +1 = right, -1 = left)."""
    d = _get_or_create_draft(ship_id)
    if d["turn_charge"] < d["turn_cost"]:
        return [f"Cannot turn: charge={d['turn_charge']}/{d['turn_cost']} "
                f"(use 'spend {ship_id} <n>' to charge)"]
    d["facing"]      = (d["facing"] + direction) % 6
    d["turn_charge"] = 0
    facing_names     = ["N", "NE", "SE", "S", "SW", "NW"]
    return [f"Draft {ship_id}: turned → facing {facing_names[d['facing']]} "
            f"charge reset to 0"]


def _draft_spend(ship_id: str, amount: int) -> list[str]:
    """Spend MP in draft (charges turning, does not move)."""
    d = _get_or_create_draft(ship_id)
    if amount <= 0:
        return ["amount must be > 0"]
    if amount > d["mp_remaining"]:
        return [f"Ship {ship_id!r} has only {d['mp_remaining']} MP remaining"]
    d["mp_remaining"] -= amount
    d["mp_used"]      += amount
    d["turn_charge"]   = min(d["turn_charge"] + amount, d["turn_cost"])
    return [f"Draft {ship_id}: spent {amount} MP → charge={d['turn_charge']}/{d['turn_cost']} "
            f"mp_left={d['mp_remaining']}"]


# ---------------------------------------------------------------------------
# Event formatting helpers
# ---------------------------------------------------------------------------

def _fmt_shots(shots, to_hit: int | None = None) -> str:
    """Compact roll list: '3✓ 7✗ 2✓' grouped by weapon if mixed."""
    parts = []
    for s in shots:
        th = s.to_hit if to_hit is None else to_hit
        mark = "✓" if s.hit else "✗"
        parts.append(f"{s.roll}{mark}")
    return " ".join(parts)


def _fmt_dogfight(ev) -> list[str]:
    from tactical.fighter_combat import DogfightEvent
    lines = [f"  DOGFIGHT {ev.attacker_id}→{ev.target_id}  mvr={ev.mvr_delta:+}"
             f"  casualties={ev.total_casualties}"]
    # Group shots by weapon
    from itertools import groupby
    for weapon, group in groupby(ev.shots, key=lambda s: s.weapon):
        shots = list(group)
        th = shots[0].to_hit
        rolls = _fmt_shots(shots)
        hits = sum(1 for s in shots if s.hit)
        lines.append(f"    [{weapon.value}] to_hit={th}  {rolls}  hits={hits}")
    return lines


def _fmt_attack_run(ev) -> list[str]:
    from tactical.fighter_combat import AttackRunEvent
    pd_rolls = " ".join(
        f"{r}{'✓' if r <= 3 else '✗'}" for r in ev.pd_rolls
    ) or "—"
    lines = [
        f"  ATTACK RUN {ev.attacker_id}→{ev.target_id}",
        f"    PD: [{pd_rolls}]  killed={ev.fighters_killed_by_pd}"
        f"  survivors={ev.surviving_strength}",
    ]
    from itertools import groupby
    for weapon, group in groupby(ev.weapon_shots, key=lambda s: s.weapon):
        shots = list(group)
        th = shots[0].to_hit
        rolls = _fmt_shots(shots)
        hits = sum(1 for s in shots if s.hit)
        dmg  = sum(s.damage for s in shots)
        lines.append(f"    [{weapon.value}] to_hit={th}  {rolls}  hits={hits}  dmg={dmg}")
    lines.append(f"    total ship damage: {ev.total_ship_damage}")
    return lines


def _fmt_fire(ev) -> str:
    if getattr(ev, "missile_rolls", None) is not None:
        to_hit = ev.to_hit
        rolls = ", ".join(
            f"{r}{'✓' if to_hit is not None and r <= to_hit else '✗'}"
            for r in ev.missile_rolls
        )
        pd_part = ""
        if ev.pd_rolls:
            pd_rolls = ", ".join(
                f"{r}{'✓' if r <= 3 else '✗'}" for r in ev.pd_rolls
            )
            pd_part = f" pd=[{pd_rolls}] pd_int={ev.pd_intercepted}"
        else:
            pd_part = f" pd_int={ev.pd_intercepted}"
        return (f"{ev.attacker_id}→{ev.target_id} {ev.weapon.value} r={ev.range} "
                f"to_hit={ev.to_hit} rolls=[{rolls}] hits={ev.missile_hits}"
                f"{pd_part} rem={ev.remaining_hits} dmg={ev.raw_damage}")
    return (f"{ev.attacker_id}→{ev.target_id} {ev.weapon.value} r={ev.range} "
            f"roll={ev.roll} to_hit={ev.to_hit} hit={ev.hit} dmg={ev.raw_damage}")


# ---------------------------------------------------------------------------
# Command processing
# ---------------------------------------------------------------------------

def _process(cmd_line: str) -> list[str]:
    global _enc, _rng, _drafts
    out: list[str] = []
    parts = cmd_line.strip().split()
    if not parts:
        return out
    cmd = parts[0].lower()

    try:
        if cmd == "reset":
            _reset()
            out.append("Reset to default scenario.")

        # ---------------------------------------------------------------- #
        # Movement path building (MOVE_SUBMISSION)                          #
        # ---------------------------------------------------------------- #

        elif cmd == "move":
            # move <ship_id> <steps>            — forward N hexes in current draft facing
            # move <ship_id> <q> <r> [facing]  — go directly to hex (bypasses draft)
            if len(parts) < 3:
                out.append("usage: move <ship_id> <steps>  OR  move <ship_id> <q> <r> [facing]")
                return out
            ship_id = parts[1]
            if ship_id not in _enc.battle.ships:
                out.append(f"unknown ship: {ship_id!r}"); return out

            from tactical.encounter import Phase
            if _enc.phase == Phase.MOVE_SUBMISSION:
                if len(parts) == 3:
                    out += _draft_move_forward(ship_id, int(parts[2]))
                else:
                    # Direct hex destination — stage immediately, no draft
                    from sim.hexgrid import Hex
                    from tactical.facing import Facing
                    ship = _enc.battle.ships[ship_id]
                    dest = Hex(int(parts[2]), int(parts[3]))
                    dest_facing = (
                        Facing.from_int(int(parts[4])) if len(parts) >= 5 else ship.facing
                    )
                    side = ship.owner_id
                    _enc = _enc.stage_move(side, ship_id, dest, dest_facing)
                    out.append(f"Staged: {ship_id} → ({dest.q},{dest.r}) facing={int(dest_facing)}")
            else:
                out.append(f"Cannot move: phase is {_enc.phase.value!r}")

        elif cmd in ("tl", "tr"):
            if len(parts) != 2:
                out.append(f"usage: {cmd} <ship_id>"); return out
            ship_id = parts[1]
            if ship_id not in _enc.battle.ships:
                out.append(f"unknown ship: {ship_id!r}"); return out
            from tactical.encounter import Phase
            if _enc.phase != Phase.MOVE_SUBMISSION:
                out.append(f"Cannot turn: phase is {_enc.phase.value!r}"); return out
            direction = +1 if cmd == "tr" else -1
            out += _draft_turn(ship_id, direction)

        elif cmd == "spend":
            if len(parts) != 3:
                out.append("usage: spend <ship_id> <amount>"); return out
            ship_id = parts[1]
            if ship_id not in _enc.battle.ships:
                out.append(f"unknown ship: {ship_id!r}"); return out
            from tactical.encounter import Phase
            if _enc.phase != Phase.MOVE_SUBMISSION:
                out.append(f"Cannot spend: phase is {_enc.phase.value!r}"); return out
            out += _draft_spend(ship_id, int(parts[2]))

        elif cmd == "commit":
            if len(parts) < 2:
                out.append("usage: commit move [side_id]  |  commit fire [side_id]")
                return out
            from tactical.encounter import Phase
            sub = parts[1].lower()

            if sub == "move":
                if _enc.phase != Phase.MOVE_SUBMISSION:
                    out.append(f"Not in move_submission phase (current: {_enc.phase.value})")
                    return out
                # Stage move orders from all pending drafts first
                from tactical.facing import Facing
                for ship_id, d in list(_drafts.items()):
                    if ship_id not in _enc.battle.ships:
                        continue
                    ship = _enc.battle.ships[ship_id]
                    side = ship.owner_id
                    try:
                        _enc = _enc.stage_move(
                            side, ship_id,
                            d["pos"], Facing.from_int(d["facing"]),
                            path_cost=d["mp_used"],
                            path=tuple(d["path"]),
                        )
                        out.append(
                            f"Staged from draft: {ship_id} → ({d['pos'].q},{d['pos'].r}) "
                            f"facing={d['facing']} cost={d['mp_used']}"
                        )
                    except Exception as e:
                        out.append(f"Draft {ship_id} invalid: {e}")
                _drafts = {}

                sides_to_commit = (
                    [parts[2]] if len(parts) >= 3
                    else sorted(_enc.sides() - _enc._move_committed)
                )
                from tactical.fighter_combat import AttackRunEvent, DogfightEvent
                for s in sides_to_commit:
                    _enc, mv_events = _enc.commit_movement(s, _rng)
                    out.append(f"Side {s!r} committed movement.")
                    for ev in mv_events:
                        if isinstance(ev, AttackRunEvent):
                            out.append(
                                f"  TRANSIT: {ev.attacker_id}→{ev.target_id}"
                                f" pd_killed={ev.fighters_killed_by_pd}"
                                f" survivors={ev.surviving_strength}"
                                f" hits={sum(1 for s in ev.weapon_shots if s.hit)}"
                                f" dmg={ev.total_ship_damage}"
                            )
                    if _enc.phase == Phase.COMBAT_SUBMISSION:
                        out.append("→ Movement resolved. Now in COMBAT_SUBMISSION.")
                        break

            elif sub == "fire":
                if _enc.phase != Phase.COMBAT_SUBMISSION:
                    out.append(f"Not in combat_submission phase (current: {_enc.phase.value})")
                    return out
                sides_to_commit = (
                    [parts[2]] if len(parts) >= 3
                    else sorted(_enc.sides() - _enc._fire_committed)
                )
                for s in sides_to_commit:
                    _enc, events = _enc.commit_fire(s, _rng)
                    out.append(f"Side {s!r} committed fire orders.")
                    out += [_fmt_fire(ev) for ev in events]
                    if _enc.phase in (Phase.COMBAT_SMALL, Phase.MOVE_SUBMISSION):
                        phase_label = "COMBAT_SMALL" if _enc.phase == Phase.COMBAT_SMALL else "next turn"
                        out.append(f"→ Fire resolved. Entering {phase_label}.")
                        break

            elif sub == "squadrons":
                if _enc.phase != Phase.COMBAT_SMALL:
                    out.append(f"Not in combat_small phase (current: {_enc.phase.value})")
                    return out
                sides_to_commit = (
                    [parts[2]] if len(parts) >= 3
                    else sorted(_enc.sides() - _enc._squadron_committed)
                )
                from tactical.fighter_combat import AttackRunEvent, DogfightEvent
                for s in sides_to_commit:
                    _enc, events = _enc.commit_squadron_orders(s, _rng)
                    out.append(f"Side {s!r} committed squadron orders.")
                    for ev in events:
                        if isinstance(ev, DogfightEvent):
                            out.extend(_fmt_dogfight(ev))
                        elif isinstance(ev, AttackRunEvent):
                            out.extend(_fmt_attack_run(ev))
                    if _enc.phase == Phase.MOVE_SUBMISSION:
                        out.append("→ Fighter phase resolved. Starting next turn.")
                        break

            else:
                out.append("usage: commit move [side_id]  |  commit fire [side_id]  |  commit squadrons [side_id]")

        # ---------------------------------------------------------------- #
        # Combat submission                                                  #
        # ---------------------------------------------------------------- #

        elif cmd == "fireall":
            if len(parts) != 3:
                out.append("usage: fireall <ship_id> <target_id>"); return out
            ship_id, target_id = parts[1], parts[2]
            if ship_id not in _enc.battle.ships:
                out.append(f"unknown ship: {ship_id!r}"); return out
            side = _enc.battle.ships[ship_id].owner_id
            _enc = _enc.stage_fire(side, ship_id, target_id)
            out.append(f"Staged: {ship_id} fires all weapons at {target_id}")

        elif cmd == "pass":
            if len(parts) != 2:
                out.append("usage: pass <ship_id>"); return out
            ship_id = parts[1]
            if ship_id not in _enc.battle.ships:
                out.append(f"unknown ship: {ship_id!r}"); return out
            side = _enc.battle.ships[ship_id].owner_id
            _enc = _enc.pass_fire(side, ship_id)
            out.append(f"Staged: {ship_id} passes fire")

        # ---------------------------------------------------------------- #
        # COMBAT_SMALL — fighter orders                                      #
        # ---------------------------------------------------------------- #

        elif cmd == "intercept":
            # intercept <squad_id> <q> <r>
            if len(parts) != 4:
                out.append("usage: intercept <squad_id> <q> <r>"); return out
            sq_id = parts[1]
            if sq_id not in _enc.battle.squadrons:
                out.append(f"unknown squadron: {sq_id!r}"); return out
            from tactical.encounter import Phase
            if _enc.phase != Phase.COMBAT_SMALL:
                out.append(f"Cannot order: phase is {_enc.phase.value!r}"); return out
            from sim.hexgrid import Hex
            from tactical.turn_orders import InterceptOrder
            patrol = Hex(int(parts[2]), int(parts[3]))
            side   = _enc.battle.squadrons[sq_id].owner_id
            _enc   = _enc.stage_squadron_order(side, sq_id, InterceptOrder(patrol_hex=patrol))
            out.append(f"Staged: {sq_id} INTERCEPT at ({patrol.q},{patrol.r})")

        elif cmd == "strike":
            # strike <squad_id> <target_id>
            if len(parts) != 3:
                out.append("usage: strike <squad_id> <target_id>"); return out
            sq_id, target_id = parts[1], parts[2]
            if sq_id not in _enc.battle.squadrons:
                out.append(f"unknown squadron: {sq_id!r}"); return out
            from tactical.encounter import Phase
            if _enc.phase != Phase.COMBAT_SMALL:
                out.append(f"Cannot order: phase is {_enc.phase.value!r}"); return out
            from tactical.turn_orders import StrikeOrder
            side = _enc.battle.squadrons[sq_id].owner_id
            _enc = _enc.stage_squadron_order(side, sq_id, StrikeOrder(target_id=target_id))
            out.append(f"Staged: {sq_id} STRIKE → {target_id}")

        # ---------------------------------------------------------------- #
        # Debug / quick fire (bypass submission system)                      #
        # ---------------------------------------------------------------- #

        elif cmd == "quickfire":
            if len(parts) != 3:
                out.append("usage: quickfire <attacker_id> <target_id>"); return out
            attacker_id, target_id = parts[1], parts[2]
            if attacker_id not in _enc.battle.ships:
                out.append(f"unknown ship: {attacker_id!r}"); return out
            from tactical.combat import resolve_fire_all
            new_battle, events = resolve_fire_all(
                _enc.battle, attacker_id=attacker_id, target_id=target_id, rng=_rng)
            _enc = replace(_enc, battle=new_battle)
            out += [_fmt_fire(ev) for ev in events] or [f"{attacker_id} has no active weapons."]

        elif cmd == "shoot":
            if len(parts) != 4:
                out.append("usage: shoot <attacker_id> <target_id> <weapon_code>"); return out
            attacker_id, target_id, wcode = parts[1], parts[2], parts[3].upper()
            from tactical.combat import resolve_large_fire
            from tactical.weapons import WeaponType
            try:
                weapon = WeaponType(wcode)
            except Exception:
                out.append(f"unknown weapon_code: {wcode!r}"); return out
            new_battle, ev = resolve_large_fire(
                _enc.battle, attacker_id=attacker_id, target_id=target_id,
                weapon=weapon, rng=_rng)
            _enc = replace(_enc, battle=new_battle)
            out.append(_fmt_fire(ev))

        else:
            out.append(f"unknown command: {cmd!r}")
            out.append("move/tl/tr/spend  commit move  fireall/pass  commit fire  quickfire/shoot  reset")

    except Exception as e:
        out.append(f"ERROR: {e}")

    return out


# ---------------------------------------------------------------------------
# State rendering helpers
# ---------------------------------------------------------------------------

def _render_units() -> str:
    lines = []
    for sid in _enc.battle.ship_ids_sorted():
        ship = _enc.battle.ships[sid]
        lines.append(
            f"{sid:>4}  owner={ship.owner_id}  pos=({ship.pos.q:+},{ship.pos.r:+})"
            f"  face={int(ship.facing)}  mp={ship.mp}"
            f"\n      systems=[{ship.systems.render_compact() if ship.systems else '-'}]"
        )
    for sqid in _enc.battle.squadron_ids_sorted():
        sq = _enc.battle.squadrons[sqid]
        internal = "".join(w.value for w in sq.loadout.internal)
        external = "".join(w.value for w in sq.loadout.external)
        loadout  = internal + (f"[{external}×{sq.loadout.external_shots_remaining}]" if external else "")
        lines.append(
            f"{sqid:>4}  owner={sq.owner_id}  pos=({sq.pos.q:+},{sq.pos.r:+})"
            f"  str={sq.strength}/{sq.max_strength}"
            f"  mvr={sq.effective_mvr}  mp={sq.effective_mp}"
            f"  load={loadout}"
        )
    return "\n".join(lines)


def _render_phase() -> str:
    from tactical.encounter import Phase
    enc = _enc
    phase = enc.phase.value.upper()
    if enc.phase == Phase.MOVE_SUBMISSION:
        committed = sorted(enc._move_committed)
        return f"{phase}  committed={committed}"
    if enc.phase == Phase.COMBAT_SUBMISSION:
        committed = sorted(enc._fire_committed)
        return f"{phase}  committed={committed}"
    return phase


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _ships_json() -> str:
    return json.dumps([
        {"id": sid, "owner": s.owner_id, "q": s.pos.q, "r": s.pos.r, "facing": int(s.facing)}
        for sid, s in _enc.battle.ships.items()
    ])


def _squadrons_json() -> str:
    return json.dumps([
        {
            "id":       sqid,
            "owner":    sq.owner_id,
            "q":        sq.pos.q,
            "r":        sq.pos.r,
            "strength": sq.strength,
            "max":      sq.max_strength,
        }
        for sqid, sq in _enc.battle.squadrons.items()
    ])


def _paths_json() -> str:
    """Serialize pending draft paths for canvas rendering."""
    paths = []
    for ship_id, d in _drafts.items():
        if ship_id not in _enc.battle.ships:
            continue
        ship = _enc.battle.ships[ship_id]
        paths.append({
            "shipId":      ship_id,
            "owner":       ship.owner_id,
            "hexes":       [{"q": h.q, "r": h.r} for h in d["path"]],
            "finalFacing": d["facing"],
        })
    return json.dumps(paths)


def _intercept_paths_json() -> str:
    """Serialize staged intercept orders as {owner, hexes} paths for canvas."""
    from tactical.turn_orders import InterceptOrder
    paths = []
    for sq_id, order in _enc._squadron_orders.items():
        if not isinstance(order, InterceptOrder):
            continue
        sq = _enc.battle.squadrons.get(sq_id)
        if sq is None:
            continue
        if sq.pos == order.patrol_hex:
            continue  # already at patrol hex, nothing to draw
        paths.append({
            "owner": sq.owner_id,
            "hexes": [
                {"q": sq.pos.q, "r": sq.pos.r},
                {"q": order.patrol_hex.q, "r": order.patrol_hex.r},
            ],
        })
    return json.dumps(paths)


def _intercept_zones_json() -> str:
    """Serialize staged intercept orders as {owner, q, r, radius} zones."""
    from tactical.fighter_combat import hex_distance
    from tactical.turn_orders import InterceptOrder
    zones = []
    for sq_id, order in _enc._squadron_orders.items():
        if not isinstance(order, InterceptOrder):
            continue
        sq = _enc.battle.squadrons.get(sq_id)
        if sq is None:
            continue
        dist   = hex_distance(sq.pos, order.patrol_hex)
        radius = max(0, sq.effective_mp - dist + 1)
        zones.append({
            "owner":  sq.owner_id,
            "q":      order.patrol_hex.q,
            "r":      order.patrol_hex.r,
            "radius": radius,
        })
    return json.dumps(zones)


def _strike_orders_json() -> str:
    """Serialize staged strike orders as attacker→target arrows."""
    from tactical.encounter import Phase
    from tactical.turn_orders import StrikeOrder
    if _enc.phase != Phase.COMBAT_SMALL:
        return json.dumps([])
    orders = []
    for sq_id, order in _enc._squadron_orders.items():
        if not isinstance(order, StrikeOrder):
            continue
        attacker = _enc.battle.squadrons.get(sq_id)
        if attacker is None:
            continue
        if order.target_id in _enc.battle.ships:
            target_pos = _enc.battle.ships[order.target_id].pos
        elif order.target_id in _enc.battle.squadrons:
            target_pos = _enc.battle.squadrons[order.target_id].pos
        else:
            continue
        orders.append({
            "attacker_owner": attacker.owner_id,
            "aq": attacker.pos.q, "ar": attacker.pos.r,
            "tq": target_pos.q,  "tr": target_pos.r,
        })
    return json.dumps(orders)


def _fire_orders_json() -> str:
    """Serialize staged fire orders for canvas rendering."""
    from tactical.encounter import Phase
    if _enc.phase != Phase.COMBAT_SUBMISSION:
        return json.dumps([])
    orders = []
    for ship_id, order in _enc._fire_orders.items():
        if order is None:
            continue
        attacker = _enc.battle.ships.get(ship_id)
        target   = _enc.battle.ships.get(order.target_id)
        if attacker is None or target is None:
            continue
        orders.append({
            "attacker_id":    ship_id,
            "target_id":      order.target_id,
            "attacker_owner": attacker.owner_id,
            "aq": attacker.pos.q, "ar": attacker.pos.r,
            "tq": target.pos.q,  "tr": target.pos.r,
        })
    return json.dumps(orders)


@router.get("/", response_class=HTMLResponse)
async def tactical_ui(request: Request):
    return templates.TemplateResponse("tactical.html", {
        "request":          request,
        "phase":            _render_phase(),
        "units_text":           _render_units(),
        "ships_json":           _ships_json(),
        "squadrons_json":       _squadrons_json(),
        "paths_json":           _paths_json(),
        "fire_orders_json":     _fire_orders_json(),
        "strike_orders_json":   _strike_orders_json(),
        "intercept_paths_json": _intercept_paths_json(),
        "intercept_zones_json": _intercept_zones_json(),
        "log":              "\n".join(_log[-40:]),
    })


@router.post("/command")
async def tactical_command(cmd: str = Form(...)):
    global _log
    _log.append(f"> {cmd}")
    output = _process(cmd)
    _log.extend(output)
    if len(_log) > _MAX_LOG:
        _log = _log[-_MAX_LOG:]
    return RedirectResponse(url="/tactical/", status_code=303)
