from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass, field
from dataclasses import replace
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from tactical.persistence import (
    init_db, list_games, save_game, load_game, delete_game as _db_delete,
    append_turn_snapshot, append_turn_events,
    save_design, load_design, list_designs, delete_design as _db_delete_design,
)
from tactical.ship_catalog import (
    HULL_CATALOG, SYSTEMS, HULL_BY_DESIGNATION, SYSTEMS_BY_CODE,
    track_to_system_string, system_string_to_track,
    hull_base_cost, systems_cost, systems_hull_spaces, hull_engines_per_room,
)

router = APIRouter(prefix="/tactical")
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# Initialise database at import time
# ---------------------------------------------------------------------------

init_db()

# ---------------------------------------------------------------------------
# In-memory game sessions
# ---------------------------------------------------------------------------

@dataclass
class GameSession:
    game_id: str
    name: str
    enc: object          # Encounter — typed loosely to avoid circular import
    rng: random.Random
    log: list[str]
    turn_number: int
    # Transient draft state (never persisted):
    drafts: dict = field(default_factory=dict)

_sessions: dict[str, GameSession] = {}
_MAX_LOG = 50


def _get_session(game_id: str) -> GameSession:
    """Return in-memory session, loading from DB if necessary."""
    if game_id not in _sessions:
        enc, rng, log, turn_number, name = load_game(game_id)
        _sessions[game_id] = GameSession(
            game_id=game_id, name=name, enc=enc, rng=rng,
            log=log, turn_number=turn_number,
        )
    return _sessions[game_id]


def _autosave(session: GameSession) -> None:
    save_game(
        game_id=session.game_id,
        name=session.name,
        enc=session.enc,
        rng=session.rng,
        log=session.log,
        turn_number=session.turn_number,
    )


def _new_game(name: str) -> GameSession:
    from tactical.encounter import Encounter
    from tactical.scenarios import default_scenario

    game_id = str(uuid.uuid4())
    battle, rng = default_scenario()
    enc = Encounter.start(battle, rng=rng)
    session = GameSession(
        game_id=game_id, name=name, enc=enc, rng=rng,
        log=[], turn_number=1,
    )
    _sessions[game_id] = session
    save_game(
        game_id=game_id, name=name, enc=enc, rng=rng,
        log=[], turn_number=1,
    )
    return session


# ---------------------------------------------------------------------------
# Draft-path helpers  (operate on session.drafts / session.enc)
# ---------------------------------------------------------------------------

def _get_or_create_draft(session: GameSession, ship_id: str) -> dict:
    if ship_id not in session.drafts:
        ship = session.enc.battle.ships[ship_id]
        cap  = session.enc._mp_capacity.get(ship_id, ship.mp)
        session.drafts[ship_id] = {
            "pos":          ship.pos,
            "facing":       int(ship.facing),
            "mp_remaining": cap,
            "turn_charge":  ship.turn_charge,
            "turn_cost":    ship.turn_cost,
            "path":         [ship.pos],
            "mp_used":      0,
        }
    return session.drafts[ship_id]


def _draft_move_forward(session: GameSession, ship_id: str, steps: int) -> list[str]:
    from sim.hexgrid import Hex
    from tactical.facing import FACING_OFFSETS

    d = _get_or_create_draft(session, ship_id)
    if steps <= 0:
        return ["steps must be > 0"]
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


def _draft_turn(session: GameSession, ship_id: str, direction: int) -> list[str]:
    d = _get_or_create_draft(session, ship_id)
    if d["turn_charge"] < d["turn_cost"]:
        return [f"Cannot turn: charge={d['turn_charge']}/{d['turn_cost']} "
                f"(use 'spend {ship_id} <n>' to charge)"]
    d["facing"]      = (d["facing"] + direction) % 6
    d["turn_charge"] = 0
    facing_names     = ["N", "NE", "SE", "S", "SW", "NW"]
    return [f"Draft {ship_id}: turned → facing {facing_names[d['facing']]} "
            f"charge reset to 0"]


def _draft_spend(session: GameSession, ship_id: str, amount: int) -> list[str]:
    d = _get_or_create_draft(session, ship_id)
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

from tactical.web_formatters import (
    fmt_shots as _fmt_shots,
    fmt_dogfight as _fmt_dogfight,
    fmt_attack_run as _fmt_attack_run,
    fmt_fire as _fmt_fire,
)


# ---------------------------------------------------------------------------
# ID resolution helpers
# ---------------------------------------------------------------------------

def _resolve_ship_id(session: GameSession, id_str: str) -> str:
    """Resolve a ship ID string to the internal ship_id key.

    Ship IDs are now display IDs (e.g. 'AFG1', 'ACA-V2'), so this is a
    direct dict lookup.  Raises KeyError if not found.
    """
    if id_str in session.enc.battle.ships:
        return id_str
    raise KeyError(id_str)


def _resolve_unit_id(session: GameSession, id_str: str) -> str:
    """Resolve an ID for any unit (ship or squadron).

    Used for StrikeOrder targets which may be either.
    """
    try:
        return _resolve_ship_id(session, id_str)
    except KeyError:
        pass
    if id_str in session.enc.battle.squadrons:
        return id_str
    raise KeyError(id_str)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def _detection_level(unit_id: str, owner_id: str, view: str, enc) -> int:
    if view == "master" or owner_id == view:
        return 3
    return enc._knowledge.get(view, {}).get(unit_id, 0)


# ---------------------------------------------------------------------------
# Command processing
# ---------------------------------------------------------------------------

