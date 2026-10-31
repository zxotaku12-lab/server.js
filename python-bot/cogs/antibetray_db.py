# Credits: gogeta_gg
"""Persistent Anti-Betray state with a small, version-tolerant schema."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import time

BASE_DIR = Path(__file__).resolve().parent
DB_NAME = BASE_DIR / "antibetray_v2.db"

CATEGORIES = (
    "trusted_mass_ban", "trusted_mass_kick", "trusted_channel_delete",
    "trusted_role_delete", "trusted_dangerous_role", "trusted_member_role_grant",
    "trusted_bot_add", "trusted_webhook", "trusted_role_create",
    "trusted_guild_change", "trusted_integration",
)
VALID_PUNISHMENTS = ("strip_roles", "kick", "ban")

# enabled, threshold, window_seconds
DEFAULT_RULES = {
    "trusted_mass_ban": (True, 3, 10),
    "trusted_mass_kick": (True, 3, 10),
    "trusted_channel_delete": (True, 2, 10),
    "trusted_role_delete": (True, 2, 10),
    "trusted_dangerous_role": (True, 2, 15),
    "trusted_member_role_grant": (True, 2, 15),
    "trusted_bot_add": (True, 1, 15),
    "trusted_webhook": (True, 2, 15),
    "trusted_role_create": (True, 4, 15),
    "trusted_guild_change": (True, 2, 20),
    "trusted_integration": (True, 1, 15),
}


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_NAME, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    return db


def setup_database() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                log_channel_id INTEGER,
                punishment TEXT NOT NULL DEFAULT 'strip_roles',
                threshold INTEGER NOT NULL DEFAULT 3,
                window_seconds INTEGER NOT NULL DEFAULT 12
            );
            CREATE TABLE IF NOT EXISTS threat_rules (
                guild_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                threshold INTEGER NOT NULL,
                window_seconds INTEGER NOT NULL,
                PRIMARY KEY(guild_id, category)
            );
            CREATE TABLE IF NOT EXISTS trusted_users (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY(guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS trusted_roles (
                guild_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY(guild_id, role_id)
            );
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                punishment TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 0,
                detail TEXT,
                timestamp INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_betray_incidents
                ON incidents(guild_id, timestamp DESC);
            """
        )
        cols = {row[1] for row in db.execute("PRAGMA table_info(settings)")}
        if "threshold" not in cols:
            db.execute("ALTER TABLE settings ADD COLUMN threshold INTEGER NOT NULL DEFAULT 3")
        if "window_seconds" not in cols:
            db.execute("ALTER TABLE settings ADD COLUMN window_seconds INTEGER NOT NULL DEFAULT 12")
        db_cols = {row[1] for row in db.execute("PRAGMA table_info(incidents)")}
        # Old table is kept compatible; the new code only relies on the fields
        # already present in the original version.
        if "detail" not in db_cols:
            db.execute("ALTER TABLE incidents ADD COLUMN detail TEXT")


def _ensure(guild_id: int) -> None:
    with connect() as db:
        db.execute(
            "INSERT INTO settings(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING",
            (guild_id,),
        )
        db.executemany(
            "INSERT INTO threat_rules(guild_id,category,enabled,threshold,window_seconds) "
            "VALUES(?,?,?,?,?) ON CONFLICT(guild_id,category) DO NOTHING",
            [
                (guild_id, category, int(enabled), threshold, window)
                for category, (enabled, threshold, window) in DEFAULT_RULES.items()
            ],
        )


def get_settings(guild_id: int) -> dict:
    _ensure(guild_id)
    with connect() as db:
        return dict(db.execute("SELECT * FROM settings WHERE guild_id=?", (guild_id,)).fetchone())


