# Credits: gogeta_gg
import sqlite3
import time
import json

DB_NAME = "applications.db"

DEFAULT_QUESTIONS = [
    "Why do you want to join the staff team?",
    "Do you have any previous moderation/staff experience?",
    "What timezone are you in, and how many hours a week can you commit?",
    "Is there anything else you'd like us to know?",
]


def connect():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def setup_database():
    conn = connect()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS apply_settings (
            guild_id INTEGER PRIMARY KEY,
            review_channel_id INTEGER,
            grant_role_id INTEGER,
            required_role_id INTEGER,
            questions TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            answers TEXT NOT NULL,
            review_channel_id INTEGER,
            review_message_id INTEGER,
            reviewed_by INTEGER,
            reviewed_at INTEGER,
            reason TEXT,
            created_at INTEGER NOT NULL
        )
    """)

    # Migration: add approval_channel_id to older databases that predate it.
    cursor.execute("PRAGMA table_info(apply_settings)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    if "approval_channel_id" not in existing_columns:
        cursor.execute("ALTER TABLE apply_settings ADD COLUMN approval_channel_id INTEGER")

    conn.commit()
    conn.close()


# ── Settings ────────────────────────────────────────────────────────────

def get_settings(guild_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM apply_settings WHERE guild_id = ?", (guild_id,))
    row = cursor.fetchone()
    conn.close()
    if row is None:
        return None
    settings = dict(row)
    settings["questions"] = json.loads(settings["questions"])
    return settings


def _ensure_row(cursor, guild_id):
    cursor.execute(
        "SELECT guild_id FROM apply_settings WHERE guild_id = ?", (guild_id,)
    )
    if cursor.fetchone() is None:
        cursor.execute(
            """
            INSERT INTO apply_settings (guild_id, questions, enabled)
            VALUES (?, ?, 1)
            """,
            (guild_id, json.dumps(DEFAULT_QUESTIONS)),
        )


def set_review_channel(guild_id, channel_id):
    conn = connect()
    cursor = conn.cursor()
    _ensure_row(cursor, guild_id)
    cursor.execute(
        "UPDATE apply_settings SET review_channel_id = ? WHERE guild_id = ?",
        (channel_id, guild_id),
    )
    conn.commit()
    conn.close()


def set_grant_role(guild_id, role_id):
    conn = connect()
    cursor = conn.cursor()
    _ensure_row(cursor, guild_id)
    cursor.execute(
        "UPDATE apply_settings SET grant_role_id = ? WHERE guild_id = ?",
        (role_id, guild_id),
    )
    conn.commit()
    conn.close()


def set_required_role(guild_id, role_id):
    conn = connect()
    cursor = conn.cursor()
    _ensure_row(cursor, guild_id)
    cursor.execute(
        "UPDATE apply_settings SET required_role_id = ? WHERE guild_id = ?",
        (role_id, guild_id),
    )
    conn.commit()
    conn.close()


def set_approval_channel(guild_id, channel_id):
    conn = connect()
    cursor = conn.cursor()
    _ensure_row(cursor, guild_id)
    cursor.execute(
        "UPDATE apply_settings SET approval_channel_id = ? WHERE guild_id = ?",
        (channel_id, guild_id),
    )
    conn.commit()
    conn.close()


def set_questions(guild_id, questions):
    conn = connect()
    cursor = conn.cursor()
    _ensure_row(cursor, guild_id)
    cursor.execute(
        "UPDATE apply_settings SET questions = ? WHERE guild_id = ?",
        (json.dumps(questions), guild_id),
    )
    conn.commit()
    conn.close()


def set_enabled(guild_id, enabled: bool):
    conn = connect()
    cursor = conn.cursor()
    _ensure_row(cursor, guild_id)
    cursor.execute(
        "UPDATE apply_settings SET enabled = ? WHERE guild_id = ?",
        (1 if enabled else 0, guild_id),
    )
    conn.commit()
    conn.close()


# ── Applications ────────────────────────────────────────────────────────

def has_pending_application(guild_id, user_id) -> bool:
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT 1 FROM applications
        WHERE guild_id = ? AND user_id = ? AND status = 'pending'
        LIMIT 1
        """,
        (guild_id, user_id),
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None


def create_application(guild_id, user_id, answers: list) -> int:
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO applications (guild_id, user_id, status, answers, created_at)
        VALUES (?, ?, 'pending', ?, ?)
        """,
        (guild_id, user_id, json.dumps(answers), int(time.time())),
    )
    conn.commit()
    app_id = cursor.lastrowid
    conn.close()
    return app_id


def set_review_message(app_id, channel_id, message_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE applications
        SET review_channel_id = ?, review_message_id = ?
        WHERE id = ?
        """,
        (channel_id, message_id, app_id),
    )
    conn.commit()
    conn.close()


def get_application(app_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
    row = cursor.fetchone()
    conn.close()
    if row is None:
        return None
    app = dict(row)
    app["answers"] = json.loads(app["answers"])
    return app


def get_application_by_message(message_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM applications WHERE review_message_id = ?", (message_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if row is None:
        return None
    app = dict(row)
    app["answers"] = json.loads(app["answers"])
    return app


def get_latest_application(guild_id, user_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM applications
        WHERE guild_id = ? AND user_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (guild_id, user_id),
    )
    row = cursor.fetchone()
    conn.close()
    if row is None:
        return None
    app = dict(row)
    app["answers"] = json.loads(app["answers"])
    return app


def update_application_status(app_id, status, reviewed_by, reason=None):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE applications
        SET status = ?, reviewed_by = ?, reviewed_at = ?, reason = ?
        WHERE id = ?
        """,
        (status, reviewed_by, int(time.time()), reason, app_id),
    )
    conn.commit()
    conn.close()
