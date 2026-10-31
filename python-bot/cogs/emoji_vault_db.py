# Credits: gogeta_gg
"""Storage for the emoji vault feature.

Bot-wide, single-target config: one guild at a time is designated as the
"vault" — wherever a configured admin sends message(s) containing custom
emoji, those emoji get copied into the vault guild. There's intentionally
only one target (not per-guild), since the whole point is a single place
to collect emoji dragged in from anywhere.
"""

from pathlib import Path
import sqlite3

DB_NAME = Path(__file__).resolve().parent / "emoji_vault.db"


def connect():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def setup_database():
    conn = connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vault_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                guild_id INTEGER,
                set_by INTEGER,
                set_at INTEGER
            )
        """)
        conn.commit()
    finally:
        conn.close()


def get_vault_guild_id() -> int | None:
    conn = connect()
    try:
        row = conn.execute("SELECT guild_id FROM vault_config WHERE id = 1").fetchone()
        return row["guild_id"] if row and row["guild_id"] else None
    finally:
        conn.close()


def set_vault_guild(guild_id: int, set_by: int, set_at: int) -> None:
    conn = connect()
    try:
        conn.execute("""
            INSERT INTO vault_config (id, guild_id, set_by, set_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET guild_id = excluded.guild_id,
                                           set_by = excluded.set_by,
                                           set_at = excluded.set_at
        """, (int(guild_id), int(set_by), int(set_at)))
        conn.commit()
    finally:
        conn.close()


def clear_vault_guild() -> None:
    conn = connect()
    try:
        conn.execute("DELETE FROM vault_config WHERE id = 1")
        conn.commit()
    finally:
        conn.close()
