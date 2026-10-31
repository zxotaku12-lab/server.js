# Credits: gogeta_gg
"""Persistent AutoMod configuration and incident storage.

The database intentionally keeps the v2 filename/schema surface so the web
security dashboard and existing guild settings survive a code rewrite.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import time

BASE_DIR = Path(__file__).resolve().parent
DB_NAME = BASE_DIR / "automod_v2.db"

RULES = (
    "spam", "duplicate", "mentions", "invites", "caps", "emoji_spam",
    "zalgo", "bad_words", "links", "attachments", "newlines",
)

# enabled, primary numeric threshold, secondary numeric value.
# For spam/duplicate the secondary value is seconds; for caps it is minimum
# letters; for the remaining rules it is unused.
DEFAULTS = {
    "spam": (True, 6, 8),
    "duplicate": (True, 3, 10),
    "mentions": (True, 6, 0),
    "invites": (True, 1, 0),
    "caps": (True, 75, 12),
    "emoji_spam": (True, 14, 0),
    "zalgo": (True, 10, 0),
    "bad_words": (True, 1, 0),
    "links": (True, 1, 0),
    "attachments": (False, 3, 0),
    "newlines": (True, 18, 0),
}

LINK_TYPES = (
    "youtube", "discord_invites", "gifs", "images", "tiktok",
    "instagram", "twitch", "reddit", "twitter", "external",
)

DEFAULT_LINK_FILTERS = {
    "youtube": True,
    "discord_invites": True,
    "gifs": True,
    "images": False,
    "tiktok": False,
    "instagram": False,
    "twitch": False,
    "reddit": False,
    "twitter": False,
    "external": False,
}

VALID_PUNISHMENTS = ("timeout_then_ban", "timeout", "ban", "delete_only")


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
                timeout_seconds INTEGER NOT NULL DEFAULT 300,
                ban_after INTEGER NOT NULL DEFAULT 5,
                trigger_after INTEGER NOT NULL DEFAULT 1,
                punishment_mode TEXT NOT NULL DEFAULT 'timeout_then_ban',
                decay_seconds INTEGER NOT NULL DEFAULT 600,
                delete_trigger INTEGER NOT NULL DEFAULT 1,
                ignore_bots INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS rules (
                guild_id INTEGER NOT NULL,
                rule TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                threshold INTEGER NOT NULL,
                window_seconds INTEGER NOT NULL,
                PRIMARY KEY(guild_id, rule)
            );
            CREATE TABLE IF NOT EXISTS link_filters (
                guild_id INTEGER NOT NULL,
                link_type TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(guild_id, link_type)
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
            CREATE TABLE IF NOT EXISTS whitelist_channels (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                PRIMARY KEY(guild_id, channel_id)
            );
            CREATE TABLE IF NOT EXISTS blocked_words (
                guild_id INTEGER NOT NULL,
                word TEXT NOT NULL,
                PRIMARY KEY(guild_id, word)
            );
            CREATE TABLE IF NOT EXISTS allowed_domains (
                guild_id INTEGER NOT NULL,
                domain TEXT NOT NULL,
                PRIMARY KEY(guild_id, domain)
            );
            CREATE TABLE IF NOT EXISTS violations (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                count INTEGER NOT NULL,
                last_violation INTEGER NOT NULL,
                PRIMARY KEY(guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                rule TEXT NOT NULL,
                punishment TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 0,
                detail TEXT,
                timestamp INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_automod_incidents ON incidents(guild_id, timestamp DESC);
            """
        )
        settings_cols = {row[1] for row in db.execute("PRAGMA table_info(settings)")}
        migrations = {
            "timeout_seconds": "ALTER TABLE settings ADD COLUMN timeout_seconds INTEGER NOT NULL DEFAULT 300",
            "ban_after": "ALTER TABLE settings ADD COLUMN ban_after INTEGER NOT NULL DEFAULT 5",
            "trigger_after": "ALTER TABLE settings ADD COLUMN trigger_after INTEGER NOT NULL DEFAULT 1",
            "punishment_mode": "ALTER TABLE settings ADD COLUMN punishment_mode TEXT NOT NULL DEFAULT 'timeout_then_ban'",
            "decay_seconds": "ALTER TABLE settings ADD COLUMN decay_seconds INTEGER NOT NULL DEFAULT 600",
            "delete_trigger": "ALTER TABLE settings ADD COLUMN delete_trigger INTEGER NOT NULL DEFAULT 1",
            "ignore_bots": "ALTER TABLE settings ADD COLUMN ignore_bots INTEGER NOT NULL DEFAULT 1",
        }
        for column, sql in migrations.items():
            if column not in settings_cols:
                db.execute(sql)