def _process(session: GameSession, cmd_line: str) -> list[str]:
    out: list[str] = []
    parts = cmd_line.strip().split()
    if not parts:
        return out
    cmd = parts[0].lower()

    try:
        # ---------------------------------------------------------------- #
        # Movement path building (MOVE_SUBMISSION)                          #
        # ---------------------------------------------------------------- #

        if cmd == "move":
            if len(parts) < 3:
                out.append("usage: move <ship_id> <steps>  OR  move <ship_id> <q> <r> [facing]")
                return out
            try:
                ship_id = _resolve_ship_id(session, parts[1])
            except KeyError:
                out.append(f"unknown ship: {parts[1]!r}"); return out

            from tactical.encounter import Phase
            if session.enc.phase == Phase.MOVE_SUBMISSION:
                if len(parts) == 3:
                    out += _draft_move_forward(session, ship_id, int(parts[2]))
                else:
                    from sim.hexgrid import Hex
                    from tactical.facing import Facing
                    ship = session.enc.battle.ships[ship_id]
                    dest = Hex(int(parts[2]), int(parts[3]))
                    dest_facing = (
                        Facing.from_int(int(parts[4])) if len(parts) >= 5 else ship.facing
                    )
                    side = ship.owner_id
                    session.enc = session.enc.stage_move(side, ship_id, dest, dest_facing)
                    out.append(f"Staged: {ship_id} → ({dest.q},{dest.r}) facing={int(dest_facing)}")
            else:
                out.append(f"Cannot move: phase is {session.enc.phase.value!r}")

        elif cmd in ("tl", "tr"):
            if len(parts) != 2:
                out.append(f"usage: {cmd} <ship_id>"); return out
            try:
                ship_id = _resolve_ship_id(session, parts[1])
            except KeyError:
                out.append(f"unknown ship: {parts[1]!r}"); return out
            from tactical.encounter import Phase
            if session.enc.phase != Phase.MOVE_SUBMISSION:
                out.append(f"Cannot turn: phase is {session.enc.phase.value!r}"); return out
            direction = +1 if cmd == "tr" else -1
            out += _draft_turn(session, ship_id, direction)

        elif cmd == "spend":
            if len(parts) != 3:
                out.append("usage: spend <ship_id> <amount>"); return out
            try:
                ship_id = _resolve_ship_id(session, parts[1])
            except KeyError:
                out.append(f"unknown ship: {parts[1]!r}"); return out
            from tactical.encounter import Phase
            if session.enc.phase != Phase.MOVE_SUBMISSION:
                out.append(f"Cannot spend: phase is {session.enc.phase.value!r}"); return out
            out += _draft_spend(session, ship_id, int(parts[2]))

        elif cmd == "commit":
            if len(parts) < 2:
                out.append("usage: commit move [side_id]  |  commit fire [side_id]")
                return out
            from tactical.encounter import Phase
            sub = parts[1].lower()

            if sub == "move":
                if session.enc.phase != Phase.MOVE_SUBMISSION:
                    out.append(f"Not in move_submission phase (current: {session.enc.phase.value})")
                    return out
                from tactical.facing import Facing
                for ship_id, d in list(session.drafts.items()):
                    if ship_id not in session.enc.battle.ships:
                        continue
                    ship = session.enc.battle.ships[ship_id]
                    side = ship.owner_id
                    try:
                        session.enc = session.enc.stage_move(
                            side, ship_id,
                            d["pos"], Facing.from_int(d["facing"]),
                            path_cost=d["mp_used"],
                            path=tuple(d["path"]),
                            final_turn_charge=d["turn_charge"],
                        )
                        out.append(
                            f"Staged from draft: {ship_id} → ({d['pos'].q},{d['pos'].r}) "
                            f"facing={d['facing']} cost={d['mp_used']}"
                        )
                    except Exception as e:
                        out.append(f"Draft {ship_id} invalid: {e}")
                session.drafts = {}

                sides_to_commit = (
                    [parts[2]] if len(parts) >= 3
                    else sorted(session.enc.sides() - session.enc._move_committed)
                )
                from tactical.events import FuelWarningEvent, UnitDestroyedEvent
                from tactical.fighter_events import AttackRunEvent, DogfightEvent
                all_mv_events = []
                for s in sides_to_commit:
                    session.enc, mv_events = session.enc.commit_movement(s, session.rng)
                    all_mv_events.extend(mv_events)
                    out.append(f"Side {s!r} committed movement.")
                    for ev in mv_events:
                        if isinstance(ev, AttackRunEvent):
                            out.extend(_fmt_attack_run(ev, label="TRANSIT"))
                        elif isinstance(ev, UnitDestroyedEvent):
                            out.append(f"  *** {ev.unit_id} DESTROYED ({ev.cause.value}) ***")
                    if session.enc.phase == Phase.COMBAT_SUBMISSION:
                        out.append("→ Movement resolved. Now in COMBAT_SUBMISSION.")
                        break
                append_turn_events(
                    session.game_id, session.turn_number, "move_submission", all_mv_events
                )
                _autosave(session)

            elif sub == "fire":
                if session.enc.phase != Phase.COMBAT_SUBMISSION:
                    out.append(f"Not in combat_submission phase (current: {session.enc.phase.value})")
                    return out
                sides_to_commit = (
                    [parts[2]] if len(parts) >= 3
                    else sorted(session.enc.sides() - session.enc._fire_committed)
                )
                from tactical.events import BattleEndEvent, FuelWarningEvent, UnitDestroyedEvent
                all_fire_events = []
                for s in sides_to_commit:
                    session.enc, events = session.enc.commit_fire(s, session.rng)
                    all_fire_events.extend(events)
                    out.append(f"Side {s!r} committed fire orders.")
                    for ev in events:
                        if isinstance(ev, UnitDestroyedEvent):
                            out.append(f"  *** {ev.unit_id} DESTROYED ({ev.cause.value}) ***")
                        elif isinstance(ev, FuelWarningEvent):
                            out.append(f"  WARNING: {ev.squadron_id} is out of fuel")
                        elif isinstance(ev, BattleEndEvent):
                            msg = "MUTUAL DESTRUCTION (draw)" if ev.is_draw else f"{ev.winner} WINS"
                            out.append(f"  *** BATTLE OVER — {msg} ***")
                        else:
                            out.append(_fmt_fire(ev))
                    if session.enc.phase in (Phase.COMBAT_SMALL, Phase.MOVE_SUBMISSION, Phase.COMPLETE):
                        if session.enc.phase == Phase.COMPLETE:
                            phase_label = "battle complete"
                        elif session.enc.phase == Phase.COMBAT_SMALL:
                            phase_label = "COMBAT_SMALL"
                        else:
                            phase_label = "next turn"
                            session.turn_number += 1
                            append_turn_snapshot(
                                session.game_id, session.turn_number, session.enc, session.rng
                            )
                        out.append(f"→ Fire resolved. Entering {phase_label}.")
                        break
                append_turn_events(
                    session.game_id, session.turn_number, "combat_submission", all_fire_events
                )
                _autosave(session)

            elif sub == "squadrons":
                if session.enc.phase != Phase.COMBAT_SMALL:
                    out.append(f"Not in combat_small phase (current: {session.enc.phase.value})")
                    return out
                sides_to_commit = (
                    [parts[2]] if len(parts) >= 3
                    else sorted(session.enc.sides() - session.enc._squadron_committed)
                )
                from tactical.events import BattleEndEvent, FuelWarningEvent, UnitDestroyedEvent
                from tactical.fighter_events import AttackRunEvent, BreakOffEvent, DogfightEvent
                all_sq_events = []
                for s in sides_to_commit:
                    session.enc, events = session.enc.commit_squadron_orders(s, session.rng)
                    all_sq_events.extend(events)
                    out.append(f"Side {s!r} committed squadron orders.")
                    for ev in events:
                        if isinstance(ev, DogfightEvent):
                            out.extend(_fmt_dogfight(ev))
                        elif isinstance(ev, AttackRunEvent):
                            out.extend(_fmt_attack_run(ev))
                        elif isinstance(ev, BreakOffEvent):
                            parting = ", ".join(
                                f"{p.attacker_id} cas={p.total_casualties}"
                                for p in ev.parting_shots
                            ) or "none"
                            out.append(
                                f"  BREAK OFF {ev.squadron_id}"
                                f" → ({ev.final_pos.q},{ev.final_pos.r})"
                                f"  parting=[{parting}]  cas={ev.casualties_taken}"
                            )
                        elif isinstance(ev, UnitDestroyedEvent):
                            out.append(f"  *** {ev.unit_id} DESTROYED ({ev.cause.value}) ***")
                        elif isinstance(ev, FuelWarningEvent):
                            out.append(f"  WARNING: {ev.squadron_id} is out of fuel")
                        elif isinstance(ev, BattleEndEvent):
                            msg = "MUTUAL DESTRUCTION (draw)" if ev.is_draw else f"{ev.winner} WINS"
                            out.append(f"  *** BATTLE OVER — {msg} ***")
                    if session.enc.phase in (Phase.MOVE_SUBMISSION, Phase.COMPLETE):
                        label = "battle complete" if session.enc.phase == Phase.COMPLETE else "next turn"
                        if session.enc.phase == Phase.MOVE_SUBMISSION:
                            session.turn_number += 1
                            append_turn_snapshot(
                                session.game_id, session.turn_number, session.enc, session.rng
                            )
                        out.append(f"→ Fighter phase resolved. {label.capitalize()}.")
                        break
                append_turn_events(
                    session.game_id, session.turn_number, "combat_small", all_sq_events
                )
                _autosave(session)

            else:
                out.append("usage: commit move [side_id]  |  commit fire [side_id]  |  commit squadrons [side_id]")

        elif cmd == "launch":
            if len(parts) != 3:
                out.append("usage: launch <carrier_id> <squadron_id>"); return out
            squadron_id = parts[2]
            try:
                carrier_id = _resolve_ship_id(session, parts[1])
            except KeyError:
                out.append(f"unknown ship: {parts[1]!r}"); return out
            from tactical.encounter import Phase
            if session.enc.phase != Phase.MOVE_SUBMISSION:
                out.append(f"Cannot launch: phase is {session.enc.phase.value!r}"); return out
            side = session.enc.battle.ships[carrier_id].owner_id
            session.enc = session.enc.stage_launch(side, carrier_id, squadron_id)
            out.append(f"Staged: {carrier_id} will launch {squadron_id}")

        # ---------------------------------------------------------------- #
        # Combat submission                                                  #
        # ---------------------------------------------------------------- #

        elif cmd == "fireall":
            if len(parts) != 3:
                out.append("usage: fireall <ship_id> <target_id>"); return out
            try:
                ship_id   = _resolve_ship_id(session, parts[1])
                target_id = _resolve_ship_id(session, parts[2])
            except KeyError as e:
                out.append(f"unknown ship: {e}"); return out
            side = session.enc.battle.ships[ship_id].owner_id
            session.enc = session.enc.stage_fire(side, ship_id, target_id)
            out.append(f"Staged: {ship_id} fires all weapons at {target_id}")

        elif cmd == "pass":
            if len(parts) != 2:
                out.append("usage: pass <ship_id>"); return out
            try:
                ship_id = _resolve_ship_id(session, parts[1])
            except KeyError:
                out.append(f"unknown ship: {parts[1]!r}"); return out
            side = session.enc.battle.ships[ship_id].owner_id
            session.enc = session.enc.pass_fire(side, ship_id)
            out.append(f"Staged: {ship_id} passes fire")

        # ---------------------------------------------------------------- #
        # COMBAT_SMALL — fighter orders                                      #
        # ---------------------------------------------------------------- #

        elif cmd == "intercept":
            if len(parts) not in (4, 5):
                out.append("usage: intercept <squad_id> <q> <r> [max_radius]"); return out
            sq_id = parts[1]
            if sq_id not in session.enc.battle.squadrons:
                out.append(f"unknown squadron: {sq_id!r}"); return out
            from tactical.encounter import Phase
            if session.enc.phase != Phase.COMBAT_SMALL:
                out.append(f"Cannot order: phase is {session.enc.phase.value!r}"); return out
            from sim.hexgrid import Hex
            from tactical.turn_orders import InterceptOrder
            patrol = Hex(int(parts[2]), int(parts[3]))
            max_radius = int(parts[4]) if len(parts) == 5 else None
            side = session.enc.battle.squadrons[sq_id].owner_id
            session.enc = session.enc.stage_squadron_order(
                side, sq_id, InterceptOrder(patrol_hex=patrol, max_intercept_radius=max_radius)
            )
            radius_str = f" max_radius={max_radius}" if max_radius is not None else ""
            out.append(f"Staged: {sq_id} INTERCEPT at ({patrol.q},{patrol.r}){radius_str}")

        elif cmd == "fmove":
            if len(parts) != 4:
                out.append("usage: fmove <squad_id> <q> <r>"); return out
            sq_id = parts[1]
            if sq_id not in session.enc.battle.squadrons:
                out.append(f"unknown squadron: {sq_id!r}"); return out
            from tactical.encounter import Phase
            if session.enc.phase != Phase.COMBAT_SMALL:
                out.append(f"Cannot order: phase is {session.enc.phase.value!r}"); return out
            from sim.hexgrid import Hex
            from tactical.turn_orders import MoveOrder
            dest = Hex(int(parts[2]), int(parts[3]))
            side = session.enc.battle.squadrons[sq_id].owner_id
            session.enc = session.enc.stage_squadron_order(side, sq_id, MoveOrder(dest=dest))
            out.append(f"Staged: {sq_id} MOVE → ({dest.q},{dest.r})")

        elif cmd == "recover":
            if len(parts) != 3:
                out.append("usage: recover <squad_id> <carrier_id>"); return out
            sq_id = parts[1]
            if sq_id not in session.enc.battle.squadrons:
                out.append(f"unknown squadron: {sq_id!r}"); return out
            from tactical.encounter import Phase
            if session.enc.phase != Phase.COMBAT_SMALL:
                out.append(f"Cannot order: phase is {session.enc.phase.value!r}"); return out
            try:
                carrier_id = _resolve_ship_id(session, parts[2])
            except KeyError:
                out.append(f"unknown ship: {parts[2]!r}"); return out
            from tactical.turn_orders import RecoverOrder
            side = session.enc.battle.squadrons[sq_id].owner_id
            session.enc = session.enc.stage_squadron_order(side, sq_id, RecoverOrder(carrier_id=carrier_id))
            out.append(f"Staged: {sq_id} RECOVER → {carrier_id}")

        elif cmd == "breakoff":
            if len(parts) != 4:
                out.append("usage: breakoff <squad_id> <q> <r>"); return out
            sq_id = parts[1]
            if sq_id not in session.enc.battle.squadrons:
                out.append(f"unknown squadron: {sq_id!r}"); return out
            from tactical.encounter import Phase
            if session.enc.phase != Phase.COMBAT_SMALL:
                out.append(f"Cannot order: phase is {session.enc.phase.value!r}"); return out
            from sim.hexgrid import Hex
            from tactical.turn_orders import BreakOffOrder
            dest = Hex(int(parts[2]), int(parts[3]))
            side = session.enc.battle.squadrons[sq_id].owner_id
            session.enc = session.enc.stage_squadron_order(side, sq_id, BreakOffOrder(dest=dest))
            out.append(f"Staged: {sq_id} BREAK OFF → ({dest.q},{dest.r})")

        elif cmd == "strike":
            if len(parts) != 3:
                out.append("usage: strike <squad_id> <target_id>"); return out
            sq_id = parts[1]
            if sq_id not in session.enc.battle.squadrons:
                out.append(f"unknown squadron: {sq_id!r}"); return out
            from tactical.encounter import Phase
            if session.enc.phase != Phase.COMBAT_SMALL:
                out.append(f"Cannot order: phase is {session.enc.phase.value!r}"); return out
            try:
                target_id = _resolve_unit_id(session, parts[2])
            except KeyError:
                out.append(f"unknown unit: {parts[2]!r}"); return out
            from tactical.turn_orders import StrikeOrder
            side = session.enc.battle.squadrons[sq_id].owner_id
            session.enc = session.enc.stage_squadron_order(side, sq_id, StrikeOrder(target_id=target_id))
            out.append(f"Staged: {sq_id} STRIKE → {target_id}")

        # ---------------------------------------------------------------- #
        # Debug / quick fire                                                 #
        # ---------------------------------------------------------------- #

        elif cmd == "quickfire":
            if len(parts) != 3:
                out.append("usage: quickfire <attacker_id> <target_id>"); return out
            try:
                attacker_id = _resolve_ship_id(session, parts[1])
                target_id   = _resolve_ship_id(session, parts[2])
            except KeyError as e:
                out.append(f"unknown ship: {e}"); return out
            from tactical.combat import resolve_fire_all
            new_battle, events = resolve_fire_all(
                session.enc.battle, attacker_id=attacker_id, target_id=target_id, rng=session.rng)
            session.enc = replace(session.enc, battle=new_battle)
            out += [_fmt_fire(ev) for ev in events] or [f"{attacker_id} has no active weapons."]

        elif cmd == "shoot":
            if len(parts) != 4:
                out.append("usage: shoot <attacker_id> <target_id> <weapon_code>"); return out
            try:
                attacker_id = _resolve_ship_id(session, parts[1])
                target_id   = _resolve_ship_id(session, parts[2])
            except KeyError as e:
                out.append(f"unknown ship: {e}"); return out
            wcode = parts[3].upper()
            from tactical.combat import resolve_large_fire
            from tactical.weapons import WeaponType
            try:
                weapon = WeaponType(wcode)
            except Exception:
                out.append(f"unknown weapon_code: {wcode!r}"); return out
            new_battle, ev = resolve_large_fire(
                session.enc.battle, attacker_id=attacker_id, target_id=target_id,
                weapon=weapon, rng=session.rng)
            session.enc = replace(session.enc, battle=new_battle)
            out.append(_fmt_fire(ev))

        else:
            out.append(f"unknown command: {cmd!r}")
            out.append("move/tl/tr/spend  commit move  fireall/pass  commit fire  quickfire/shoot")

    except Exception as e:
        out.append(f"ERROR: {e}")

    return out


