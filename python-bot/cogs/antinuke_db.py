# Credits: gogeta_gg
"""Persistent Anti-Nuke state.

The runtime firewall lives in :mod:`antinuke`; this module deliberately keeps
SQLite operations small, validated and backwards compatible with the existing
web dashboard/API.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import time

BASE_DIR = Path(__file__).resolve().parent
DB_NAME = BASE_DIR / "antinuke_v2.db"

CATEGORIES = (
    "ban", "kick", "prune_members", "bot_add",
    "channel_create", "channel_delete", "channel_update",
    "role_create", "role_delete", "role_update", "role_dangerous",
    "everyone_dangerous", "member_role_grant", "webhook_create",
    "webhook_update", "webhook_delete", "integration_change",
    "emoji_change", "sticker_change", "thread_create", "thread_delete",
    "thread_update", "scheduled_event_change", "guild_update",
)

VALID_PUNISHMENTS = ("strip_roles", "kick", "ban")
VALID_RULE_PUNISHMENTS = ("inherit",) + VALID_PUNISHMENTS

# enabled, threshold, window_seconds
DEFAULT_RULES = {
    "ban": (True, 3, 10),
    "kick": (True, 3, 10),
    "prune_members": (True, 1, 10),
    "bot_add": (True, 1, 10),
    "channel_create": (True, 5, 10),
    "channel_delete": (True, 2, 10),
    "channel_update": (True, 5, 10),
    "role_create": (True, 5, 10),
    "role_delete": (True, 2, 10),
    "role_update": (True, 5, 10),
    "role_dangerous": (True, 1, 10),
    "everyone_dangerous": (True, 1, 10),
    "member_role_grant": (True, 2, 10),
    "webhook_create": (True, 2, 10),
    "webhook_update": (True, 2, 10),
    "webhook_delete": (True, 2, 10),
    "integration_change": (True, 1, 10),
    "emoji_change": (True, 5, 15),
    "sticker_change": (True, 5, 15),
    "thread_create": (True, 8, 10),
    "thread_delete": (True, 3, 10),
    "thread_update": (True, 8, 10),
    "scheduled_event_change": (True, 2, 15),
    "guild_update": (True, 2, 20),
}


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_NAME, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    return db


def setup_database() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS security_settings (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                log_channel_id INTEGER,
                punishment TEXT NOT NULL DEFAULT 'strip_roles',
                global_threshold INTEGER NOT NULL DEFAULT 3,
                global_window INTEGER NOT NULL DEFAULT 10,
                auto_deploy INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS security_rules (
                guild_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                threshold INTEGER NOT NULL,
                window_seconds INTEGER NOT NULL,
                punishment TEXT NOT NULL DEFAULT 'inherit',
                PRIMARY KEY(guild_id, category)
            );
            CREATE TABLE IF NOT EXISTS whitelist_users (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY(guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS whitelist_roles (
                guild_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY(guild_id, role_id)
            );
            CREATE TABLE IF NOT EXISTS whitelist_bots (
                guild_id INTEGER NOT NULL,
                bot_id INTEGER NOT NULL,
                PRIMARY KEY(guild_id, bot_id)
            );
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                actor_id INTEGER,
                category TEXT NOT NULL,
                punishment TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 0,
                detail TEXT,
                timestamp INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_security_incidents
                ON incidents(guild_id, timestamp DESC);
            """
        )
        cols = {row[1] for row in db.execute("PRAGMA table_info(security_rules)")}
        if "punishment" not in cols:
            db.execute(
                "ALTER TABLE security_rules ADD COLUMN punishment TEXT NOT NULL DEFAULT 'inherit'"
            )


def _ensure(guild_id: int) -> None:
    with connect() as db:
        db.execute(
            "INSERT INTO security_settings(guild_id) VALUES(?) "
            "ON CONFLICT(guild_id) DO NOTHING",
            (guild_id,),
        )
        db.executemany(
            "INSERT INTO security_rules(guild_id,category,enabled,threshold,window_seconds) "
            "VALUES(?,?,?,?,?) ON CONFLICT(guild_id,category) DO NOTHING",
            [
                (guild_id, category, int(enabled), threshold, window)
                for category, (enabled, threshold, window) in DEFAULT_RULES.items()
            ],
        )