def _update(guild_id: int, **fields) -> None:
    _ensure(guild_id)
    allowed = {"enabled", "log_channel_id", "punishment", "threshold", "window_seconds"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    assignments = ",".join(f"{k}=?" for k in fields)
    with connect() as db:
        db.execute(f"UPDATE settings SET {assignments} WHERE guild_id=?", [*fields.values(), guild_id])


def set_enabled(guild_id: int, enabled: bool) -> None:
    _update(guild_id, enabled=int(bool(enabled)))


def set_log_channel(guild_id: int, channel_id: int | None) -> None:
    _update(guild_id, log_channel_id=channel_id)


def set_punishment(guild_id: int, punishment: str) -> None:
    punishment = str(punishment).strip().lower()
    if punishment not in VALID_PUNISHMENTS:
        raise ValueError("Invalid punishment")
    _update(guild_id, punishment=punishment)


def set_threshold(guild_id: int, threshold: int, window_seconds: int) -> None:
    _update(
        guild_id,
        threshold=max(1, min(20, int(threshold))),
        window_seconds=max(2, min(300, int(window_seconds))),
    )


def get_rule(guild_id: int, category: str) -> dict:
    if category not in CATEGORIES:
        raise ValueError(f"Invalid category: {category}")
    _ensure(guild_id)
    with connect() as db:
        return dict(db.execute(
            "SELECT * FROM threat_rules WHERE guild_id=? AND category=?",
            (guild_id, category),
        ).fetchone())


def set_rule(guild_id: int, category: str, *, enabled: bool | None = None, threshold: int | None = None, window_seconds: int | None = None) -> None:
    rule = get_rule(guild_id, category)
    fields = {}
    if enabled is not None: fields["enabled"] = int(bool(enabled))
    if threshold is not None: fields["threshold"] = max(1, min(50, int(threshold)))
    if window_seconds is not None: fields["window_seconds"] = max(2, min(300, int(window_seconds)))
    if not fields:
        return
    assignments = ",".join(f"{k}=?" for k in fields)
    with connect() as db:
        db.execute(f"UPDATE threat_rules SET {assignments} WHERE guild_id=? AND category=?", [*fields.values(), guild_id, category])


def is_category_enabled(guild_id: int, category: str) -> bool:
    return bool(get_rule(guild_id, category)["enabled"])


def get_disabled_categories(guild_id: int) -> list[str]:
    _ensure(guild_id)
    with connect() as db:
        rows = db.execute("SELECT category FROM threat_rules WHERE guild_id=? AND enabled=0", (guild_id,)).fetchall()
    disabled = {row[0] for row in rows}
    return [c for c in CATEGORIES if c in disabled]


def _set_trusted(table: str, column: str, guild_id: int, value: int, add: bool) -> None:
    with connect() as db:
        if add:
            db.execute(f"INSERT OR IGNORE INTO {table}(guild_id,{column}) VALUES(?,?)", (guild_id, int(value)))
        else:
            db.execute(f"DELETE FROM {table} WHERE guild_id=? AND {column}=?", (guild_id, int(value)))


def add_trusted_user(guild_id: int, user_id: int) -> None:
    _set_trusted("trusted_users", "user_id", guild_id, user_id, True)


def remove_trusted_user(guild_id: int, user_id: int) -> None:
    _set_trusted("trusted_users", "user_id", guild_id, user_id, False)


def list_trusted_users(guild_id: int) -> list[int]:
    with connect() as db:
        return [r[0] for r in db.execute("SELECT user_id FROM trusted_users WHERE guild_id=? ORDER BY user_id", (guild_id,))]


def add_trusted_role(guild_id: int, role_id: int) -> None:
    _set_trusted("trusted_roles", "role_id", guild_id, role_id, True)


def remove_trusted_role(guild_id: int, role_id: int) -> None:
    _set_trusted("trusted_roles", "role_id", guild_id, role_id, False)


def list_trusted_roles(guild_id: int) -> list[int]:
    with connect() as db:
        return [r[0] for r in db.execute("SELECT role_id FROM trusted_roles WHERE guild_id=? ORDER BY role_id", (guild_id,))]


def add_incident(guild_id, user_id, category, punishment, timestamp=None, success=False, detail="") -> None:
    with connect() as db:
        db.execute(
            "INSERT INTO incidents(guild_id,user_id,category,punishment,success,detail,timestamp) VALUES(?,?,?,?,?,?,?)",
            (guild_id, user_id, category, punishment, int(bool(success)), (detail or "")[:1500], int(timestamp or time.time())),
        )


def get_incidents(guild_id: int, limit: int = 50):
    with connect() as db:
        return db.execute(
            "SELECT * FROM incidents WHERE guild_id=? ORDER BY timestamp DESC LIMIT ?",
            (guild_id, max(1, min(500, int(limit)))),
        ).fetchall()


def cleanup_incidents(guild_id: int, keep: int = 500) -> None:
    keep = max(50, min(2000, int(keep)))
    with connect() as db:
        db.execute(
            "DELETE FROM incidents WHERE guild_id=? AND id NOT IN "
            "(SELECT id FROM incidents WHERE guild_id=? ORDER BY timestamp DESC LIMIT ?)",
            (guild_id, guild_id, keep),
        )


def reset_guild(guild_id: int) -> None:
    with connect() as db:
        for table in ("threat_rules", "trusted_users", "trusted_roles", "incidents", "settings"):
            db.execute(f"DELETE FROM {table} WHERE guild_id=?", (guild_id,))
