"""SQLite persistence for multi-game tactical sessions.

Schema:
  games       — one row per game; holds current state snapshot + log.
  turns       — one row per completed turn; holds state at start of that turn.
  turn_events — one row per event batch; holds structured event data.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tactical.serialization import (
    encode_encounter, decode_encounter,
    encode_rng, decode_rng,
    encode_events,
)

# ---------------------------------------------------------------------------
# DB location
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).parent.parent / "tactical.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Create tables if they do not exist. Call once at startup."""
    global _DB_PATH
    if db_path is not None:
        _DB_PATH = db_path

    conn = _connect()
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS games (
                game_id     TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                turn_number INTEGER NOT NULL DEFAULT 1,
                phase       TEXT NOT NULL,
                sides       TEXT NOT NULL,
                state       TEXT NOT NULL,
                log         TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS turns (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id     TEXT NOT NULL REFERENCES games(game_id),
                turn_number INTEGER NOT NULL,
                state       TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS turn_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id     TEXT NOT NULL REFERENCES games(game_id),
                turn_number INTEGER NOT NULL,
                phase       TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                event_data  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS designs (
                design_id   TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                hull_type   TEXT NOT NULL,
                hull_spaces INTEGER NOT NULL,
                track       TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
        """)
    # Migration: add hull_mods column if it doesn't exist yet
    try:
        conn.execute("ALTER TABLE designs ADD COLUMN hull_mods TEXT NOT NULL DEFAULT '[]'")
        conn.commit()
    except Exception:
        pass  # column already exists
    conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode_state(enc, rng) -> str:
    return json.dumps({
        "enc": encode_encounter(enc),
        "rng": encode_rng(rng),
    })


def _decode_state(blob: str) -> tuple:
    d = json.loads(blob)
    return decode_encounter(d["enc"]), decode_rng(d["rng"])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_games() -> list[dict]:
    """Return summary rows for all games, ordered by updated_at descending."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT game_id, name, created_at, updated_at, turn_number, phase, sides "
            "FROM games ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_game(
    game_id: str,
    name: str,
    enc,
    rng,
    log: list[str],
    turn_number: int,
) -> None:
    """Upsert the current game state.

    On the first call (new game), also inserts a turn-0 snapshot.
    Subsequent calls update the existing row.
    """
    now = _now()
    sides = json.dumps(sorted({s.owner_id for s in enc.battle.ships.values()}))
    state_blob = _encode_state(enc, rng)
    log_blob = json.dumps(log[-50:])   # keep last 50 lines
    phase = enc.phase.value

    conn = _connect()
    with conn:
        existing = conn.execute(
            "SELECT game_id FROM games WHERE game_id = ?", (game_id,)
        ).fetchone()

        if existing is None:
            conn.execute(
                "INSERT INTO games (game_id, name, created_at, updated_at, "
                "turn_number, phase, sides, state, log) VALUES (?,?,?,?,?,?,?,?,?)",
                (game_id, name, now, now, turn_number, phase, sides, state_blob, log_blob),
            )
            # Snapshot turn 1 start state.
            conn.execute(
                "INSERT INTO turns (game_id, turn_number, state, created_at) VALUES (?,?,?,?)",
                (game_id, turn_number, state_blob, now),
            )
        else:
            conn.execute(
                "UPDATE games SET name=?, updated_at=?, turn_number=?, phase=?, "
                "sides=?, state=?, log=? WHERE game_id=?",
                (name, now, turn_number, phase, sides, state_blob, log_blob, game_id),
            )
    conn.close()


def load_game(game_id: str) -> tuple:
    """Return (enc, rng, log, turn_number, name) for the given game_id.

    Raises KeyError if game not found.
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT name, state, log, turn_number FROM games WHERE game_id = ?",
            (game_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Game not found: {game_id!r}")
        enc, rng = _decode_state(row["state"])
        log = json.loads(row["log"])
        return enc, rng, log, row["turn_number"], row["name"]
    finally:
        conn.close()


def delete_game(game_id: str) -> None:
    """Delete a game and all associated turn history."""
    conn = _connect()
    with conn:
        conn.execute("DELETE FROM turn_events WHERE game_id = ?", (game_id,))
        conn.execute("DELETE FROM turns WHERE game_id = ?", (game_id,))
        conn.execute("DELETE FROM games WHERE game_id = ?", (game_id,))
    conn.close()


def append_turn_snapshot(game_id: str, turn_number: int, enc, rng) -> None:
    """Record state snapshot at the start of a new turn."""
    now = _now()
    state_blob = _encode_state(enc, rng)
    conn = _connect()
    with conn:
        conn.execute(
            "INSERT INTO turns (game_id, turn_number, state, created_at) VALUES (?,?,?,?)",
            (game_id, turn_number, state_blob, now),
        )
    conn.close()


# ---------------------------------------------------------------------------
# Ship designs
# ---------------------------------------------------------------------------

def save_design(design_id: str, name: str, hull_type: str, hull_spaces: int,
                track: list, hull_mods: list | None = None) -> None:
    """Insert or replace a ship design."""
    now = _now()
    conn = _connect()
    with conn:
        conn.execute(
            """INSERT INTO designs (design_id, name, hull_type, hull_spaces, track, hull_mods, created_at, updated_at)
               VALUES (?,?,?,?,?,?,
                       COALESCE((SELECT created_at FROM designs WHERE design_id=?), ?),
                       ?)
               ON CONFLICT(design_id) DO UPDATE SET
                   name=excluded.name, hull_type=excluded.hull_type,
                   hull_spaces=excluded.hull_spaces, track=excluded.track,
                   hull_mods=excluded.hull_mods,
                   updated_at=excluded.updated_at""",
            (design_id, name, hull_type, hull_spaces, json.dumps(track),
             json.dumps(hull_mods or []),
             design_id, now, now),
        )
    conn.close()


def load_design(design_id: str) -> dict:
    """Return design as a dict with keys: design_id, name, hull_type, hull_spaces, track, hull_mods."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM designs WHERE design_id=?", (design_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Design not found: {design_id!r}")
        return {
            "design_id":   row["design_id"],
            "name":        row["name"],
            "hull_type":   row["hull_type"],
            "hull_spaces": row["hull_spaces"],
            "track":       json.loads(row["track"]),
            "hull_mods":   json.loads(row["hull_mods"]) if row["hull_mods"] else [],
            "created_at":  row["created_at"],
            "updated_at":  row["updated_at"],
        }
    finally:
        conn.close()


def list_designs() -> list[dict]:
    """Return all saved designs as list of dicts (without full track data)."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT design_id, name, hull_type, hull_spaces, hull_mods, updated_at "
            "FROM designs ORDER BY updated_at DESC"
        ).fetchall()
        return [{**dict(r), "hull_mods": json.loads(r["hull_mods"]) if r["hull_mods"] else []}
                for r in rows]
    finally:
        conn.close()


def delete_design(design_id: str) -> None:
    conn = _connect()
    with conn:
        conn.execute("DELETE FROM designs WHERE design_id=?", (design_id,))
    conn.close()


def append_turn_events(
    game_id: str,
    turn_number: int,
    phase: str,
    events: list,
) -> None:
    """Append structured events from a resolved phase to turn_events."""
    if not events:
        return
    encoded = encode_events(events)
    conn = _connect()
    with conn:
        conn.executemany(
            "INSERT INTO turn_events (game_id, turn_number, phase, event_type, event_data) "
            "VALUES (?,?,?,?,?)",
            [
                (game_id, turn_number, phase, ev["type"], json.dumps(ev))
                for ev in encoded
            ],
        )
    conn.close()
