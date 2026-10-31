# Credits: gogeta_gg
import sqlite3
import time

DB_NAME = "moderation.db"


def connect():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def setup_database():
    conn = connect()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            timestamp INTEGER NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS modlogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            reason TEXT,
            timestamp INTEGER NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    setup_lock_tables()


def add_warning(guild_id, user_id, moderator_id, reason):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO warnings (guild_id, user_id, moderator_id, reason, timestamp)
        VALUES (?, ?, ?, ?, ?)
        """,
        (guild_id, user_id, moderator_id, reason, int(time.time())),
    )
    conn.commit()
    warning_id = cursor.lastrowid
    conn.close()
    return warning_id


def get_warnings(guild_id, user_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM warnings
        WHERE guild_id = ? AND user_id = ?
        ORDER BY timestamp DESC
        """,
        (guild_id, user_id),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def clear_warnings(guild_id, user_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    conn.commit()
    removed = cursor.rowcount
    conn.close()
    return removed


def remove_warning(warning_id, guild_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM warnings WHERE id = ? AND guild_id = ?",
        (warning_id, guild_id),
    )
    conn.commit()
    removed = cursor.rowcount
    conn.close()
    return removed


def add_modlog(guild_id, user_id, moderator_id, action, reason=None):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO modlogs (guild_id, user_id, moderator_id, action, reason, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (guild_id, user_id, moderator_id, action, reason, int(time.time())),
    )
    conn.commit()
    conn.close()


def get_modlogs(guild_id, user_id, limit=10):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM modlogs
        WHERE guild_id = ? AND user_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (guild_id, user_id, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


# ── hierarchy lock ─────────────────────────────────────────────
# lock_settings: the per-guild cutoff role. Locking a channel denies
# send_messages to every role at or below this role's position,
# including roles that carry Administrator — Discord's admin bypass
# only applies when a role has no explicit deny on that channel, so
# writing the deny directly onto each role is what actually holds.
#
# lock_state: one row per (guild, channel, entry) touched by the most
# recent active lock on that channel, storing the PRIOR send_messages
# override (True/False/None) so /unlock can restore exactly what was
# there before, not just wipe everything to None. entry_key is either
# a numeric role ID (stored as text) or "member:<id>" for the owner's
# personal exemption overwrite.

def setup_lock_tables():
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lock_settings (
            guild_id INTEGER PRIMARY KEY,
            cutoff_role_id INTEGER NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lock_state (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            entry_key TEXT NOT NULL,
            prior_value TEXT NOT NULL,
            PRIMARY KEY (guild_id, channel_id, entry_key)
        )
    """)
    conn.commit()
    conn.close()


def set_lock_cutoff(guild_id, role_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO lock_settings (guild_id, cutoff_role_id) VALUES (?, ?) "
        "ON CONFLICT(guild_id) DO UPDATE SET cutoff_role_id = excluded.cutoff_role_id",
        (guild_id, role_id),
    )
    conn.commit()
    conn.close()


def get_lock_cutoff(guild_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT cutoff_role_id FROM lock_settings WHERE guild_id = ?", (guild_id,))
    row = cursor.fetchone()
    conn.close()
    return row["cutoff_role_id"] if row else None


def _encode_override(value):
    # discord.py PermissionOverwrite fields are True / False / None
    return "true" if value is True else "false" if value is False else "none"


def _decode_override(text):
    return True if text == "true" else False if text == "false" else None


def save_lock_state(guild_id, channel_id, entry_prior_pairs):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lock_state WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id))
    cursor.executemany(
        "INSERT INTO lock_state (guild_id, channel_id, entry_key, prior_value) VALUES (?, ?, ?, ?)",
        [(guild_id, channel_id, str(entry_key), _encode_override(prior)) for entry_key, prior in entry_prior_pairs],
    )
    conn.commit()
    conn.close()


def get_lock_state(guild_id, channel_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT entry_key, prior_value FROM lock_state WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id))
    rows = cursor.fetchall()
    conn.close()
    result = []
    for row in rows:
        key = row["entry_key"]
        key = key if key.startswith("member:") else int(key)
        result.append((key, _decode_override(row["prior_value"])))
    return result


def clear_lock_state(guild_id, channel_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lock_state WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id))
    conn.commit()
    conn.close()