# ---------------------------------------------------------------------------
# State rendering helpers
# ---------------------------------------------------------------------------

def _render_units(session: GameSession, view: str = "master") -> str:
    import re
    from tactical.sensor_rules import major_status_flags
    enc = session.enc
    lines = []
    for sid in enc.battle.ship_ids_sorted():
        ship = enc.battle.ships[sid]
        if ship.systems is not None and ship.systems.is_destroyed():
            continue

        det = _detection_level(sid, ship.owner_id, view, enc)

        if det == 0:
            continue
        elif det == 1:
            m = re.search(r'\d+$', sid)
            num_str = m.group() if m else ""
            flags = major_status_flags(ship)
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            lines.append(f"  {ship.owner_id}??{num_str}  pos=({ship.pos.q:+},{ship.pos.r:+}){flag_str}")
        elif det == 2:
            revealed = enc._revealed_systems.get(sid, frozenset())
            track = "".join(
                sys.token if i in revealed else "?"
                for i, sys in enumerate(ship.systems)
            ) if ship.systems else ""
            hull_class = ship.hull_type.designation if ship.hull_type else "??"
            lines.append(
                f"  {sid}  pos=({ship.pos.q:+},{ship.pos.r:+})"
                f"  class={hull_class}  systems=[{track}]"
            )
        else:
            lines.append(
                f"{sid:>8}  pos=({ship.pos.q:+},{ship.pos.r:+})"
                f"  face={int(ship.facing)}  mp={ship.mp}"
                f"\n      systems=[{ship.systems.render_compact() if ship.systems else '-'}]"
            )
    for sqid in enc.battle.squadron_ids_sorted():
        sq = enc.battle.squadrons[sqid]
        if not sq.is_deployed:
            continue
        det = _detection_level(sqid, sq.owner_id, view, enc)
        if det == 0:
            continue
        elif det == 1:
            lines.append(f"   ?  pos=({sq.pos.q:+},{sq.pos.r:+})")
        elif det == 2:
            lines.append(
                f"   ?  pos=({sq.pos.q:+},{sq.pos.r:+})"
                f"  str={sq.strength}/{sq.max_strength}"
            )
        else:
            internal = "".join(w.value for w in sq.loadout.internal)
            external = "".join(w.value for w in sq.loadout.external)
            loadout  = internal + (f"[{external}×{sq.loadout.external_shots_remaining}]" if external else "")
            lines.append(
                f"{sqid:>4}  owner={sq.owner_id}  pos=({sq.pos.q:+},{sq.pos.r:+})"
                f"  str={sq.strength}/{sq.max_strength}"
                f"  mvr={sq.effective_mvr}  mp={sq.effective_mp}"
                f"  fuel={sq.endurance}/{sq.max_endurance}"
                f"  load={loadout}"
            )
    return "\n".join(lines)


