# Credits: gogeta_gg
import sqlite3
import time

DB_NAME = "giveaways.db"


def connect():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def setup_database():
    conn = connect()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS giveaways (
            message_id INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            host_id INTEGER NOT NULL,
            prize TEXT NOT NULL,
            winners INTEGER NOT NULL,
            end_time INTEGER NOT NULL,
            ended INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS giveaway_entries (
            message_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (message_id, user_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bonus_roles (
            guild_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            entries INTEGER NOT NULL,
            PRIMARY KEY (guild_id, role_id)
        )
    """)
    conn.commit()
    conn.close()


def create_giveaway(
    message_id,
    channel_id,
    guild_id,
    host_id,
    prize,
    winners,
    end_time
):
    conn = connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO giveaways
        (
            message_id,
            channel_id,
            guild_id,
            host_id,
            prize,
            winners,
            end_time,
            ended
        )
        VALUES
        (?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            message_id,
            channel_id,
            guild_id,
            host_id,
            prize,
            winners,
            end_time,
        ),
    )

    conn.commit()
    conn.close()

def add_entry(message_id, user_id):
    conn = connect()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO giveaway_entries
            (message_id, user_id)
            VALUES (?, ?)
            """,
            (message_id, user_id),
        )

        conn.commit()
        success = True

    except sqlite3.IntegrityError:
        success = False

    conn.close()
    return success


def get_entries(message_id):
    conn = connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT user_id
        FROM giveaway_entries
        WHERE message_id = ?
        """,
        (message_id,),
    )

    users = [row["user_id"] for row in cursor.fetchall()]

    conn.close()
    return users


def get_giveaway(message_id):
    conn = connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM giveaways
        WHERE message_id = ?
        """,
        (message_id,),
    )

    giveaway = cursor.fetchone()

    conn.close()
    return giveaway


def get_active_giveaways():
    conn = connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM giveaways
        WHERE ended = 0
        """
    )

    giveaways = cursor.fetchall()

    conn.close()
    return giveaways


def has_active_giveaway(guild_id):
    conn = connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 1
        FROM giveaways
        WHERE guild_id = ? AND ended = 0
        LIMIT 1
        """,
        (guild_id,),
    )

    result = cursor.fetchone()
    conn.close()
    return result is not None

def mark_giveaway_ended(message_id):
    conn = connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE giveaways
        SET ended = 1
        WHERE message_id = ?
        """,
        (message_id,),
    )

    conn.commit()
    conn.close()


def is_giveaway_ended(message_id):
    conn = connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT ended
        FROM giveaways
        WHERE message_id = ?
        """,
        (message_id,),
    )

    row = cursor.fetchone()

    conn.close()

    if row is None:
        return True

    return bool(row["ended"])


def get_expired_giveaways():
    conn = connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM giveaways
        WHERE ended = 0
        AND end_time <= ?
        """,
        (int(time.time()),),
    )

    giveaways = cursor.fetchall()

    conn.close()
    return giveaways


def delete_giveaway(message_id):
    conn = connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM giveaways
        WHERE message_id = ?
        """,
        (message_id,),
    )

    cursor.execute(
        """
        DELETE FROM giveaway_entries
        WHERE message_id = ?
        """,
        (message_id,),
    )

    conn.commit()
    conn.close()


def get_entry_count(message_id):
    return len(get_entries(message_id))

def add_bonus_role(guild_id, role_id, entries):
    conn = connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO bonus_roles
        (guild_id, role_id, entries)
        VALUES (?, ?, ?)
        """,
        (guild_id, role_id, entries),
    )

    conn.commit()
    conn.close()


def remove_bonus_role(guild_id, role_id):
    conn = connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM bonus_roles
        WHERE guild_id = ?
        AND role_id = ?
        """,
        (guild_id, role_id),
    )

    conn.commit()
    conn.close()


def get_bonus_roles(guild_id):
    conn = connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM bonus_roles
        WHERE guild_id = ?
        ORDER BY entries DESC
        """,
        (guild_id,),
    )

    rows = cursor.fetchall()

    conn.close()
    return rows


def get_bonus_entries(guild_id, role_ids):
    conn = connect()
    cursor = conn.cursor()

    highest = 1

    for role_id in role_ids:
        cursor.execute(
            """
            SELECT entries
            FROM bonus_roles
            WHERE guild_id = ?
            AND role_id = ?
            """,
            (guild_id, role_id),
        )

        row = cursor.fetchone()

        if row:
            highest = max(highest, row["entries"])

    conn.close()
    return highest