def get_settings(guild_id: int) -> dict:
    _ensure(guild_id)
    with connect() as db:
        row = db.execute(
            "SELECT * FROM security_settings WHERE guild_id=?", (guild_id,)
        ).fetchone()
    out = dict(row)
    # Dashboard/API compatibility aliases.
    out["threshold"] = out["global_threshold"]
    out["window_seconds"] = out["global_window"]
    return out


def _update(guild_id: int, **fields) -> None:
    _ensure(guild_id)
    if not fields:
        return
    allowed = {"enabled", "log_channel_id", "punishment", "global_threshold", "global_window", "auto_deploy"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    columns = ",".join(fields)
    placeholders = ",".join("?" for _ in fields)
    updates = ",".join(f"{k}=excluded.{k}" for k in fields)
    with connect() as db:
        db.execute(
            f"INSERT INTO security_settings(guild_id,{columns}) VALUES(?,{placeholders}) "
            f"ON CONFLICT(guild_id) DO UPDATE SET {updates}",
            [guild_id, *fields.values()],
        )


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
    threshold = max(1, min(50, int(threshold)))
    window_seconds = max(2, min(300, int(window_seconds)))
    _update(guild_id, global_threshold=threshold, global_window=window_seconds)


def get_rule(guild_id: int, category: str) -> dict:
    validate_category(category)
    _ensure(guild_id)
    with connect() as db:
        return dict(db.execute(
            "SELECT * FROM security_rules WHERE guild_id=? AND category=?",
            (guild_id, category),
        ).fetchone())


def set_rule(
    guild_id: int,
    category: str,
    *,
    enabled: bool | None = None,
    threshold: int | None = None,
    window_seconds: int | None = None,
    punishment: str | None = None,
) -> None:
    validate_category(category)
    _ensure(guild_id)
    fields = {}
    if enabled is not None:
        fields["enabled"] = int(bool(enabled))
    if threshold is not None:
        fields["threshold"] = max(1, min(100, int(threshold)))
    if window_seconds is not None:
        fields["window_seconds"] = max(2, min(300, int(window_seconds)))
    if punishment is not None:
        punishment = str(punishment).lower()
        if punishment not in VALID_RULE_PUNISHMENTS:
            raise ValueError("Invalid rule punishment")
        fields["punishment"] = punishment
    if not fields:
        return
    assignments = ",".join(f"{k}=?" for k in fields)
    with connect() as db:
        db.execute(
            f"UPDATE security_rules SET {assignments} WHERE guild_id=? AND category=?",
            [*fields.values(), guild_id, category],
        )


def validate_category(category: str) -> None:
    if category not in CATEGORIES:
        raise ValueError(f"Invalid category: {category}")


def set_category_enabled(guild_id: int, category: str, enabled: bool) -> None:
    set_rule(guild_id, category, enabled=enabled)


def set_rule_punishment(guild_id: int, category: str, punishment: str) -> None:
    set_rule(guild_id, category, punishment=punishment)


def effective_punishment(guild_id: int, category: str) -> str:
    rule = get_rule(guild_id, category)
    return get_settings(guild_id)["punishment"] if rule["punishment"] == "inherit" else rule["punishment"]


def is_category_enabled(guild_id: int, category: str) -> bool:
    return bool(get_rule(guild_id, category)["enabled"])


def get_disabled_categories(guild_id: int) -> list[str]:
    _ensure(guild_id)
    with connect() as db:
        rows = db.execute(
            "SELECT category FROM security_rules WHERE guild_id=? AND enabled=0",
            (guild_id,),
        ).fetchall()
    disabled = {row[0] for row in rows}
    return [category for category in CATEGORIES if category in disabled]


# --- Trust lists -----------------------------------------------------------
# The live Anti-Nuke engine (cogs/antinuke.py, v3) stores trust in the ``an_trust`` table.
# These helpers used to read/write the old ``whitelist_*`` tables, so Anti-Betray and the
# dashboard saw a DIFFERENT whitelist from the one Anti-Nuke actually enforced (a bot trusted
# in /antinuke was still kicked by Anti-Betray, and vice versa).  They now share ``an_trust``.
_TRUST_DDL = """
CREATE TABLE IF NOT EXISTS an_trust (
    guild_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    PRIMARY KEY(guild_id, kind, target_id)
)
"""


def _trust_set(kind: str, guild_id: int, value: int, add: bool) -> None:
    with connect() as db:
        db.execute(_TRUST_DDL)
        if add:
            db.execute("INSERT OR IGNORE INTO an_trust(guild_id,kind,target_id) VALUES(?,?,?)", (guild_id, kind, int(value)))
        else:
            db.execute("DELETE FROM an_trust WHERE guild_id=? AND kind=? AND target_id=?", (guild_id, kind, int(value)))


def _trust_has(kind: str, guild_id: int, value: int) -> bool:
    with connect() as db:
        db.execute(_TRUST_DDL)
        return db.execute("SELECT 1 FROM an_trust WHERE guild_id=? AND kind=? AND target_id=?", (guild_id, kind, int(value))).fetchone() is not None


def _trust_list(kind: str, guild_id: int) -> list[int]:
    with connect() as db:
        db.execute(_TRUST_DDL)
        return [int(r[0]) for r in db.execute("SELECT target_id FROM an_trust WHERE guild_id=? AND kind=? ORDER BY target_id", (guild_id, kind))]


def add_whitelisted_user(guild_id: int, user_id: int) -> None: _trust_set("user", guild_id, user_id, True)
def remove_whitelisted_user(guild_id: int, user_id: int) -> None: _trust_set("user", guild_id, user_id, False)
def is_user_whitelisted(guild_id: int, user_id: int) -> bool: return _trust_has("user", guild_id, user_id)
def list_whitelisted_users(guild_id: int) -> list[int]: return _trust_list("user", guild_id)
def add_whitelisted_role(guild_id: int, role_id: int) -> None: _trust_set("role", guild_id, role_id, True)
def remove_whitelisted_role(guild_id: int, role_id: int) -> None: _trust_set("role", guild_id, role_id, False)
def list_whitelisted_roles(guild_id: int) -> list[int]: return _trust_list("role", guild_id)
def add_whitelisted_bot(guild_id: int, bot_id: int) -> None: _trust_set("bot", guild_id, bot_id, True)
def remove_whitelisted_bot(guild_id: int, bot_id: int) -> None: _trust_set("bot", guild_id, bot_id, False)
def is_bot_whitelisted(guild_id: int, bot_id: int) -> bool: return _trust_has("bot", guild_id, bot_id)
def list_whitelisted_bots(guild_id: int) -> list[int]: return _trust_list("bot", guild_id)


# Compatibility hooks retained for older dashboard integrations.
def get_category_grants(guild_id, target_type, target_id):
    return {category: False for category in CATEGORIES}


def set_category_grant(guild_id, target_type, target_id, category, allowed):
    return None


def whitelist(guild_id, target_type, target_id, add=True):
    mapping = {
        ("user", True): add_whitelisted_user,
        ("user", False): remove_whitelisted_user,
        ("role", True): add_whitelisted_role,
        ("role", False): remove_whitelisted_role,
        ("bot", True): add_whitelisted_bot,
        ("bot", False): remove_whitelisted_bot,
    }
    fn = mapping.get((target_type, bool(add)))
    if not fn:
        raise ValueError("Invalid whitelist target")
    fn(guild_id, target_id)


def add_incident(guild_id, actor_id, category, punishment, timestamp=None, success=False, detail=""):
    with connect() as db:
        db.execute(
            "INSERT INTO incidents(guild_id,actor_id,category,punishment,success,detail,timestamp) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                guild_id,
                actor_id,
                category,
                punishment,
                int(bool(success)),
                detail[:1500] if detail else "",
                int(timestamp or time.time()),
            ),
        )


def get_incidents(guild_id: int, limit: int = 50):
    limit = max(1, min(500, int(limit)))
    with connect() as db:
        return db.execute(
            "SELECT * FROM incidents WHERE guild_id=? ORDER BY timestamp DESC LIMIT ?",
            (guild_id, limit),
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
        for table in ("security_rules", "whitelist_users", "whitelist_roles", "whitelist_bots", "incidents", "security_settings"):
            db.execute(f"DELETE FROM {table} WHERE guild_id=?", (guild_id,))