def _render_phase(session: GameSession) -> str:
    from tactical.encounter import Phase
    enc = session.enc
    phase = enc.phase.value.upper()
    if enc.phase == Phase.MOVE_SUBMISSION:
        committed = sorted(enc._move_committed)
        return f"Turn {session.turn_number}  {phase}  committed={committed}"
    if enc.phase == Phase.COMBAT_SUBMISSION:
        committed = sorted(enc._fire_committed)
        return f"Turn {session.turn_number}  {phase}  committed={committed}"
    return f"Turn {session.turn_number}  {phase}"


# ---------------------------------------------------------------------------
# JSON rendering helpers
# ---------------------------------------------------------------------------

def _ships_json(session: GameSession, view: str = "master") -> str:
    import re
    from tactical.sensor_rules import major_status_flags
    enc = session.enc
    result = []
    for sid, s in enc.battle.ships.items():
        is_destroyed = bool(s.systems is not None and s.systems.is_destroyed())
        det = _detection_level(sid, s.owner_id, view, enc)

        if det == 0:
            continue
        elif det == 1:
            m = re.search(r'\d+$', sid)
            num_str = m.group() if m else ""
            result.append({
                "id": s.owner_id + "??" + num_str,
                "owner": s.owner_id,
                "q": s.pos.q,
                "r": s.pos.r,
                "is_destroyed": is_destroyed,
                "detection": 1,
                "major_status": major_status_flags(s),
            })
        elif det == 2:
            revealed = enc._revealed_systems.get(sid, frozenset())
            sys_list = [
                sys.token if i in revealed else "?"
                for i, sys in enumerate(s.systems)
            ] if s.systems else []
            result.append({
                "id": sid,
                "owner": s.owner_id,
                "q": s.pos.q,
                "r": s.pos.r,
                "facing": int(s.facing),
                "systems": sys_list,
                "is_destroyed": is_destroyed,
                "detection": 2,
            })
        else:
            result.append({
                "id": sid,
                "owner": s.owner_id,
                "q": s.pos.q,
                "r": s.pos.r,
                "facing": int(s.facing),
                "is_destroyed": is_destroyed,
                "detection": 3,
            })
    return json.dumps(result)


