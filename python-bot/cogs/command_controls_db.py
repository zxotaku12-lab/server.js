# Credits: gogeta_gg
"""Persistent per-guild command enable/disable controls for Gogeta's dashboard.

The dashboard stores only explicit disabled overrides. Missing rows mean the
command is enabled. This keeps the default behaviour identical to the existing
bot while allowing an administrator to switch individual prefix/hybrid/slash
commands off from the Command Center.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "command_controls.db"
_cache: dict[tuple[int, str], bool] = {}

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def setup_database() -> None:
    with _connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS command_controls(
                guild_id INTEGER NOT NULL,
                command_name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(guild_id, command_name)
            )
        """)

def normalize(name: str) -> str:
    return " ".join(str(name or "").strip().lower().split())

def is_enabled(guild_id: int, command_name: str) -> bool:
    key = (int(guild_id), normalize(command_name))
    if key in _cache:
        return _cache[key]
    with _connect() as db:
        row = db.execute(
            "SELECT enabled FROM command_controls WHERE guild_id=? AND command_name=?",
            key,
        ).fetchone()
    enabled = True if row is None else bool(row[0])
    _cache[key] = enabled
    return enabled

def set_enabled(guild_id: int, command_name: str, enabled: bool) -> None:
    key = (int(guild_id), normalize(command_name))
    value = bool(enabled)
    with _connect() as db:
        if value:
            db.execute(
                "DELETE FROM command_controls WHERE guild_id=? AND command_name=?",
                key,
            )
        else:
            db.execute(
                "INSERT INTO command_controls(guild_id, command_name, enabled) VALUES(?,?,0) "
                "ON CONFLICT(guild_id, command_name) DO UPDATE SET enabled=0",
                key,
            )
    _cache[key] = value

def list_overrides(guild_id: int) -> dict[str, bool]:
    with _connect() as db:
        rows = db.execute(
            "SELECT command_name, enabled FROM command_controls WHERE guild_id=?",
            (int(guild_id),),
        ).fetchall()
    return {str(name): bool(enabled) for name, enabled in rows}
