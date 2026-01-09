from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import db
from sim.hexgrid import Hex
from sim.persistence import game_from_json, game_to_json
from sim.render_ascii import render_map_ascii

# Reuse your existing default scenario to start new games.
# (main.py already imports this, so it should be stable in your repo.)
from scenarios.simple_scenario import build_game


app = FastAPI(title="Async 4X Sim (MVP)")
templates = Jinja2Templates(directory="templates")


def _load_game(game_id: str):
    s = db.get_game_json(game_id)
    if s is None:
        raise HTTPException(status_code=404, detail="No such game")
    return game_from_json(s)


def _save_game(game_id: str, game) -> None:
    db.save_game_json(game_id, game_to_json(game))


def _tail(lines: list[str], n: int = 50) -> list[str]:
    if n <= 0:
        return []
    return lines[-n:]


def _apply_command(game_id: str, game, viewer: str, command: str) -> list[str]:
    """
    Minimal command surface for MVP UI.
    Reuses GameState methods; supports both queued-actions and manual-actions variants.
    """
    cmd = command.strip()
    if not cmd:
        return ["(no command)"]

    # Normalize viewer
    viewer = viewer.strip() or getattr(game.active_player, "name", "")
    if not viewer:
        raise HTTPException(status_code=400, detail="viewer is required")

    # Set active player if viewer matches a player name (simple MVP behavior).
    # If viewer doesn't match, we still let them view but command may fail.
    try:
        for p in game.players:
            if getattr(p, "name", None) == viewer:
                game.active_player = p
                break
    except Exception:
        pass

    parts = cmd.split()
    head = parts[0].lower()

    # Core loop commands
    if head == "submit":
        return game.submit_orders()

    if head == "pass":
        # Passing = submitting with no queued orders.
        return game.submit_orders()

    if head == "move":
        if len(parts) != 4:
            return ["Usage: move <group_id> <q> <r>"]
        gid = parts[1]
        try:
            q = int(parts[2])
            r = int(parts[3])
        except ValueError:
            return ["q and r must be integers"]
        ok, msg = game.queue_move(gid, Hex(q, r))
        return [msg] if ok else [f"ERROR: {msg}"]

    # Actions (prefer queued if available)
    if head == "colonize":
        if len(parts) != 2:
            return ["Usage: colonize <group_id>"]
        gid = parts[1]
        if hasattr(game, "queue_colonize"):
            ok, msg = game.queue_colonize(gid)
            return [msg] if ok else [f"ERROR: {msg}"]
        # fallback
        return list(game.manual_colonize(gid))

    if head == "mine":
        if len(parts) != 2:
            return ["Usage: mine <group_id>"]
        gid = parts[1]
        if hasattr(game, "queue_mine"):
            ok, msg = game.queue_mine(gid)
            return [msg] if ok else [f"ERROR: {msg}"]
        # fallback
        return list(game.manual_mine(gid))

    if head == "deliver":
        if len(parts) != 2:
            return ["Usage: deliver <group_id>"]
        gid = parts[1]
        if hasattr(game, "queue_deliver"):
            ok, msg = game.queue_deliver(gid)
            return [msg] if ok else [f"ERROR: {msg}"]
        if hasattr(game, "manual_deliver"):
            return list(game.manual_deliver(gid))
        return ["(deliver not implemented in this build)"]

    # --- Web-specific persistence helpers (SQLite snapshots) ---
    if head == "save":
        if len(parts) != 2:
            return ["Usage: save <name>"]
        name = parts[1].strip()
        if not name:
            return ["Usage: save <name>"]
        db.save_snapshot(game_id, name, game_to_json(game))
        return [f"Saved snapshot '{name}'"]

    if head == "load":
        if len(parts) != 2:
            return ["Usage: load <name>"]
        name = parts[1].strip()
        if not name:
            return ["Usage: load <name>"]
        s = db.load_snapshot(game_id, name)
        if s is None:
            return [f"ERROR: no such snapshot '{name}'"]
        loaded = game_from_json(s)
        # Replace current game state object in-place
        game.__dict__.clear()
        game.__dict__.update(loaded.__dict__)
        return [f"Loaded snapshot '{name}'"]

    if head == "list-saves":
        snaps = db.list_snapshots(game_id)
        if not snaps:
            return ["(no snapshots)"]
        return ["Snapshots: " + ", ".join(snaps)]

    return [f"Unknown command: {cmd}"]


def _ui_state(game_id: str, viewer: str) -> dict[str, Any]:
    game = _load_game(game_id)

    # Render for viewer. Current renderer takes (game, viewer_player).
    # If viewer is invalid, fall back to active_player for now.
    viewer_player = game.active_player
    for p in getattr(game, "players", []):
        if getattr(p, "name", None) == viewer:
            viewer_player = p
            break

    map_txt = render_map_ascii(game, viewer_player)
    log_tail = _tail(list(getattr(game, "log", [])), 60)

    return {
        "game_id": game_id,
        "viewer": viewer,
        "active_player": getattr(getattr(game, "active_player", None), "name", "?"),
        "turn_number": int(getattr(game, "turn_number", 1)),
        "map_text": map_txt,
        "log_tail": "\n".join(log_tail),
        "orders": [str(o) for o in game.list_orders(viewer_player) ] if hasattr(game, "list_orders") else [],
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request, game_id: Optional[str] = None, viewer: str = "A"):
    # If no game exists yet, create one and redirect to it.
    if game_id is None:
        new_id = str(uuid.uuid4())
        g = build_game()
        db.create_game(new_id, game_to_json(g))
        return RedirectResponse(url=f"/?game_id={new_id}&viewer={viewer}", status_code=302)

    state = _ui_state(game_id, viewer)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, **state, "games": db.list_game_ids()},
    )


@app.get("/games")
def list_games():
    return {"games": db.list_game_ids()}


@app.post("/games")
def create_game():
    game_id = str(uuid.uuid4())
    g = build_game()
    db.create_game(game_id, game_to_json(g))
    return {"game_id": game_id}


@app.get("/games/{game_id}/state")
def get_state(game_id: str, viewer: str = "A"):
    return _ui_state(game_id, viewer)


@app.post("/games/{game_id}/command")
def post_command(game_id: str, payload: Dict[str, Any]):
    viewer = str(payload.get("viewer", "A"))
    command = str(payload.get("command", ""))
    game = _load_game(game_id)

    out = _apply_command(game_id, game, viewer, command)
    _save_game(game_id, game)

    return {"events": out, "state": _ui_state(game_id, viewer)}


@app.post("/ui/command", response_class=HTMLResponse)
def ui_command(
    request: Request,
    game_id: str = Form(...),
    viewer: str = Form("A"),
    command: str = Form(""),
):
    game = _load_game(game_id)
    events = _apply_command(game_id, game, viewer, command)
    _save_game(game_id, game)

    # Append UI-visible events into log tail by relying on game.log updates.
    state = _ui_state(game_id, viewer)
    # For immediate feedback, we also show the returned events in the page.
    return templates.TemplateResponse(
        "index.html",
        {"request": request, **state, "games": db.list_game_ids(), "last_events": "\n".join(events)},
    )
