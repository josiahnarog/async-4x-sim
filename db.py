from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

DEFAULT_DB_PATH = str((Path(__file__).parent / "games.db").resolve())


def db_path() -> str:
    return os.environ.get("ASYNC4X_DB_PATH", DEFAULT_DB_PATH)


def _connect() -> sqlite3.Connection:
    # New connection per call keeps things simple and avoids threading pitfalls.
    return sqlite3.connect(db_path())


def init_db() -> None:
    with _connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                game_id TEXT NOT NULL,
                name TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (game_id, name)
            )
            """
        )
        con.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_game_ids() -> list[str]:
    init_db()
    with _connect() as con:
        rows = con.execute("SELECT id FROM games ORDER BY updated_at DESC").fetchall()
    return [r[0] for r in rows]


def create_game(game_id: str, state_json: str) -> None:
    init_db()
    with _connect() as con:
        con.execute(
            "INSERT INTO games(id, state_json, updated_at) VALUES(?,?,?)",
            (game_id, state_json, _now_iso()),
        )
        con.commit()


def get_game_json(game_id: str) -> Optional[str]:
    init_db()
    with _connect() as con:
        row = con.execute("SELECT state_json FROM games WHERE id = ?", (game_id,)).fetchone()
    return None if row is None else row[0]


def save_game_json(game_id: str, state_json: str) -> None:
    init_db()
    with _connect() as con:
        cur = con.execute(
            "UPDATE games SET state_json = ?, updated_at = ? WHERE id = ?",
            (state_json, _now_iso(), game_id),
        )
        if cur.rowcount == 0:
            # If missing, create it.
            con.execute(
                "INSERT INTO games(id, state_json, updated_at) VALUES(?,?,?)",
                (game_id, state_json, _now_iso()),
            )
        con.commit()


def save_snapshot(game_id: str, name: str, state_json: str) -> None:
    init_db()
    with _connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO snapshots(game_id, name, state_json, created_at) VALUES(?,?,?,?)",
            (game_id, name, state_json, _now_iso()),
        )
        con.commit()


def load_snapshot(game_id: str, name: str) -> Optional[str]:
    init_db()
    with _connect() as con:
        row = con.execute(
            "SELECT state_json FROM snapshots WHERE game_id = ? AND name = ?",
            (game_id, name),
        ).fetchone()
    return None if row is None else row[0]


def list_snapshots(game_id: str) -> list[str]:
    init_db()
    with _connect() as con:
        rows = con.execute(
            "SELECT name FROM snapshots WHERE game_id = ? ORDER BY created_at DESC",
            (game_id,),
        ).fetchall()
    return [r[0] for r in rows]


def delete_snapshot(game_id: str, name: str) -> bool:
    init_db()
    with _connect() as con:
        cur = con.execute(
            "DELETE FROM snapshots WHERE game_id = ? AND name = ?",
            (game_id, name),
        )
        con.commit()
        return cur.rowcount > 0


print("Using DB path:", db_path())