def _squadrons_json(session: GameSession, view: str = "master") -> str:
    enc = session.enc
    result = []
    for sqid, sq in enc.battle.squadrons.items():
        if not sq.is_deployed:
            continue
        det = _detection_level(sqid, sq.owner_id, view, enc)
        num = sqid[len(sq.owner_id):]

        if det == 0:
            continue
        elif det == 1:
            result.append({
                "id": sq.owner_id + "??" + num,
                "owner": sq.owner_id,
                "q": sq.pos.q,
                "r": sq.pos.r,
                "detection": 1,
            })
        elif det == 2:
            result.append({
                "id": sqid,
                "owner": sq.owner_id,
                "q": sq.pos.q,
                "r": sq.pos.r,
                "strength": sq.strength,
                "max": sq.max_strength,
                "detection": 2,
            })
        else:
            result.append({
                "id": sqid,
                "owner": sq.owner_id,
                "q": sq.pos.q,
                "r": sq.pos.r,
                "strength": sq.strength,
                "max": sq.max_strength,
                "detection": 3,
            })
    return json.dumps(result)


def _paths_json(session: GameSession) -> str:
    enc = session.enc
    paths = []
    for ship_id, d in session.drafts.items():
        if ship_id not in enc.battle.ships:
            continue
        ship = enc.battle.ships[ship_id]
        paths.append({
            "shipId":      ship_id,
            "owner":       ship.owner_id,
            "hexes":       [{"q": h.q, "r": h.r} for h in d["path"]],
            "finalFacing": d["facing"],
        })
    return json.dumps(paths)


