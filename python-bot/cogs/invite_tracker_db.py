# Credits: gogeta_gg
from pathlib import Path
import sqlite3
import time

BASE_DIR = Path(__file__).resolve().parent
DB_NAME = BASE_DIR / "invite_tracker.db"

JOIN_TYPES = ("regular", "fake", "vanity", "unknown")

DEFAULT_FAKE_ACCOUNT_AGE_DAYS = 3


def connect():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def setup_database():
    conn = connect()
    cursor = conn.cursor()
    conn.execute("PRAGMA journal_mode = WAL")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invite_tracker_settings (
            guild_id INTEGER PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
            log_channel_id INTEGER,
            fake_account_age_days INTEGER NOT NULL DEFAULT 3
        )
    """)

    # Manual adjustments from /invites-add and /invites-remove. Kept
    # separate from invite_joins because a bonus isn't tied to any single
    # join event — it's a standing credit/debit an admin applied.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invite_bonus (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
    """)

    # One row per join. left_at is set when that member later leaves, so we
    # can tell "regular" (still here) apart from "leave" (invited, left)
    # without losing history. A rejoin creates a brand new row.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invite_joins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            inviter_id INTEGER,
            code TEXT,
            join_type TEXT NOT NULL DEFAULT 'unknown'
                CHECK(join_type IN ('regular', 'fake', 'vanity', 'unknown')),
            joined_at INTEGER NOT NULL,
            left_at INTEGER
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_invite_joins_guild_inviter
        ON invite_joins(guild_id, inviter_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_invite_joins_guild_member
        ON invite_joins(guild_id, member_id)
    """)

    conn.commit()
    conn.close()


# ── Settings ─────────────────────────────────────────────────────────────

def get_settings(guild_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO invite_tracker_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING",
        (guild_id,),
    )
    conn.commit()
    cursor.execute("SELECT * FROM invite_tracker_settings WHERE guild_id = ?", (guild_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row)


def set_enabled(guild_id, enabled: bool):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO invite_tracker_settings (guild_id, enabled) VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET enabled = excluded.enabled
        """,
        (guild_id, int(enabled)),
    )
    conn.commit()
    conn.close()


def set_log_channel(guild_id, channel_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO invite_tracker_settings (guild_id, log_channel_id) VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET log_channel_id = excluded.log_channel_id
        """,
        (guild_id, channel_id),
    )
    conn.commit()
    conn.close()


def set_fake_account_age(guild_id, days):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO invite_tracker_settings (guild_id, fake_account_age_days) VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET fake_account_age_days = excluded.fake_account_age_days
        """,
        (guild_id, days),
    )
    conn.commit()
    conn.close()


# ── Bonus ────────────────────────────────────────────────────────────────

def adjust_bonus(guild_id, user_id, delta):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO invite_bonus (guild_id, user_id, amount) VALUES (?, ?, ?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET amount = amount + excluded.amount
        """,
        (guild_id, user_id, delta),
    )
    conn.commit()
    cursor.execute(
        "SELECT amount FROM invite_bonus WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    row = cursor.fetchone()
    conn.close()
    return row["amount"] if row else 0


def get_bonus(guild_id, user_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT amount FROM invite_bonus WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    row = cursor.fetchone()
    conn.close()
    return row["amount"] if row else 0


# ── Joins / leaves ───────────────────────────────────────────────────────

def record_join(guild_id, member_id, inviter_id, code, join_type, timestamp=None):
    if join_type not in JOIN_TYPES:
        raise ValueError(f"Invalid join_type: {join_type}")
    timestamp = timestamp if timestamp is not None else int(time.time())
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO invite_joins (guild_id, member_id, inviter_id, code, join_type, joined_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (guild_id, member_id, inviter_id, code, join_type, timestamp),
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def record_leave(guild_id, member_id, timestamp=None):
    """Close out the member's most recent open join row. Returns that row
    (as a dict) so the caller can notify the inviter, or None if we had no
    record of how this member joined (e.g. they joined before tracking was
    enabled)."""
    timestamp = timestamp if timestamp is not None else int(time.time())
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM invite_joins
        WHERE guild_id = ? AND member_id = ? AND left_at IS NULL
        ORDER BY joined_at DESC
        LIMIT 1
        """,
        (guild_id, member_id),
    )
    row = cursor.fetchone()
    if row is None:
        conn.close()
        return None

    cursor.execute(
        "UPDATE invite_joins SET left_at = ? WHERE id = ?",
        (timestamp, row["id"]),
    )
    conn.commit()
    conn.close()
    result = dict(row)
    result["left_at"] = timestamp
    return result


