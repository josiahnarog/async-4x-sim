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


def _build_default() -> tuple:
    from sim.hexgrid import Hex
    from tactical.battle_state import BattleState
    from tactical.encounter import Encounter
    from tactical.facing import Facing
    from tactical.hull_types import FG
    from tactical.ship_state import ShipState
    from tactical.ship_systems import ShipSystems

    rng = random.Random(1)
    fg = "SSSSSAAAAA(I)FFRRD(I)(I)(I)"
    a = ShipState(ship_id="A1", owner_id="A", pos=Hex(0, 0), facing=Facing.NE,
                  mp=5, turn_cost=2, turn_charge=0,
                  systems=ShipSystems.parse(fg), hull_type=FG)
    b = ShipState(ship_id="B1", owner_id="B", pos=Hex(6, 0), facing=Facing.S,
                  mp=5, turn_cost=2, turn_charge=0,
                  systems=ShipSystems.parse(fg), hull_type=FG)
    battle = BattleState(ships={"A1": a, "B1": b})
    enc = Encounter.start(battle, rng=rng, movement_subphases=3)
    return enc, rng


def _reset() -> None:
    global _enc, _rng, _log
    _enc, _rng = _build_default()
    _log = []


_reset()


# ---------------------------------------------------------------------------
# Fire event formatting (mirrors repl.py)
# ---------------------------------------------------------------------------

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
    global _enc, _rng
    out: list[str] = []
    parts = cmd_line.strip().split()
    if not parts:
        return out
    cmd = parts[0].lower()

    try:
        if cmd == "reset":
            _reset()
            out.append("Reset to default scenario.")

        elif cmd in ("move",):
            if len(parts) != 3:
                out.append("usage: move <ship_id> <steps>"); return out
            _enc = _enc.move_ship_forward(_enc.active_side(), parts[1], steps=int(parts[2]))

        elif cmd == "tl":
            if len(parts) != 2:
                out.append("usage: tl <ship_id>"); return out
            _enc = _enc.turn_ship_left(_enc.active_side(), parts[1], auto_spend=False)

        elif cmd == "tr":
            if len(parts) != 2:
                out.append("usage: tr <ship_id>"); return out
            _enc = _enc.turn_ship_right(_enc.active_side(), parts[1], auto_spend=False)

        elif cmd == "tla":
            if len(parts) != 2:
                out.append("usage: tla <ship_id>"); return out
            _enc = _enc.turn_ship_left(_enc.active_side(), parts[1], auto_spend=True)

        elif cmd == "tra":
            if len(parts) != 2:
                out.append("usage: tra <ship_id>"); return out
            _enc = _enc.turn_ship_right(_enc.active_side(), parts[1], auto_spend=True)

        elif cmd == "spend":
            if len(parts) != 3:
                out.append("usage: spend <ship_id> <mp>"); return out
            _enc = _enc.spend_mp(_enc.active_side(), parts[1], int(parts[2]))

        elif cmd == "end":
            _enc = _enc.end_side_movement(_enc.active_side())

        elif cmd == "fireall":
            if len(parts) != 3:
                out.append("usage: fireall <attacker_id> <target_id>"); return out
            attacker_id, target_id = parts[1], parts[2]
            ship = _enc.battle.ships.get(attacker_id)
            if ship is None:
                out.append(f"unknown ship: {attacker_id!r}"); return out
            if ship.owner_id != _enc.active_side():
                out.append(f"not your turn: {attacker_id!r} is side {ship.owner_id!r}, active={_enc.active_side()!r}")
                return out
            from tactical.combat import resolve_fire_all
            new_battle, events = resolve_fire_all(
                _enc.battle, attacker_id=attacker_id, target_id=target_id, rng=_rng)
            _enc = replace(_enc, battle=new_battle)
            out += [_fmt_fire(ev) for ev in events] or [f"{attacker_id} has no active weapons."]

        elif cmd == "next":
            _enc = _enc.advance_combat_turn()

        elif cmd == "pass":
            if len(parts) != 2:
                out.append("usage: pass <ship_id>"); return out
            _enc = _enc.pass_fire(_enc.active_large_combat_side(), parts[1])

        else:
            out.append(f"unknown command: {cmd!r}")

    except Exception as e:
        out.append(f"ERROR: {e}")

    return out


# ---------------------------------------------------------------------------
# State rendering helpers
# ---------------------------------------------------------------------------

def _render_ships() -> str:
    lines = []
    for sid, ship in _enc.battle.ships.items():
        lines.append(
            f"{sid:>3}  owner={ship.owner_id}  pos=({ship.pos.q:+},{ship.pos.r:+})"
            f"  face={int(ship.facing)}  mp={ship.mp}  tc={ship.turn_cost}  ch={ship.turn_charge}"
            f"\n     systems=[{ship.systems.render_compact() if ship.systems else '-'}]"
        )
    return "\n".join(lines)


def _render_phase() -> str:
    from tactical.encounter import Phase
    enc = _enc
    if enc.phase == Phase.MOVEMENT:
        return (f"MOVEMENT  subphase {enc.movement_subphase_index + 1}/{enc.movement_subphases}"
                f"  active={enc.active_side()}")
    if enc.phase == Phase.COMBAT_LARGE:
        return f"COMBAT (large)  active={enc.active_large_combat_side()}"
    return enc.phase.value.upper()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _ships_json() -> str:
    return json.dumps([
        {"id": sid, "owner": s.owner_id, "q": s.pos.q, "r": s.pos.r, "facing": int(s.facing)}
        for sid, s in _enc.battle.ships.items()
    ])


@router.get("/", response_class=HTMLResponse)
async def tactical_ui(request: Request):
    return templates.TemplateResponse("tactical.html", {
        "request": request,
        "phase": _render_phase(),
        "ships_text": _render_ships(),
        "ships_json": _ships_json(),
        "log": "\n".join(_log[-40:]),
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
