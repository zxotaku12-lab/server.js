# Credits: gogeta_gg
"""Per-guild settings for the mention-reaction features.

Two independent toggles per guild:
  - dev_enabled:   reactions when the bot's dev (MENTION_REACT_USER_ID) is mentioned
  - owner_enabled: reactions when that server's owner is mentioned
"""

from pathlib import Path
import sqlite3

DB_NAME = Path(__file__).resolve().parent / "reaction.db"


def connect():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def setup_database():
    conn = connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reaction_settings (
                guild_id INTEGER PRIMARY KEY,
                dev_enabled INTEGER NOT NULL DEFAULT 1 CHECK(dev_enabled IN (0, 1)),
                owner_enabled INTEGER NOT NULL DEFAULT 1 CHECK(owner_enabled IN (0, 1))
            )
        """)

        # Migrate installs from before the dev/owner split, where the
        # table only had a single "enabled" column (the old /reaction
        # command). Their existing value is preserved as dev_enabled;
        # owner_enabled defaults to 1 (previous behavior didn't have an
        # owner reaction feature, so there's nothing to migrate for it).
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(reaction_settings)")}
        if "enabled" in existing_columns and "dev_enabled" not in existing_columns:
            conn.execute("ALTER TABLE reaction_settings RENAME COLUMN enabled TO dev_enabled")
        if "owner_enabled" not in existing_columns:
            conn.execute(
                "ALTER TABLE reaction_settings ADD COLUMN owner_enabled INTEGER NOT NULL DEFAULT 1"
            )

        conn.commit()
    finally:
        conn.close()


def is_dev_enabled(guild_id: int) -> bool:
    """New/unconfigured guilds default to enabled, preserving prior behavior."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT dev_enabled FROM reaction_settings WHERE guild_id = ?",
            (int(guild_id),),
        ).fetchone()
        return True if row is None else bool(row["dev_enabled"])
    finally:
        conn.close()


def set_dev_enabled(guild_id: int, enabled: bool) -> None:
    conn = connect()
    try:
        conn.execute("""
            INSERT INTO reaction_settings (guild_id, dev_enabled)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET dev_enabled = excluded.dev_enabled
        """, (int(guild_id), int(bool(enabled))))
        conn.commit()
    finally:
        conn.close()


def is_owner_enabled(guild_id: int) -> bool:
    """New/unconfigured guilds default to enabled."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT owner_enabled FROM reaction_settings WHERE guild_id = ?",
            (int(guild_id),),
        ).fetchone()
        return True if row is None else bool(row["owner_enabled"])
    finally:
        conn.close()


def set_owner_enabled(guild_id: int, enabled: bool) -> None:
    conn = connect()
    try:
        conn.execute("""
            INSERT INTO reaction_settings (guild_id, owner_enabled)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET owner_enabled = excluded.owner_enabled
        """, (int(guild_id), int(bool(enabled))))
        conn.commit()
    finally:
        conn.close()