def _iter_intercept_orders(session: GameSession):
    from tactical.turn_orders import InterceptOrder
    enc = session.enc
    for sq_id, order in enc._squadron_orders.items():
        if not isinstance(order, InterceptOrder):
            continue
        sq = enc.battle.squadrons.get(sq_id)
        if sq is None:
            continue
        yield sq_id, sq, order


def _intercept_paths_json(session: GameSession) -> str:
    paths = []
    for _sq_id, sq, order in _iter_intercept_orders(session):
        if sq.pos == order.patrol_hex:
            continue
        paths.append({
            "owner": sq.owner_id,
            "hexes": [
                {"q": sq.pos.q, "r": sq.pos.r},
                {"q": order.patrol_hex.q, "r": order.patrol_hex.r},
            ],
        })
    return json.dumps(paths)


def _intercept_zones_json(session: GameSession) -> str:
    from sim.hexgrid import hex_distance
    zones = []
    for _sq_id, sq, order in _iter_intercept_orders(session):
        dist   = hex_distance(sq.pos, order.patrol_hex)
        radius = max(0, sq.effective_mp - dist + 1)
        if order.max_intercept_radius is not None:
            radius = min(radius, order.max_intercept_radius)
        zones.append({
            "owner":  sq.owner_id,
            "q":      order.patrol_hex.q,
            "r":      order.patrol_hex.r,
            "radius": radius,
        })
    return json.dumps(zones)


def _recover_paths_json(session: GameSession) -> str:
    from tactical.encounter import Phase
    from tactical.turn_orders import RecoverOrder
    enc = session.enc
    if enc.phase != Phase.COMBAT_SMALL:
        return json.dumps([])
    paths = []
    for sq_id, order in enc._squadron_orders.items():
        if not isinstance(order, RecoverOrder):
            continue
        sq = enc.battle.squadrons.get(sq_id)
        carrier = enc.battle.ships.get(order.carrier_id)
        if sq is None or carrier is None:
            continue
        paths.append({
            "owner": sq.owner_id,
            "hexes": [
                {"q": sq.pos.q, "r": sq.pos.r},
                {"q": carrier.pos.q, "r": carrier.pos.r},
            ],
        })
    return json.dumps(paths)


def _strike_orders_json(session: GameSession) -> str:
    from tactical.encounter import Phase
    from tactical.turn_orders import StrikeOrder
    enc = session.enc
    if enc.phase != Phase.COMBAT_SMALL:
        return json.dumps([])
    orders = []
    for sq_id, order in enc._squadron_orders.items():
        if not isinstance(order, StrikeOrder):
            continue
        attacker = enc.battle.squadrons.get(sq_id)
        if attacker is None:
            continue
        if order.target_id in enc.battle.ships:
            target_pos = enc.battle.ships[order.target_id].pos
        elif order.target_id in enc.battle.squadrons:
            target_pos = enc.battle.squadrons[order.target_id].pos
        else:
            continue
        orders.append({
            "attacker_owner": attacker.owner_id,
            "aq": attacker.pos.q, "ar": attacker.pos.r,
            "tq": target_pos.q,  "tr": target_pos.r,
        })
    return json.dumps(orders)


def _fire_orders_json(session: GameSession) -> str:
    from tactical.encounter import Phase
    enc = session.enc
    if enc.phase != Phase.COMBAT_SUBMISSION:
        return json.dumps([])
    orders = []
    for ship_id, order in enc._fire_orders.items():
        if order is None:
            continue
        attacker = enc.battle.ships.get(ship_id)
        target   = enc.battle.ships.get(order.target_id)
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


def _game_template_context(request: Request, session: GameSession, view: str) -> dict:
    enc = session.enc
    return {
        "request":              request,
        "game_id":              session.game_id,
        "game_name":            session.name,
        "phase":                _render_phase(session),
        "phase_name":           enc.phase.value,
        "sides":                sorted(enc.sides()),
        "units_text":           _render_units(session, view),
        "ships_json":           _ships_json(session, view),
        "squadrons_json":       _squadrons_json(session, view),
        "paths_json":           _paths_json(session),
        "fire_orders_json":     _fire_orders_json(session),
        "strike_orders_json":   _strike_orders_json(session),
        "intercept_paths_json": _intercept_paths_json(session),
        "intercept_zones_json": _intercept_zones_json(session),
        "recover_paths_json":   _recover_paths_json(session),
        "log":                  "\n".join(session.log[-40:]),
        "view":                 view,
    }


# ---------------------------------------------------------------------------
# Routes — lobby
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def lobby(request: Request):
    games = list_games()
    return templates.TemplateResponse("lobby.html", {
        "request": request,
        "games":   games,
    })


@router.post("/new")
async def new_game(name: str = Form(...)):
    session = _new_game(name.strip() or "Unnamed game")
    return RedirectResponse(url=f"/tactical/game/{session.game_id}/", status_code=303)


# ---------------------------------------------------------------------------
# Routes — scenario builder
# ---------------------------------------------------------------------------

