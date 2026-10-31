# Credits: gogeta_gg
import aiosqlite
import discord
from datetime import datetime, timezone

DB_NAME = "activity.db"


async def setup_database():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS activity (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        last_activity TEXT NOT NULL,
        warned INTEGER DEFAULT 0,
        staff_notified INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    )
    """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS inactivity_settings (
            guild_id INTEGER PRIMARY KEY,
            kick_after_days INTEGER NOT NULL DEFAULT 150,
            auto_kick_enabled INTEGER NOT NULL DEFAULT 1,
            warning_channel_id INTEGER,
            staff_channel_id INTEGER,
            staff_ping_role_id INTEGER
        )
        """)

        # Older DBs created before warning/staff channels became
        # per-guild + configurable won't have these columns yet.
        # ALTER TABLE ADD COLUMN is the only portable way to migrate an
        # existing sqlite table in place, and sqlite has no
        # "ADD COLUMN IF NOT EXISTS", so we just try each one and ignore
        # the "duplicate column" error on databases that already have it.
        for column, coltype in (
            ("warning_channel_id", "INTEGER"),
            ("staff_channel_id", "INTEGER"),
            ("staff_ping_role_id", "INTEGER"),
        ):
            try:
                await db.execute(
                    f"ALTER TABLE inactivity_settings ADD COLUMN {column} {coltype}"
                )
            except Exception:
                pass  # column already exists

        # Per-role overrides: exemption and/or custom warning/kick
        # thresholds for members holding a given role.
        await db.execute("""
        CREATE TABLE IF NOT EXISTS inactivity_role_settings (
            guild_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            exempt INTEGER NOT NULL DEFAULT 0,
            warning_days INTEGER,
            kick_days INTEGER,
            PRIMARY KEY (guild_id, role_id)
        )
        """)

        await db.commit()


async def add_member(member: discord.Member):
    if member.bot:
        return

    joined = member.joined_at or datetime.now(timezone.utc)

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT OR IGNORE INTO activity
        (guild_id, user_id, last_activity, warned, staff_notified)
        VALUES (?, ?, ?, 0, 0)
        """, (
            member.guild.id,
            member.id,
            joined.isoformat()
        ))
        await db.commit()


async def update_activity(guild_id: int, user_id: int):
    now = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT INTO activity
        (guild_id, user_id, last_activity, warned, staff_notified)
        VALUES (?, ?, ?, 0, 0)
        ON CONFLICT(guild_id, user_id)
        DO UPDATE SET
            last_activity = excluded.last_activity,
            warned = 0,
            staff_notified = 0
        """, (
            guild_id,
            user_id,
            now
        ))
        await db.commit()

async def mark_warned(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            UPDATE activity
            SET warned = 1
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id)
        )
        await db.commit()

async def get_member_activity(guild_id: int, user_id: int):
    """Returns (last_activity, warned, staff_notified) for one member in one
    guild, or None if there's no record yet. Used by /activity and
    /activity_check."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
        SELECT last_activity, warned, staff_notified
        FROM activity
        WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))

        row = await cursor.fetchone()

    return row


async def get_all_members():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
        SELECT
            guild_id,
            user_id,
            last_activity,
            warned,
            staff_notified
        FROM activity
        """)

        rows = await cursor.fetchall()

    return rows