def _ensure(guild_id: int) -> None:
    with connect() as db:
        db.execute("INSERT INTO settings(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING", (guild_id,))
        db.executemany(
            "INSERT INTO rules(guild_id,rule,enabled,threshold,window_seconds) VALUES(?,?,?,?,?) "
            "ON CONFLICT(guild_id,rule) DO NOTHING",
            [(guild_id, rule, int(enabled), threshold, window) for rule, (enabled, threshold, window) in DEFAULTS.items()],
        )
        db.executemany(
            "INSERT INTO link_filters(guild_id,link_type,enabled) VALUES(?,?,?) "
            "ON CONFLICT(guild_id,link_type) DO NOTHING",
            [(guild_id, kind, int(enabled)) for kind, enabled in DEFAULT_LINK_FILTERS.items()],
        )


def get_settings(guild_id: int) -> dict:
    _ensure(guild_id)
    with connect() as db:
        settings = dict(db.execute("SELECT * FROM settings WHERE guild_id=?", (guild_id,)).fetchone())
        rows = db.execute("SELECT * FROM rules WHERE guild_id=?", (guild_id,)).fetchall()
    for row in rows:
        rule = row["rule"]
        settings[f"rule_{rule}_enabled"] = bool(row["enabled"])
        settings[f"rule_{rule}_threshold"] = int(row["threshold"])
        settings[f"rule_{rule}_window"] = int(row["window_seconds"])
    # Keep the exact keys used by the existing dashboard/API.
    aliases = {
        "spam": ("count", "window"),
        "duplicate": ("count", "window"),
        "mentions": ("max", None),
        "caps": ("percent", "min_length"),
    }
    for rule, (first, second) in aliases.items():
        settings[f"rule_{rule}_{'max' if first == 'max' else first}"] = settings[f"rule_{rule}_threshold"]
        if second:
            settings[f"rule_{rule}_{second}"] = settings[f"rule_{rule}_window"]
    return settings


