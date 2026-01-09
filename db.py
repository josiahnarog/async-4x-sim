from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional


DEFAULT_DB_PATH = "games.db"


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