@router.get("/scenario/new", response_class=HTMLResponse)
async def scenario_builder(request: Request):
    designs = list_designs()
    for d in designs:
        bh_slots = [
            slot for slot in d.get("track", [])
            if isinstance(slot, dict)
            and slot.get("type") == "system"
            and slot.get("code") == "Bh"
        ]
        d["bh_count"]  = len(bh_slots)
        d["bh_squads"] = [
            (slot.get("squadron") or {}).get("internal") or ""
            for slot in bh_slots
        ]
    return templates.TemplateResponse("scenario_builder.html", {
        "request":   request,
        "designs":   designs,
        "hull_mods": HULL_MODS,
    })


@router.post("/scenario/launch")
async def scenario_launch(
    request: Request,
    game_name:       str = Form(default=""),
    seed:            str = Form(default=""),
    distance:        int = Form(default=30),
    side_a_ids:      str = Form(default=""),
    side_b_ids:      str = Form(default=""),
    side_a_ordnance: str = Form(default="[]"),
    side_b_ordnance: str = Form(default="[]"),
):
    from tactical.encounter import Encounter
    from tactical.fleet_arrangement import arrange_fleets
    from tactical.persistence import load_design

    # Parse comma-separated design ID lists (may have duplicates)
    def _parse_ids(raw: str) -> list[str]:
        return [x.strip() for x in raw.split(",") if x.strip()]

    a_ids = _parse_ids(side_a_ids)
    b_ids = _parse_ids(side_b_ids)

    if not a_ids or not b_ids:
        return RedirectResponse(url="/tactical/scenario/new", status_code=303)

    try:
        a_ord: list = json.loads(side_a_ordnance)
    except Exception:
        a_ord = []
    try:
        b_ord: list = json.loads(side_b_ordnance)
    except Exception:
        b_ord = []

    a_designs = [load_design(did) for did in a_ids]
    b_designs = [load_design(did) for did in b_ids]

    # Attach per-bay ordnance selections (ordered, matching the IDs list)
    for i, d in enumerate(a_designs):
        if d is not None:
            d["bh_ordnance"] = a_ord[i] if i < len(a_ord) else []
    for i, d in enumerate(b_designs):
        if d is not None:
            d["bh_ordnance"] = b_ord[i] if i < len(b_ord) else []

    seed_int = int(seed.strip()) if seed.strip().isdigit() else None
    distance  = max(5, min(100, distance))

    battle, rng, seed_used = arrange_fleets(a_designs, b_designs, distance, seed_int)

    game_id   = str(uuid.uuid4())
    name      = (game_name.strip() or "Unnamed game") + f"  [seed:{seed_used}]"
    enc       = Encounter.start(battle, rng=rng)
    session   = GameSession(game_id=game_id, name=name, enc=enc, rng=rng,
                            log=[], turn_number=1)
    _sessions[game_id] = session
    save_game(game_id=game_id, name=name, enc=enc, rng=rng,
              log=[], turn_number=1)
    return RedirectResponse(url=f"/tactical/game/{game_id}/", status_code=303)


# ---------------------------------------------------------------------------
# Routes — per-game
# ---------------------------------------------------------------------------

@router.get("/game/{game_id}/", response_class=HTMLResponse)
async def game_view(request: Request, game_id: str, view: str = "master"):
    try:
        session = _get_session(game_id)
    except KeyError:
        return HTMLResponse(f"Game {game_id!r} not found.", status_code=404)
    return templates.TemplateResponse(
        "tactical.html",
        _game_template_context(request, session, view),
    )


@router.post("/game/{game_id}/command")
async def game_command(request: Request, game_id: str, cmd: str = Form(default="")):
    try:
        session = _get_session(game_id)
    except KeyError:
        return HTMLResponse(f"Game {game_id!r} not found.", status_code=404)
    view = request.query_params.get("view", "master")
    cmd = cmd.strip()
    if not cmd:
        return RedirectResponse(url=f"/tactical/game/{game_id}/?view={view}", status_code=303)
    session.log.append(f"> {cmd}")
    output = _process(session, cmd)
    session.log.extend(output)
    if len(session.log) > _MAX_LOG:
        session.log = session.log[-_MAX_LOG:]
    return RedirectResponse(url=f"/tactical/game/{game_id}/?view={view}", status_code=303)


@router.post("/game/{game_id}/ai_turn/{side_id}")
async def game_ai_turn(request: Request, game_id: str, side_id: str):
    """Stage AI orders for side_id in the current phase, then redirect back."""
    try:
        session = _get_session(game_id)
    except KeyError:
        return HTMLResponse(f"Game {game_id!r} not found.", status_code=404)
    view = request.query_params.get("view", "master")

    from tactical.encounter import Phase
    from tactical.ai import DEFAULT, make_fire_orders, make_move_orders, make_squadron_orders

    enc = session.enc
    new_log: list[str] = []

    if enc.phase == Phase.MOVE_SUBMISSION:
        session.enc = make_move_orders(enc, side_id, DEFAULT, session.rng)
        # Mirror staged move orders into session.drafts so ghost paths render.
        facing_names = ["N", "NE", "SE", "S", "SW", "NW"]
        for ship_id, order in session.enc._move_orders.items():
            ship = session.enc.battle.ships.get(ship_id)
            if ship is None or ship.owner_id != side_id:
                continue
            cap = session.enc._mp_capacity.get(ship_id, ship.mp)
            path = order.path if order.path else (ship.pos, order.dest)
            session.drafts[ship_id] = {
                "pos":          order.dest,
                "facing":       int(order.dest_facing),
                "mp_remaining": cap - order.total_mp_cost,
                "turn_charge":  order.final_turn_charge,
                "turn_cost":    ship.turn_cost,
                "path":         list(path),
                "mp_used":      order.total_mp_cost,
            }
            new_log.append(
                f"[AI] {ship_id}: move → ({order.dest.q},{order.dest.r}) "
                f"facing={facing_names[int(order.dest_facing)]} cost={order.total_mp_cost}"
            )
    elif enc.phase == Phase.COMBAT_SUBMISSION:
        session.enc = make_fire_orders(enc, side_id, DEFAULT, session.rng)
        for ship_id, order in session.enc._fire_orders.items():
            ship = session.enc.battle.ships.get(ship_id)
            if ship is None or ship.owner_id != side_id:
                continue
            if order is None:
                new_log.append(f"[AI] {ship_id}: pass fire")
            else:
                new_log.append(f"[AI] {ship_id}: fire → {order.target_id}")
    elif enc.phase == Phase.COMBAT_SMALL:
        session.enc = make_squadron_orders(enc, side_id, DEFAULT, session.rng)
        new_log.append(f"[AI] {side_id}: staged squadron orders")
    else:
        new_log.append(f"[AI] {side_id}: no orders for phase {enc.phase.value}")

    session.log.extend(new_log)
    if len(session.log) > _MAX_LOG:
        session.log = session.log[-_MAX_LOG:]
    return RedirectResponse(url=f"/tactical/game/{game_id}/?view={view}", status_code=303)