def _update(guild_id: int, **fields) -> None:
    _ensure(guild_id)
    allowed = {"enabled", "log_channel_id", "timeout_seconds", "ban_after", "trigger_after", "punishment_mode", "decay_seconds", "delete_trigger", "ignore_bots"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    assignments = ",".join(f"{k}=?" for k in fields)
    with connect() as db:
        db.execute(f"UPDATE settings SET {assignments} WHERE guild_id=?", [*fields.values(), guild_id])


def set_enabled(guild_id, enabled): _update(guild_id, enabled=int(bool(enabled)))
def set_log_channel(guild_id, channel_id): _update(guild_id, log_channel_id=channel_id)


def set_escalation(guild_id, timeout_seconds=None, ban_after=None, decay_seconds=None, trigger_after=None, punishment_mode=None, delete_trigger=None, ignore_bots=None):
    fields = {}
    if timeout_seconds is not None: fields["timeout_seconds"] = max(5, min(2419200, int(timeout_seconds)))
    if ban_after is not None: fields["ban_after"] = max(1, min(100, int(ban_after)))
    if decay_seconds is not None: fields["decay_seconds"] = max(10, min(86400, int(decay_seconds)))
    if trigger_after is not None: fields["trigger_after"] = max(1, min(50, int(trigger_after)))
    if punishment_mode is not None:
        punishment_mode = str(punishment_mode).lower()
        if punishment_mode not in VALID_PUNISHMENTS: raise ValueError("Invalid punishment mode")
        fields["punishment_mode"] = punishment_mode
    if delete_trigger is not None: fields["delete_trigger"] = int(bool(delete_trigger))
    if ignore_bots is not None: fields["ignore_bots"] = int(bool(ignore_bots))
    _update(guild_id, **fields)


def validate_rule(rule):
    if rule not in RULES: raise ValueError(f"Invalid AutoMod rule: {rule}")


def set_rule(guild_id, rule, enabled=None, threshold=None, window_seconds=None):
    validate_rule(rule); _ensure(guild_id)
    fields = {}
    if enabled is not None: fields["enabled"] = int(bool(enabled))
    if threshold is not None: fields["threshold"] = max(1, min(1000, int(threshold)))
    if window_seconds is not None: fields["window_seconds"] = max(1, min(86400, int(window_seconds)))
    if not fields: return
    assignments = ",".join(f"{k}=?" for k in fields)
    with connect() as db: db.execute(f"UPDATE rules SET {assignments} WHERE guild_id=? AND rule=?", [*fields.values(), guild_id, rule])


def set_rule_enabled(guild_id, rule, enabled): set_rule(guild_id, rule, enabled=enabled)
def set_spam_params(guild_id, count, window): set_rule(guild_id, "spam", threshold=count, window_seconds=window)
def set_duplicate_params(guild_id, count, window): set_rule(guild_id, "duplicate", threshold=count, window_seconds=window)
def set_mentions_params(guild_id, max_mentions): set_rule(guild_id, "mentions", threshold=max_mentions)
def set_caps_params(guild_id, percent, min_length): set_rule(guild_id, "caps", threshold=percent, window_seconds=min_length)


def get_link_filters(guild_id):
    _ensure(guild_id)
    with connect() as db: return {r["link_type"]: bool(r["enabled"]) for r in db.execute("SELECT link_type,enabled FROM link_filters WHERE guild_id=?", (guild_id,))}


def set_link_filter(guild_id, link_type, enabled):
    if link_type not in LINK_TYPES: raise ValueError("Invalid link filter")
    _ensure(guild_id)
    with connect() as db: db.execute("UPDATE link_filters SET enabled=? WHERE guild_id=? AND link_type=?", (int(bool(enabled)), guild_id, link_type))


def _wl(table, column, guild_id, value, add):
    with connect() as db:
        if add: db.execute(f"INSERT OR IGNORE INTO {table}(guild_id,{column}) VALUES(?,?)", (guild_id, int(value)))
        else: db.execute(f"DELETE FROM {table} WHERE guild_id=? AND {column}=?", (guild_id, int(value)))

def add_whitelisted_user(guild_id, value): _wl("whitelist_users", "user_id", guild_id, value, True)
def remove_whitelisted_user(guild_id, value): _wl("whitelist_users", "user_id", guild_id, value, False)
def add_whitelisted_role(guild_id, value): _wl("whitelist_roles", "role_id", guild_id, value, True)
def remove_whitelisted_role(guild_id, value): _wl("whitelist_roles", "role_id", guild_id, value, False)
def add_whitelisted_channel(guild_id, value): _wl("whitelist_channels", "channel_id", guild_id, value, True)
def remove_whitelisted_channel(guild_id, value): _wl("whitelist_channels", "channel_id", guild_id, value, False)

def list_whitelisted_users(guild_id):
    with connect() as db: return [r[0] for r in db.execute("SELECT user_id FROM whitelist_users WHERE guild_id=? ORDER BY user_id", (guild_id,))]
def list_whitelisted_roles(guild_id):
    with connect() as db: return [r[0] for r in db.execute("SELECT role_id FROM whitelist_roles WHERE guild_id=? ORDER BY role_id", (guild_id,))]
def list_whitelisted_channels(guild_id):
    with connect() as db: return [r[0] for r in db.execute("SELECT channel_id FROM whitelist_channels WHERE guild_id=? ORDER BY channel_id", (guild_id,))]


def add_filter_word(guild_id, word):
    word = str(word).strip().casefold()
    if not word or len(word) > 64: raise ValueError("Word/phrase must be 1–64 characters")
    with connect() as db: db.execute("INSERT OR IGNORE INTO blocked_words VALUES(?,?)", (guild_id, word))

def remove_filter_word(guild_id, word):
    word = str(word).strip().casefold()
    with connect() as db: db.execute("DELETE FROM blocked_words WHERE guild_id=? AND word=?", (guild_id, word))

def list_filter_words(guild_id):
    with connect() as db: return [r[0] for r in db.execute("SELECT word FROM blocked_words WHERE guild_id=? ORDER BY word", (guild_id,))]


def _normal_domain(value: str) -> str:
    value = str(value).strip().lower()
    if "://" not in value: value = "https://" + value
    from urllib.parse import urlsplit
    host = urlsplit(value).hostname or ""
    return host.removeprefix("www.")


def add_allowed_domain(guild_id, domain):
    host = _normal_domain(domain)
    if "." not in host or len(host) > 253: raise ValueError("Enter a valid domain")
    with connect() as db: db.execute("INSERT OR IGNORE INTO allowed_domains VALUES(?,?)", (guild_id, host))

def remove_allowed_domain(guild_id, domain):
    host = _normal_domain(domain)
    with connect() as db: db.execute("DELETE FROM allowed_domains WHERE guild_id=? AND domain=?", (guild_id, host))

def list_allowed_domains(guild_id):
    with connect() as db: return [r[0] for r in db.execute("SELECT domain FROM allowed_domains WHERE guild_id=? ORDER BY domain", (guild_id,))]


def register_violation(guild_id, user_id, decay):
    now = int(time.time())
    decay = max(1, int(decay))
    with connect() as db:
        row = db.execute("SELECT count,last_violation FROM violations WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
        count = 0 if not row or now - int(row["last_violation"]) > decay else int(row["count"])
        count += 1
        db.execute(
            "INSERT INTO violations(guild_id,user_id,count,last_violation) VALUES(?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET count=excluded.count,last_violation=excluded.last_violation",
            (guild_id, user_id, count, now),
        )
        return count


def reset_violation(guild_id, user_id):
    with connect() as db: db.execute("DELETE FROM violations WHERE guild_id=? AND user_id=?", (guild_id, user_id))

def get_violation_count(guild_id, user_id):
    with connect() as db:
        row = db.execute("SELECT count FROM violations WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
        return int(row[0]) if row else 0


def add_incident(guild_id, user_id, rule, punishment, timestamp=None, success=False, detail=""):
    with connect() as db:
        db.execute("INSERT INTO incidents(guild_id,user_id,rule,punishment,success,detail,timestamp) VALUES(?,?,?,?,?,?,?)", (guild_id, user_id, rule, punishment, int(bool(success)), (detail or "")[:1500], int(timestamp or time.time())))

def get_incidents(guild_id, limit=50):
    with connect() as db: return db.execute("SELECT * FROM incidents WHERE guild_id=? ORDER BY timestamp DESC LIMIT ?", (guild_id, max(1, min(500, int(limit))))).fetchall()

def cleanup_incidents(guild_id, keep=500):
    keep = max(50, min(2000, int(keep)))
    with connect() as db: db.execute("DELETE FROM incidents WHERE guild_id=? AND id NOT IN (SELECT id FROM incidents WHERE guild_id=? ORDER BY timestamp DESC LIMIT ?)", (guild_id, guild_id, keep))