# ── Stats ────────────────────────────────────────────────────────────────

def get_stats(guild_id, user_id):
    conn = connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM invite_joins
        WHERE guild_id = ? AND inviter_id = ? AND join_type = 'regular' AND left_at IS NULL
        """,
        (guild_id, user_id),
    )
    regular = cursor.fetchone()["c"]

    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM invite_joins
        WHERE guild_id = ? AND inviter_id = ? AND join_type = 'regular' AND left_at IS NOT NULL
        """,
        (guild_id, user_id),
    )
    leaves = cursor.fetchone()["c"]

    cursor.execute(
        """
        SELECT COUNT(*) AS c FROM invite_joins
        WHERE guild_id = ? AND inviter_id = ? AND join_type = 'fake'
        """,
        (guild_id, user_id),
    )
    fake = cursor.fetchone()["c"]

    conn.close()
    bonus = get_bonus(guild_id, user_id)
    total = regular + bonus - leaves

    return {
        "regular": regular,
        "leaves": leaves,
        "fake": fake,
        "bonus": bonus,
        "total": total,
    }


def _full_board(guild_id):
    """Every user who has either invited someone or received a bonus
    adjustment, ranked by effective total (regular + bonus - leaves).
    Shared by get_leaderboard and get_rank so both agree on ordering."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT inviter_id FROM invite_joins WHERE guild_id = ? AND inviter_id IS NOT NULL",
        (guild_id,),
    )
    inviter_ids = {row["inviter_id"] for row in cursor.fetchall()}
    cursor.execute("SELECT user_id FROM invite_bonus WHERE guild_id = ?", (guild_id,))
    inviter_ids |= {row["user_id"] for row in cursor.fetchall()}
    conn.close()

    board = [(uid, get_stats(guild_id, uid)) for uid in inviter_ids]
    board.sort(key=lambda pair: pair[1]["total"], reverse=True)
    return board


def get_leaderboard(guild_id, limit=10):
    return _full_board(guild_id)[:limit]


def get_rank(guild_id, user_id):
    """Returns (rank, total_tracked_users). rank is None if this user has
    no invites and no bonus adjustment on record (nothing to rank)."""
    board = _full_board(guild_id)
    total = len(board)
    for i, (uid, _stats) in enumerate(board, start=1):
        if uid == user_id:
            return i, total
    return None, total


def get_invited_members(guild_id, inviter_id, include_left=True):
    """Return distinct people attributed to an inviter, newest join first.

    This is intentionally separate from get_stats(): eligibility verification needs
    the underlying member IDs so the ticket assistant can inspect each account.
    """
    conn = connect()
    cursor = conn.cursor()
    sql = """
        SELECT member_id, joined_at, left_at, join_type, code
        FROM invite_joins
        WHERE guild_id = ? AND inviter_id = ?
        ORDER BY joined_at DESC
    """
    cursor.execute(sql, (guild_id, inviter_id))
    rows = cursor.fetchall()
    conn.close()

    latest = {}
    for row in rows:
        member_id = int(row["member_id"])
        if member_id not in latest:
            latest[member_id] = dict(row)
    values = list(latest.values())
    if not include_left:
        values = [row for row in values if row.get("left_at") is None]
    return values


def get_recent_activity(guild_id, user_id, limit=5):
    """Recent join/leave events among people this user invited, newest
    first. A row with left_at set counts as a 'left' event (using left_at
    as the event time); otherwise it's a 'joined' event."""
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT member_id, joined_at, left_at FROM invite_joins
        WHERE guild_id = ? AND inviter_id = ?
        ORDER BY COALESCE(left_at, joined_at) DESC
        LIMIT ?
        """,
        (guild_id, user_id, limit),
    )
    rows = cursor.fetchall()
    conn.close()

    events = []
    for row in rows:
        if row["left_at"]:
            events.append({"member_id": row["member_id"], "type": "left", "at": row["left_at"]})
        else:
            events.append({"member_id": row["member_id"], "type": "joined", "at": row["joined_at"]})
    return events


def reset_user(guild_id, user_id):
    conn = connect()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM invite_joins WHERE guild_id = ? AND inviter_id = ?",
        (guild_id, user_id),
    )
    cursor.execute(
        "DELETE FROM invite_bonus WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    conn.commit()
    conn.close()


def reset_guild(guild_id):
    conn = connect()
    cursor = conn.cursor()
    for table in ("invite_tracker_settings", "invite_bonus", "invite_joins"):
        cursor.execute(f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,))
    conn.commit()
    conn.close()
