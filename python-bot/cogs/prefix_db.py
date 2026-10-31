# Credits: gogeta_gg
import sqlite3

DB_NAME = "prefixes.db"

DEFAULT_PREFIX = "$"

# Discord.py's command_prefix callback runs on every single message, so this
# module keeps a small in-memory cache on top of sqlite to avoid a DB round
# trip per message. The cache is populated lazily and kept in sync by
# set_prefix()/clear_prefix(), so it never needs an explicit warm-up step.
_cache: dict[int, str] = {}


def connect():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def setup_database():
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guild_prefixes (
            guild_id INTEGER PRIMARY KEY,
            prefix TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def get_prefix(guild_id: int) -> str:
    if guild_id in _cache:
        return _cache[guild_id]

    conn = connect()
    row = conn.execute(
        "SELECT prefix FROM guild_prefixes WHERE guild_id = ?", (guild_id,)
    ).fetchone()
    conn.close()

    prefix = row["prefix"] if row else DEFAULT_PREFIX
    _cache[guild_id] = prefix
    return prefix


def set_prefix(guild_id: int, prefix: str) -> None:
    conn = connect()
    conn.execute(
        """
        INSERT INTO guild_prefixes (guild_id, prefix) VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET prefix = excluded.prefix
        """,
        (guild_id, prefix),
    )
    conn.commit()
    conn.close()
    _cache[guild_id] = prefix


def clear_prefix(guild_id: int) -> None:
    conn = connect()
    conn.execute("DELETE FROM guild_prefixes WHERE guild_id = ?", (guild_id,))
    conn.commit()
    conn.close()
    _cache[guild_id] = DEFAULT_PREFIX