async def get_guild_members(guild_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
        SELECT user_id, last_activity
        FROM activity
        WHERE guild_id = ?
        """, (guild_id,))

        rows = await cursor.fetchall()

    return rows

async def remove_member(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            DELETE FROM activity
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id)
        )
        await db.commit()

async def mark_staff_notified(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        UPDATE activity
        SET staff_notified = 1
        WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))
        await db.commit()


async def reset_all_warning_flags():
    """
    One-time safety reset: clears warned/staff_notified for everyone.
    Used after fixing a tracking gap so nobody gets warned/kicked off of
    stale data recorded while activity wasn't being tracked correctly.
    Does NOT touch last_activity, so genuinely inactive members will still
    surface again on their own after the normal thresholds pass.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        UPDATE activity
        SET warned = 0, staff_notified = 0
        """)
        await db.commit()


async def repair_duplicate_activity_rows():
    """
    Self-heal for a data-integrity bug: if activity.db was ever created by
    an older version of this table without a real PRIMARY KEY on
    (guild_id, user_id), then update_activity()'s "ON CONFLICT ... DO
    UPDATE" silently can't match anything and just inserts a brand new row
    every time instead of updating the existing one. Over time that leaves
    multiple rows per member, each with a different stale last_activity —
    which is exactly what causes inconsistent, wrong inactivity warnings
    (different people ending up with different bogus "days inactive").

    This detects duplicates and/or a missing PK, and rebuilds the table
    keeping only the most-recent row per (guild_id, user_id).
    """
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='activity'"
        )
        row = await cursor.fetchone()
        has_correct_pk = row is not None and row[0] and "PRIMARY KEY (guild_id, user_id)" in row[0]

        cursor = await db.execute("""
            SELECT guild_id, user_id, COUNT(*) as c
            FROM activity
            GROUP BY guild_id, user_id
            HAVING c > 1
        """)
        duplicates = await cursor.fetchall()

        if not duplicates and has_correct_pk:
            return 0  # nothing to repair

        await db.execute("""
            CREATE TABLE IF NOT EXISTS activity_repaired (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                last_activity TEXT NOT NULL,
                warned INTEGER DEFAULT 0,
                staff_notified INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        # Keep only the most-recent row per (guild_id, user_id).
        await db.execute("""
            INSERT OR REPLACE INTO activity_repaired
                (guild_id, user_id, last_activity, warned, staff_notified)
            SELECT a.guild_id, a.user_id, a.last_activity, a.warned, a.staff_notified
            FROM activity a
            WHERE a.rowid = (
                SELECT b.rowid FROM activity b
                WHERE b.guild_id = a.guild_id AND b.user_id = a.user_id
                ORDER BY b.last_activity DESC
                LIMIT 1
            )
        """)

        await db.execute("DROP TABLE activity")
        await db.execute("ALTER TABLE activity_repaired RENAME TO activity")
        await db.commit()

        return len(duplicates)

async def get_kick_settings(guild_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
        SELECT kick_after_days, auto_kick_enabled
        FROM inactivity_settings
        WHERE guild_id = ?
        """, (guild_id,))

        row = await cursor.fetchone()

        if row is None:
            await db.execute("""
            INSERT INTO inactivity_settings
            (guild_id)
            VALUES (?)
            """, (guild_id,))
            await db.commit()

            return 150, True

        return row[0], bool(row[1])


async def set_kick_days(guild_id: int, days: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT INTO inactivity_settings
        (guild_id, kick_after_days)
        VALUES (?, ?)
        ON CONFLICT(guild_id)
        DO UPDATE SET
            kick_after_days = excluded.kick_after_days
        """, (guild_id, days))
        await db.commit()


async def set_auto_kick(guild_id: int, enabled: bool):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT INTO inactivity_settings
        (guild_id, auto_kick_enabled)
        VALUES (?, ?)
        ON CONFLICT(guild_id)
        DO UPDATE SET
            auto_kick_enabled = excluded.auto_kick_enabled
        """, (guild_id, int(enabled)))
        await db.commit()


# ===========================
# PER-GUILD CHANNEL CONFIG
# (replaces the old hardcoded WARNING_CHANNEL_ID / STAFF_CHANNEL_ID)
# ===========================

async def set_channels(guild_id: int, warning_channel_id: int, staff_channel_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT INTO inactivity_settings
        (guild_id, warning_channel_id, staff_channel_id)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id)
        DO UPDATE SET
            warning_channel_id = excluded.warning_channel_id,
            staff_channel_id = excluded.staff_channel_id
        """, (guild_id, warning_channel_id, staff_channel_id))
        await db.commit()


async def get_channels(guild_id: int):
    """Returns (warning_channel_id, staff_channel_id), either of which may
    be None if that guild hasn't configured it yet."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
        SELECT warning_channel_id, staff_channel_id
        FROM inactivity_settings
        WHERE guild_id = ?
        """, (guild_id,))

        row = await cursor.fetchone()

    if row is None:
        return None, None

    return row[0], row[1]


async def set_staff_ping_role(guild_id: int, role_id):
    """role_id can be None to clear the ping role."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT INTO inactivity_settings
        (guild_id, staff_ping_role_id)
        VALUES (?, ?)
        ON CONFLICT(guild_id)
        DO UPDATE SET
            staff_ping_role_id = excluded.staff_ping_role_id
        """, (guild_id, role_id))
        await db.commit()


async def get_staff_ping_role(guild_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
        SELECT staff_ping_role_id
        FROM inactivity_settings
        WHERE guild_id = ?
        """, (guild_id,))

        row = await cursor.fetchone()

    return row[0] if row else None


# ===========================
# PER-ROLE INACTIVITY CONFIG
# ===========================

async def set_role_exempt(guild_id: int, role_id: int, exempt: bool):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT INTO inactivity_role_settings
        (guild_id, role_id, exempt)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id, role_id)
        DO UPDATE SET
            exempt = excluded.exempt
        """, (guild_id, role_id, int(exempt)))
        await db.commit()


async def set_role_thresholds(guild_id: int, role_id: int, warning_days, kick_days):
    """warning_days / kick_days may be None to leave that field untouched."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT INTO inactivity_role_settings
        (guild_id, role_id, warning_days, kick_days)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, role_id)
        DO UPDATE SET
            warning_days = COALESCE(excluded.warning_days, inactivity_role_settings.warning_days),
            kick_days = COALESCE(excluded.kick_days, inactivity_role_settings.kick_days)
        """, (guild_id, role_id, warning_days, kick_days))
        await db.commit()


async def clear_role_config(guild_id: int, role_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        DELETE FROM inactivity_role_settings
        WHERE guild_id = ? AND role_id = ?
        """, (guild_id, role_id))
        await db.commit()


async def get_role_configs(guild_id: int):
    """Returns a list of (role_id, exempt, warning_days, kick_days) rows
    for every role that has a custom inactivity config in this guild."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
        SELECT role_id, exempt, warning_days, kick_days
        FROM inactivity_role_settings
        WHERE guild_id = ?
        """, (guild_id,))

        rows = await cursor.fetchall()

    return rows

