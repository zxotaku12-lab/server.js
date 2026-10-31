# Credits: gogeta_gg
import sqlite3
import time

DB_NAME = "tickets.db"

TYPES = ("support", "reward", "staff_app")
TYPE_LABELS = {
    "support": "Support",
    "reward": "Reward",
    "staff_app": "Staff Application",
}


def connect():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def setup_database():
    conn = connect()
    cursor = conn.cursor()

    # One row per (guild, ticket type) — where new tickets of that type get
    # created and which role can see them, besides the opener.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ticket_type_config (
            guild_id INTEGER NOT NULL,
            ticket_type TEXT NOT NULL,
            category_id INTEGER,
            staff_role_id INTEGER,
            PRIMARY KEY (guild_id, ticket_type)
        )
    """)

    # One row per open/closed ticket channel.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER,
            ticket_type TEXT NOT NULL,
            opener_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            application_id INTEGER,
            created_at INTEGER NOT NULL,
            closed_at INTEGER,
            closed_by INTEGER
        )
    """)

    # One persistent AI handoff row per ticket. This lives beside the existing
    # ticket records so human takeover survives bot restarts without creating
    # a second database.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ticket_ai_state (
            ticket_id INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL UNIQUE,
            state TEXT NOT NULL,
            reason TEXT,
            updated_at INTEGER NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticket_ai_state_channel ON ticket_ai_state(channel_id)")

    conn.commit()
    conn.close()


# ── per-type configuration ──────────────────────────────────────────────

def _ensure_type_row(cursor, guild_id, ticket_type):
    cursor.execute(
        "SELECT 1 FROM ticket_type_config WHERE guild_id = ? AND ticket_type = ?",
        (guild_id, ticket_type),
    )
    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO ticket_type_config (guild_id, ticket_type) VALUES (?, ?)",
            (guild_id, ticket_type),
        )


def set_type_category(guild_id, ticket_type, category_id):
    conn = connect()
    cursor = conn.cursor()
    _ensure_type_row(cursor, guild_id, ticket_type)
    cursor.execute(
        "UPDATE ticket_type_config SET category_id = ? WHERE guild_id = ? AND ticket_type = ?",
        (category_id, guild_id, ticket_type),
    )
    conn.commit()
    conn.close()


def set_type_staff_role(guild_id, ticket_type, role_id):
    conn = connect()
    cursor = conn.cursor()
    _ensure_type_row(cursor, guild_id, ticket_type)
    cursor.execute(
        "UPDATE ticket_type_config SET staff_role_id = ? WHERE guild_id = ? AND ticket_type = ?",
        (role_id, guild_id, ticket_type),
    )
    conn.commit()
    conn.close()


def get_type_config(guild_id, ticket_type):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM ticket_type_config WHERE guild_id = ? AND ticket_type = ?",
        (guild_id, ticket_type),
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_type_configs(guild_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ticket_type_config WHERE guild_id = ?", (guild_id,))
    rows = cursor.fetchall()
    conn.close()
    return {row["ticket_type"]: dict(row) for row in rows}


# ── ticket lifecycle ────────────────────────────────────────────────────

def has_open_ticket(guild_id, opener_id, ticket_type):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT 1 FROM tickets
        WHERE guild_id = ? AND opener_id = ? AND ticket_type = ? AND status = 'open'
        LIMIT 1
        """,
        (guild_id, opener_id, ticket_type),
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None


def create_ticket(guild_id, ticket_type, opener_id) -> int:
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO tickets (guild_id, ticket_type, opener_id, status, created_at)
        VALUES (?, ?, ?, 'open', ?)
        """,
        (guild_id, ticket_type, opener_id, int(time.time())),
    )
    conn.commit()
    ticket_id = cursor.lastrowid
    conn.close()
    return ticket_id


def set_ticket_channel(ticket_id, channel_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET channel_id = ? WHERE id = ?", (channel_id, ticket_id))
    conn.commit()
    conn.close()


def link_application(ticket_id, application_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET application_id = ? WHERE id = ?", (application_id, ticket_id))
    conn.commit()
    conn.close()


def get_ticket(ticket_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_ticket_by_channel(channel_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tickets WHERE channel_id = ?", (channel_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_ticket_ai_state(channel_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT ticket_id, channel_id, state, reason, updated_at FROM ticket_ai_state WHERE channel_id = ?",
        (channel_id,),
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def set_ticket_ai_state(ticket_id, channel_id, state, reason=None):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO ticket_ai_state (ticket_id, channel_id, state, reason, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(ticket_id) DO UPDATE SET
            channel_id = excluded.channel_id,
            state = excluded.state,
            reason = excluded.reason,
            updated_at = excluded.updated_at
        """,
        (ticket_id, channel_id, state, reason, int(time.time())),
    )
    conn.commit()
    conn.close()


def delete_ticket_ai_state(ticket_id=None, channel_id=None):
    if ticket_id is None and channel_id is None:
        return
    conn = connect()
    cursor = conn.cursor()
    if ticket_id is not None:
        cursor.execute("DELETE FROM ticket_ai_state WHERE ticket_id = ?", (ticket_id,))
    else:
        cursor.execute("DELETE FROM ticket_ai_state WHERE channel_id = ?", (channel_id,))
    conn.commit()
    conn.close()


def close_ticket(ticket_id, closed_by):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE tickets SET status = 'closed', closed_at = ?, closed_by = ? WHERE id = ?",
        (int(time.time()), closed_by, ticket_id),
    )
    cursor.execute("DELETE FROM ticket_ai_state WHERE ticket_id = ?", (ticket_id,))
    conn.commit()
    conn.close()