@router.post("/game/{game_id}/commit_phase")
async def game_commit_phase(request: Request, game_id: str):
    """Commit the current phase for all uncommitted sides, then redirect back."""
    try:
        session = _get_session(game_id)
    except KeyError:
        return HTMLResponse(f"Game {game_id!r} not found.", status_code=404)
    view = request.query_params.get("view", "master")

    from tactical.encounter import Phase
    phase_to_cmd = {
        Phase.MOVE_SUBMISSION:   "commit move",
        Phase.COMBAT_SUBMISSION: "commit fire",
        Phase.COMBAT_SMALL:      "commit squadrons",
    }
    cmd = phase_to_cmd.get(session.enc.phase)
    if cmd:
        session.log.append(f"> {cmd}")
        output = _process(session, cmd)
        session.log.extend(output)
        if len(session.log) > _MAX_LOG:
            session.log = session.log[-_MAX_LOG:]

    return RedirectResponse(url=f"/tactical/game/{game_id}/?view={view}", status_code=303)


@router.post("/game/{game_id}/delete")
async def game_delete(game_id: str):
    _sessions.pop(game_id, None)
    _db_delete(game_id)
    return RedirectResponse(url="/tactical/", status_code=303)


# ---------------------------------------------------------------------------
# Ship designer
# ---------------------------------------------------------------------------

# Hull modifier definitions — add future mods here.
HULL_MODS = [
    {
        "key":             "carrier",
        "label":           "Carrier",
        "designation_suffix": "-V",
        "cost_multiplier": 1.25,
        "requires_systems": ["Bh", "Bl"],   # systems that require this mod
        "description":     "Allows Hangar Bays (Bh) and Launch Bays (Bl). +25% hull cost.",
    },
]

@router.get("/designs/", response_class=HTMLResponse)
async def designer_index(request: Request):
    designs = list_designs()
    hulls   = HULL_CATALOG
    systems = SYSTEMS
    return templates.TemplateResponse("ship_designer.html", {
        "request":   request,
        "designs":   designs,
        "hull_mods": HULL_MODS,
        "hulls":     [{"designation": h.designation, "name": h.name,
                       "hs_min": h.hs_min, "hs_max": h.hs_max,
                       "cost_per_hs": h.cost_per_hs, "epr_i": h.epr_i,
                       "ia": h.ia, "req_el": h.req_el,
                       "req_min_speed": h.req_min_speed,
                       "max_speed": h.max_speed, "turn_cost": h.turn_cost,
                       "engines_per_room": hull_engines_per_room(h)}
                      for h in hulls],
        "systems":   [{"code": s.code, "name": s.name,
                       "cost": s.cost, "hull_spaces": s.hull_spaces,
                       "ls_capacity": s.ls_capacity}
                      for s in systems],
    })


@router.get("/designs/{design_id}/edit", response_class=HTMLResponse)
async def designer_edit(request: Request, design_id: str):
    try:
        design = load_design(design_id)
    except KeyError:
        return RedirectResponse(url="/tactical/designs/", status_code=303)

    designs = list_designs()
    hulls   = HULL_CATALOG
    systems = SYSTEMS
    return templates.TemplateResponse("ship_designer.html", {
        "request":       request,
        "designs":       designs,
        "hulls":         [{"designation": h.designation, "name": h.name,
                           "hs_min": h.hs_min, "hs_max": h.hs_max,
                           "cost_per_hs": h.cost_per_hs, "epr_i": h.epr_i,
                           "ia": h.ia, "req_el": h.req_el,
                           "req_min_speed": h.req_min_speed,
                           "max_speed": h.max_speed, "turn_cost": h.turn_cost,
                           "engines_per_room": hull_engines_per_room(h)}
                          for h in hulls],
        "hull_mods":     HULL_MODS,
        "systems":       [{"code": s.code, "name": s.name,
                           "cost": s.cost, "hull_spaces": s.hull_spaces,
                           "ls_capacity": s.ls_capacity}
                          for s in systems],
        "edit_design":   design,
    })


@router.post("/designs/save")
async def designer_save(
    design_id:    str  = Form(default=""),
    name:         str  = Form(...),
    hull_type:    str  = Form(...),
    hull_spaces:  int  = Form(...),
    track_json:   str  = Form(...),
    hull_mods_json: str = Form(default="[]"),
):
    did = design_id.strip() or str(uuid.uuid4())
    try:
        track = json.loads(track_json)
    except Exception:
        track = []
    try:
        hull_mods = json.loads(hull_mods_json)
    except Exception:
        hull_mods = []
    save_design(did, name.strip() or "Unnamed", hull_type, hull_spaces, track, hull_mods)
    return RedirectResponse(url=f"/tactical/designs/{did}/edit", status_code=303)


@router.post("/designs/{design_id}/delete")
async def designer_delete(design_id: str):
    _db_delete_design(design_id)
    return RedirectResponse(url="/tactical/designs/", status_code=303)
