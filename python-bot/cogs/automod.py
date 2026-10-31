# Credits: gogeta_gg
"""Gogeta AutoMod v3.

Self-contained interaction-first AutoMod rewrite. It intentionally does not
use the old AdminView/require mixins. Configuration is persisted in the
existing automod_v2.db file under new namespaced tables, with migration of
legacy v2 settings/filter data on first use.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
import time
import unicodedata
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import discord
from discord import app_commands
from discord.ext import commands
from ui.emoji import E, bind_view_emojis

DB_PATH = Path(__file__).resolve().parent / "automod_v2.db"
CACHE_TTL = 5.0
MAX_HISTORY = 80
WARN_DELETE_AFTER = 8.0

# Discord-native AutoMod mirrors the two highest-value defenses so protection
# still works even when Discord withholds message content from the Gateway.
# The local detectors remain authoritative for the richer rule set.
NATIVE_INVITE_RULE = "Gogeta • Invite Shield"
NATIVE_SPAM_RULE = "Gogeta • Spam Shield"
NATIVE_MENTION_RULE = "Gogeta • Mention Shield"
NATIVE_RULE_MARKER = "Gogeta AutoMod v6"

ACTIONS = ("log_only", "delete", "warn", "timeout", "quarantine", "kick", "ban")
RULES: dict[str, dict[str, object]] = {
    "rapid_spam": {"label":"Rapid Spam","threshold":6,"window":8,"action":"delete","weight":1},
    "duplicate": {"label":"Duplicate Flood","threshold":3,"window":10,"action":"delete","weight":1},
    "mass_mentions": {"label":"Mass Mentions","threshold":6,"window":1,"action":"timeout","weight":2},
    "discord_invites": {"label":"Discord Invites","threshold":1,"window":1,"action":"delete","weight":1},
    "links": {"label":"Links","threshold":1,"window":1,"action":"delete","weight":1},
    "caps": {"label":"Excessive Caps","threshold":75,"window":12,"action":"warn","weight":1},
    "emoji_flood": {"label":"Emoji Flood","threshold":14,"window":1,"action":"delete","weight":1},
    "zalgo": {"label":"Zalgo / Combining Flood","threshold":10,"window":1,"action":"delete","weight":1},
    "blocked_words": {"label":"Blocked Words","threshold":1,"window":1,"action":"timeout","weight":2},
    "repeated_chars": {"label":"Repeated Characters","threshold":8,"window":1,"action":"delete","weight":1},
    "newline_flood": {"label":"Line Flood","threshold":18,"window":1,"action":"delete","weight":1},
    "attachment_flood": {"label":"Attachment Flood","threshold":3,"window":10,"action":"delete","weight":1},
    "message_length": {"label":"Oversized Message","threshold":3000,"window":1,"action":"delete","weight":1},
    "markdown_flood": {"label":"Markdown Flood","threshold":25,"window":1,"action":"delete","weight":1},
    "invisible_chars": {"label":"Invisible Character Flood","threshold":10,"window":1,"action":"delete","weight":1},
    "everyone_here": {"label":"@everyone / @here Ping","threshold":1,"window":1,"action":"timeout","weight":2},
}

RULE_LISTENERS: dict[str, tuple[str, ...]] = {
    "rapid_spam": ("on_message",), "duplicate": ("on_message",), "mass_mentions": ("on_message",),
    "discord_invites": ("on_message",), "links": ("on_message",), "caps": ("on_message",),
    "emoji_flood": ("on_message",), "zalgo": ("on_message",), "blocked_words": ("on_message",),
    "repeated_chars": ("on_message",), "newline_flood": ("on_message",), "attachment_flood": ("on_message",),
    "message_length": ("on_message",), "markdown_flood": ("on_message",), "invisible_chars": ("on_message",),
    "everyone_here": ("on_message",),
}

URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>()]+", re.I)
INVITE_RE = re.compile(r"(?:discord(?:app)?\.com/invite|discord\.gg)/[\w-]+", re.I)
OBFUSCATED_INVITE_RE = re.compile(
    r"discord\s*(?:\[\s*(?:\.|dot)\s*\]|\(\s*(?:\.|dot)\s*\)|\.\s*dot\b)\s*(?:gg|com|app)"
    r"(?:\s*(?:/|\[\s*(?:/|slash)\s*\]|dot)\s*(?:invite\s*)?)?",
    re.I,
)
EMOJI_RE = re.compile(r"<a?:\w+:\d+>|[\U0001F300-\U0001FAFF\U00002600-\U000027BF]", re.U)
ZALGO_RE = re.compile(r"[\u0300-\u036f\u0489\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\u2de0-\u2dff\ua66f\ua670-\ua672\ufe20-\ufe2f]")
INVISIBLE_RE = re.compile(r"[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f\u2800\u3000\ufeff]")
MARKDOWN_RE = re.compile(r"[`*_~|>#-]")
REPEAT_RE = re.compile(r"(.)\1{7,}", re.S)

# ---- link / invite detection (hardened) -----------------------------------
# Everything invisible or purely decorative is stripped before link scanning so
# "discord.gg/\u200babc" or "disc\u200bord.gg/abc" cannot slip through.
_FOLD_STRIP_RE = re.compile(
    r"[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180e\u200b-\u200f\u202a-\u202e"
    r"\u2060-\u206f\u2800\u3164\ufe00-\ufe0f\ufeff]|[\u0300-\u036f]"
)
_DEOBF_DOT_RE = re.compile(r"\s*(?:\[\s*(?:\.|dot)\s*\]|\(\s*(?:\.|dot)\s*\)|\{\s*(?:\.|dot)\s*\}|<\s*(?:\.|dot)\s*>|\bdot\b|\u3002|\uff0e)\s*", re.I)
_DEOBF_SLASH_RE = re.compile(r"\s*(?:\[\s*(?:/|slash)\s*\]|\(\s*(?:/|slash)\s*\)|\bslash\b|\uff0f)\s*", re.I)
_INVITE_PATTERNS = (
    re.compile(r"(?:discord(?:app)?|dsc|invite)\.gg/+[\w-]{2,}", re.I),
    re.compile(r"discord(?:app)?\.com/+invite/+[\w-]{2,}", re.I),
    re.compile(r"discord\.(?:me|io|link|li|plus)/+[\w-]{2,}", re.I),
    re.compile(r"(?:top|disboard)\.gg/+(?:servers|server)/+\d{5,}", re.I),
)
URL_SCHEME_RE = re.compile(r"(?:(?:h(?:tt|xx|\*\*|--)ps?|ftp)://|www\.)[^\s<>()\[\]{}]+", re.I)
_STRONG_TLDS = (
    "com|net|org|io|gg|xyz|info|biz|tv|cc|app|dev|gl|ly|ru|cn|tk|ml|ga|cf|gq|site|online|live|shop|"
    "store|club|link|click|fun|icu|vip|pw|ws|gift|lol|uk|eu|su|top|cyou|rest|monster|buzz|quest|cam"
)
# Looks-like-a-filename TLDs (.sh .zip .mov .ai ...) and short country codes that collide with
# typos ("fine.so") only count when the token also has a /path.
_ANY_TLDS = _STRONG_TLDS + (
    "|sh|ai|art|page|zip|mov|work|win|bid|loan|men|date|world|today|cloud|digital|ngrok|co|me|to|in|it|"
    "be|at|so|us|de|fr|nl|br|jp|kr|ca|au|es|pl|ch|one|is|id|ir|ua|tr"
)
BARE_STRONG_RE = re.compile(
    rf"(?<![\w@./:-])(?:[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?\.)+(?:{_STRONG_TLDS})(?::\d{{2,5}})?(?:/[^\s<>()\[\]{{}}]*)?(?![\w@-])",
    re.I,
)
BARE_PATH_RE = re.compile(
    rf"(?<![\w@./:-])(?:[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?\.)+(?:{_ANY_TLDS})(?::\d{{2,5}})?/[^\s<>()\[\]{{}}]+",
    re.I,
)
IP_URL_RE = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?::\d{2,5})?(?:/[^\s<>()\[\]{}]*)?(?![\w.])")


def fold_text(value: str) -> str:
    """NFKC-fold and strip invisible/combining characters (link scanning only)."""
    return _FOLD_STRIP_RE.sub("", unicodedata.normalize("NFKC", value or ""))


def _variants(value: str) -> list[str]:
    folded = fold_text(value)
    deobf = _DEOBF_SLASH_RE.sub("/", _DEOBF_DOT_RE.sub(".", folded))
    squashed = re.sub(r"\s+", "", deobf)
    out: list[str] = []
    for item in (folded, deobf, squashed):
        if item and item not in out:
            out.append(item)
    return out


def has_invite(value: str) -> bool:
    return any(p.search(v) for v in _variants(value) for p in _INVITE_PATTERNS)


def find_links(value: str) -> list[str]:
    """Return every URL-looking token (scheme, www., bare domain, IP)."""
    found: list[str] = []
    seen: set[str] = set()
    for variant in _variants(value)[:2]:  # squashed text is for invites only
        for regex in (URL_SCHEME_RE, BARE_STRONG_RE, BARE_PATH_RE, IP_URL_RE):
            for match in regex.finditer(variant):
                token = match.group(0).rstrip(".,;:!?'\"*_~|")
                if token and token.lower() not in seen:
                    seen.add(token.lower())
                    found.append(token)
    return found


def message_text(message: "discord.Message") -> str:
    parts = [message.content or ""]
    for snap in (getattr(message, "message_snapshots", None) or []):
        text = getattr(snap, "content", "") or ""
        if text:
            parts.append(text)
    return "\n".join(p for p in parts if p)

RULE_LABELS = {k: str(v["label"]) for k, v in RULES.items()}
LINK_POLICIES = ("block_all", "block_configured", "allow_all")


def link_kind(raw: str) -> str:
    h = host(raw)
    path = raw.lower().split("?", 1)[0]
    if "discord.gg/" in raw.lower() or "discord.com/invite/" in raw.lower() or "discordapp.com/invite/" in raw.lower(): return "discord_invites"
    if h in {"youtube.com", "youtu.be", "m.youtube.com"} or h.endswith(".youtube.com"): return "youtube"
    if h.endswith(("giphy.com", "tenor.com")) or path.endswith((".gif", ".gifv")): return "gifs"
    if path.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".svg", ".avif", ".jpeg")): return "images"
    if h.endswith("tiktok.com"): return "tiktok"
    if h.endswith("instagram.com"): return "instagram"
    if h.endswith("twitch.tv"): return "twitch"
    if h.endswith(("reddit.com", "redd.it")): return "reddit"
    if h in {"twitter.com", "x.com", "mobile.twitter.com"} or h.endswith(".x.com"): return "twitter"
    return "external"


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"\s+", " ", "".join(c if c.isalnum() or c.isspace() else " " for c in value)).strip()


def word_pattern(word: str) -> re.Pattern[str]:
    value = re.escape(normalize(word)).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<!\w){value}(?!\w)", re.I)


def host(raw: str) -> str:
    try:
        value = raw if raw.startswith(("http://","https://")) else "https://" + raw
        return (urlsplit(value).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def colour(enabled: bool) -> int:
    return 0x57F287 if enabled else 0x747F8D


def embed(title: str, description: str = "", c: int = 0x5865F2) -> discord.Embed:
    e=discord.Embed(title=title,description=description,colour=c,timestamp=discord.utils.utcnow()); e.set_footer(text="Gogeta Security Suite • AutoMod v3"); return e


def check_line(name: str, ok: bool, detail: str = "") -> str:
    return f"{'✅' if ok else '❌'} **{name}**{(' — '+detail) if detail else ''}"


class AMDB:
    def __init__(self)->None:self.setup()
    def db(self)->sqlite3.Connection:
        c=sqlite3.connect(DB_PATH,timeout=10); c.row_factory=sqlite3.Row; c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=5000"); return c
    def setup(self)->None:
        with self.db() as db:
            had_meta=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='am_meta'").fetchone()
            has_settings=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='am_settings'").fetchone()
            db.executescript("""
            CREATE TABLE IF NOT EXISTS am_settings(
                guild_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, log_channel_id INTEGER,
                default_action TEXT NOT NULL DEFAULT 'delete', timeout_seconds INTEGER NOT NULL DEFAULT 300,
                trigger_after INTEGER NOT NULL DEFAULT 1, ban_after INTEGER NOT NULL DEFAULT 5,
                strike_decay INTEGER NOT NULL DEFAULT 900, delete_trigger INTEGER NOT NULL DEFAULT 1,
                ignore_bots INTEGER NOT NULL DEFAULT 1, mention_limit INTEGER NOT NULL DEFAULT 6,
                link_policy TEXT NOT NULL DEFAULT 'block_all', max_content_length INTEGER NOT NULL DEFAULT 3000,
                quarantine_role_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS am_rules(
                guild_id INTEGER NOT NULL, rule TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                threshold INTEGER NOT NULL, window_seconds INTEGER NOT NULL, action TEXT NOT NULL DEFAULT 'inherit',
                weight INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(guild_id,rule)
            );
            CREATE TABLE IF NOT EXISTS am_links(guild_id INTEGER NOT NULL, kind TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(guild_id,kind));
            CREATE TABLE IF NOT EXISTS am_words(guild_id INTEGER NOT NULL, word TEXT NOT NULL, PRIMARY KEY(guild_id,word));
            CREATE TABLE IF NOT EXISTS am_allowed_domains(guild_id INTEGER NOT NULL, domain TEXT NOT NULL, PRIMARY KEY(guild_id,domain));
            CREATE TABLE IF NOT EXISTS am_blocked_domains(guild_id INTEGER NOT NULL, domain TEXT NOT NULL, PRIMARY KEY(guild_id,domain));
            CREATE TABLE IF NOT EXISTS am_trust(guild_id INTEGER NOT NULL, kind TEXT NOT NULL, target_id INTEGER NOT NULL, PRIMARY KEY(guild_id,kind,target_id));
            CREATE TABLE IF NOT EXISTS am_strikes(guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, score INTEGER NOT NULL, last_at INTEGER NOT NULL, PRIMARY KEY(guild_id,user_id));
            CREATE TABLE IF NOT EXISTS am_incidents(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER NOT NULL,user_id INTEGER NOT NULL,rule TEXT NOT NULL,action TEXT NOT NULL,strike INTEGER NOT NULL,success INTEGER NOT NULL,detail TEXT,timestamp INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_am_incidents ON am_incidents(guild_id,timestamp DESC);
            CREATE TABLE IF NOT EXISTS am_meta(key TEXT PRIMARY KEY, value TEXT);
            """)
            if not had_meta and has_settings:
                db.execute("INSERT OR IGNORE INTO am_meta(key,value) SELECT 'legacy_import:'||guild_id,'1' FROM am_settings")
            # One-time: the old default ('block_configured' + only the invite class armed) never
            # blocked ordinary links, so every guild still on that untouched default is upgraded.
            if not db.execute("SELECT 1 FROM am_meta WHERE key='link_policy_v2'").fetchone():
                db.execute("UPDATE am_settings SET link_policy='block_all' WHERE link_policy='block_configured'")
                db.execute("INSERT INTO am_meta(key,value) VALUES('link_policy_v2','1')")
    def ensure(self,guild_id:int)->None:
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO am_settings(guild_id,link_policy) VALUES(?,'block_all')",(guild_id,))
            db.executemany("INSERT OR IGNORE INTO am_rules(guild_id,rule,enabled,threshold,window_seconds,action,weight) VALUES(?,?,?,?,?,?,?)",[(guild_id,n,1,int(v['threshold']),int(v['window']),str(v['action']),int(v['weight'])) for n,v in RULES.items()])
            db.executemany("INSERT OR IGNORE INTO am_links(guild_id,kind,enabled) VALUES(?,?,?)",[(guild_id,k,1 if k in ('discord_invites',) else 0) for k in ('youtube','discord_invites','gifs','images','tiktok','instagram','twitch','reddit','twitter','external')])
            # Legacy (v2 dashboard tables) import. It MUST run exactly once per guild: the previous
            # version re-ran on every cache refresh, which silently reverted rule edits and
            # re-added every word / trusted user / trusted role the admin had removed.
            marker=f'legacy_import:{guild_id}'
            if db.execute("SELECT 1 FROM am_meta WHERE key=?",(marker,)).fetchone():return
            db.execute("INSERT OR IGNORE INTO am_meta(key,value) VALUES(?,'1')",(marker,))
            old=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'").fetchone()
            if not old:return
            oldrow=db.execute("SELECT enabled,log_channel_id,timeout_seconds,ban_after,trigger_after,punishment_mode,decay_seconds,delete_trigger,ignore_bots FROM settings WHERE guild_id=?",(guild_id,)).fetchone()
            if oldrow:
                legacy_action={'delete_only':'delete','timeout':'timeout','ban':'ban','timeout_then_ban':'timeout'}.get(str(oldrow[5]),'delete')
                db.execute("UPDATE am_settings SET enabled=?,log_channel_id=?,timeout_seconds=?,ban_after=?,trigger_after=?,strike_decay=?,delete_trigger=?,ignore_bots=?,default_action=? WHERE guild_id=? AND enabled=0 AND log_channel_id IS NULL",(oldrow[0],oldrow[1],oldrow[2],oldrow[3],oldrow[4],oldrow[6],oldrow[7],oldrow[8],legacy_action,guild_id))
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='blocked_words'").fetchone():
                rows=db.execute("SELECT word FROM blocked_words WHERE guild_id=?",(guild_id,)).fetchall(); db.executemany("INSERT OR IGNORE INTO am_words(guild_id,word) VALUES(?,?)",[(guild_id,r[0]) for r in rows])
            for table,kind,col in (("whitelist_users","user","user_id"),("whitelist_roles","role","role_id"),("whitelist_channels","channel","channel_id")):
                if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                    rows=db.execute(f"SELECT {col} FROM {table} WHERE guild_id=?",(guild_id,)).fetchall(); db.executemany("INSERT OR IGNORE INTO am_trust(guild_id,kind,target_id) VALUES(?,?,?)",[(guild_id,kind,int(r[0])) for r in rows])
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='allowed_domains'").fetchone():
                rows=db.execute("SELECT domain FROM allowed_domains WHERE guild_id=?",(guild_id,)).fetchall(); db.executemany("INSERT OR IGNORE INTO am_allowed_domains(guild_id,domain) VALUES(?,?)",[(guild_id,r[0]) for r in rows])
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rules'").fetchone():
                rows=db.execute("SELECT rule,enabled,threshold,window_seconds FROM rules WHERE guild_id=?",(guild_id,)).fetchall()
                mapping={'spam':'rapid_spam','duplicate':'duplicate','mentions':'mass_mentions','invites':'discord_invites','caps':'caps','emoji_spam':'emoji_flood','zalgo':'zalgo','bad_words':'blocked_words','links':'links','attachments':'attachment_flood','newlines':'newline_flood'}
                for r in rows:
                    if r[0] in mapping:
                        win=int(r[3]) if int(r[3])>0 else int(RULES[mapping[r[0]]]['window'])
                        db.execute("UPDATE am_rules SET enabled=?,threshold=?,window_seconds=? WHERE guild_id=? AND rule=?",(r[1],r[2],win,guild_id,mapping[r[0]]))
    def settings(self,guild_id:int)->dict:self.ensure(guild_id); return self._one("SELECT * FROM am_settings WHERE guild_id=?",(guild_id,))
    def _one(self,q,args=()):
        with self.db() as db:return dict(db.execute(q,args).fetchone())
    def update_settings(self,guild_id:int,**fields:object)->None:
        self.ensure(guild_id); allowed={'enabled','log_channel_id','default_action','timeout_seconds','trigger_after','ban_after','strike_decay','delete_trigger','ignore_bots','mention_limit','link_policy','max_content_length','quarantine_role_id'}; clean={k:v for k,v in fields.items() if k in allowed}
        if clean:
            with self.db() as db:db.execute(f"UPDATE am_settings SET {','.join(f'{k}=?' for k in clean)} WHERE guild_id=?",[*clean.values(),guild_id])
    def rules(self,guild_id:int)->dict[str,dict]:
        self.ensure(guild_id)
        with self.db() as db:return {r['rule']:dict(r) for r in db.execute("SELECT * FROM am_rules WHERE guild_id=?",(guild_id,))}
    def rule(self,guild_id:int,rule:str)->dict:
        """Return one detector row by key for the sequential deployment path."""
        self.ensure(guild_id)
        with self.db() as db:
            row=db.execute("SELECT * FROM am_rules WHERE guild_id=? AND rule=?",(guild_id,rule)).fetchone()
        if row is None:
            raise KeyError(f"Unknown AutoMod detector: {rule}")
        return dict(row)
    def update_rule(self,guild_id:int,rule:str,**fields:object)->None:
        self.ensure(guild_id); allowed={'enabled','threshold','window_seconds','action','weight'}; clean={k:v for k,v in fields.items() if k in allowed}
        if clean:
            with self.db() as db:db.execute(f"UPDATE am_rules SET {','.join(f'{k}=?' for k in clean)} WHERE guild_id=? AND rule=?",[*clean.values(),guild_id,rule])
    def toggles(self,guild_id:int)->dict[str,bool]:
        self.ensure(guild_id)
        with self.db() as db:return {r['kind']:bool(r['enabled']) for r in db.execute("SELECT kind,enabled FROM am_links WHERE guild_id=?",(guild_id,))}
    def toggle_link(self,guild_id:int,kind:str,enabled:bool)->None:
        with self.db() as db:db.execute("INSERT INTO am_links(guild_id,kind,enabled) VALUES(?,?,?) ON CONFLICT(guild_id,kind) DO UPDATE SET enabled=excluded.enabled",(guild_id,kind,int(enabled)))
    def list_table(self,table:str,guild_id:int,column:str)->list[str]:
        with self.db() as db:return [r[0] for r in db.execute(f"SELECT {column} FROM {table} WHERE guild_id=? ORDER BY {column}",(guild_id,))]
    def add_value(self,table:str,column:str,guild_id:int,value:str)->None:
        with self.db() as db:db.execute(f"INSERT OR IGNORE INTO {table}(guild_id,{column}) VALUES(?,?)",(guild_id,str(value).strip().casefold()))
    def remove_value(self,table:str,column:str,guild_id:int,value:str)->None:
        with self.db() as db:db.execute(f"DELETE FROM {table} WHERE guild_id=? AND {column}=?",(guild_id,str(value).strip().casefold()))
    def trust(self,guild_id:int,kind:str,target:int,add:bool)->None:
        with self.db() as db:
            if add:db.execute("INSERT OR IGNORE INTO am_trust(guild_id,kind,target_id) VALUES(?,?,?)",(guild_id,kind,target))
            else:db.execute("DELETE FROM am_trust WHERE guild_id=? AND kind=? AND target_id=?",(guild_id,kind,target))
    def trust_sets(self,guild_id:int)->dict[str,set[int]]:
        with self.db() as db:rows=db.execute("SELECT kind,target_id FROM am_trust WHERE guild_id=?",(guild_id,)).fetchall()
        out=defaultdict(set)
        for r in rows:out[r['kind']].add(int(r['target_id']))
        return out
    def strike(self,guild_id:int,user_id:int,weight:int,decay:int)->int:
        now=int(time.time())
        with self.db() as db:
            row=db.execute("SELECT score,last_at FROM am_strikes WHERE guild_id=? AND user_id=?",(guild_id,user_id)).fetchone(); score=0 if not row or now-int(row['last_at'])>decay else int(row['score']); score+=weight
            db.execute("INSERT INTO am_strikes(guild_id,user_id,score,last_at) VALUES(?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET score=excluded.score,last_at=excluded.last_at",(guild_id,user_id,score,now)); return score
    def clear_strike(self,guild_id:int,user_id:int)->None:
        with self.db() as db:db.execute("DELETE FROM am_strikes WHERE guild_id=? AND user_id=?",(guild_id,user_id))
    def incident(self,guild_id:int,user_id:int,rule:str,action:str,strike:int,success:bool,detail:str)->None:
        with self.db() as db:
            db.execute("INSERT INTO am_incidents(guild_id,user_id,rule,action,strike,success,detail,timestamp) VALUES(?,?,?,?,?,?,?,?)",(guild_id,user_id,rule,action,strike,int(success),str(detail)[:1500],int(time.time())))
            db.execute("DELETE FROM am_incidents WHERE guild_id=? AND id NOT IN (SELECT id FROM am_incidents WHERE guild_id=? ORDER BY timestamp DESC LIMIT 1000)",(guild_id,guild_id))
    def incidents(self,guild_id:int,limit:int=12):
        with self.db() as db:return db.execute("SELECT * FROM am_incidents WHERE guild_id=? ORDER BY timestamp DESC, id DESC LIMIT ?",(guild_id,max(1,min(100,int(limit))))).fetchall()


class GlobalPolicyModal(discord.ui.Modal,title="AutoMod • Global Policy"):
    action=discord.ui.TextInput(label="Default action",placeholder="delete / warn / timeout / kick / ban / log_only",max_length=20)
    timeout=discord.ui.TextInput(label="Timeout seconds",placeholder="300",max_length=7)
    trigger=discord.ui.TextInput(label="Strike trigger",placeholder="1",max_length=3)
    ban_after=discord.ui.TextInput(label="Ban after strikes",placeholder="5",max_length=3)
    decay=discord.ui.TextInput(label="Strike decay seconds",placeholder="900",max_length=6)
    def __init__(self,cog:"Automod",gid:int,view:"AMView")->None:
        super().__init__();self.cog,self.gid,self.view=cog,gid,view;s=cog.settings(gid);self.action.default=str(s['default_action']);self.timeout.default=str(s['timeout_seconds']);self.trigger.default=str(s['trigger_after']);self.ban_after.default=str(s['ban_after']);self.decay.default=str(s['strike_decay'])
    async def on_submit(self,interaction:discord.Interaction)->None:
        try:
            action=str(self.action.value).strip().lower();
            if action not in ACTIONS:raise ValueError("Invalid action.")
            values={"default_action":action,"timeout_seconds":max(5,min(2419200,int(self.timeout.value))),"trigger_after":max(1,min(50,int(self.trigger.value))),"ban_after":max(1,min(100,int(self.ban_after.value))),"strike_decay":max(10,min(86400,int(self.decay.value)))}
        except (ValueError,TypeError) as exc:await interaction.response.send_message(embed=embed("AUTOMOD / INVALID POLICY",str(exc),0xED4245),ephemeral=False);return
        self.cog.db.update_settings(self.gid,**values);self.cog.invalidate(self.gid);self.view.page="policy";self.view.rebuild();await interaction.response.edit_message(embed=self.cog.panel(self.gid,"policy"),view=self.view)


class RuleModal(discord.ui.Modal,title="AutoMod • Rule Editor"):
    enabled=discord.ui.TextInput(label="Enabled?",placeholder="yes / no",max_length=3)
    threshold=discord.ui.TextInput(label="Threshold",placeholder="6",max_length=6)
    window=discord.ui.TextInput(label="Window seconds",placeholder="8",max_length=6)
    action=discord.ui.TextInput(label="Action",placeholder="inherit / delete / warn / timeout / kick / ban / log_only",max_length=20)
    weight=discord.ui.TextInput(label="Strike weight",placeholder="1",max_length=2)
    def __init__(self,cog:"Automod",gid:int,rule:str,view:"AMView")->None:
        super().__init__();self.cog,self.gid,self.rule,self.view=cog,gid,rule,view;r=cog.db.rules(gid)[rule];self.enabled.default='yes' if r['enabled'] else 'no';self.threshold.default=str(r['threshold']);self.window.default=str(r['window_seconds']);self.action.default=str(r['action']);self.weight.default=str(r['weight'])
    async def on_submit(self,interaction:discord.Interaction)->None:
        try:
            action=str(self.action.value).strip().lower();
            if action not in ('inherit',)+ACTIONS:raise ValueError("Invalid action.")
            values={'enabled':str(self.enabled.value).strip().lower() in {'y','yes','on','true','1'},'threshold':max(1,min(100000,int(self.threshold.value))),'window_seconds':max(1,min(86400,int(self.window.value))),'action':action,'weight':max(1,min(10,int(self.weight.value)))}
        except (ValueError,TypeError) as exc:await interaction.response.send_message(embed=embed("AUTOMOD / INVALID RULE",str(exc),0xED4245),ephemeral=False);return
        self.cog.db.update_rule(self.gid,self.rule,**values);self.cog.invalidate(self.gid);self.view.page='rules';self.view.rebuild();await interaction.response.edit_message(embed=self.cog.panel(self.gid,'rules'),view=self.view)


class TextListModal(discord.ui.Modal):
    values=discord.ui.TextInput(label="Entries",placeholder="one per line or comma-separated",style=discord.TextStyle.paragraph,max_length=1500)
    def __init__(self,cog:"Automod",gid:int,kind:str,add:bool,view:"AMView")->None:
        super().__init__(title=f"AutoMod • {'Add' if add else 'Remove'} {kind}");self.cog,self.gid,self.kind,self.add,self.view=cog,gid,kind,add,view
    async def on_submit(self,interaction:discord.Interaction)->None:
        vals=[x.strip() for x in re.split(r"[\n,]",str(self.values.value)) if x.strip()][:100]
        if not vals:await interaction.response.send_message("Provide at least one entry.",ephemeral=False);return
        table,column={'word':('am_words','word'),'allowed_domain':('am_allowed_domains','domain'),'blocked_domain':('am_blocked_domains','domain')}[self.kind]
        for v in vals:
            try:
                h=host(v) if 'domain' in self.kind else v
                if 'domain' in self.kind and (not h or '.' not in h):raise ValueError(f"Invalid domain: {v}")
                (self.cog.db.add_value if self.add else self.cog.db.remove_value)(table,column,self.gid,h)
            except ValueError as exc:await interaction.response.send_message(embed=embed("AUTOMOD / INVALID ENTRY",str(exc),0xED4245),ephemeral=False);return
        self.cog.invalidate(self.gid);self.view.page='filters';self.view.rebuild();await interaction.response.edit_message(embed=self.cog.panel(self.gid,'filters'),view=self.view)


class AMView(discord.ui.View):
    def __init__(self,cog:"Automod",author_id:int,gid:int,page:str='overview')->None:super().__init__(timeout=1200);self.cog,self.author_id,self.gid,self.page=cog,author_id,gid,page;self.rebuild()
    async def interaction_check(self,interaction:discord.Interaction)->bool:
        if interaction.user.id!=self.author_id:await interaction.response.send_message("This AutoMod panel belongs to another administrator.",ephemeral=False);return False
        return True
    def rebuild(self)->None:
        self.clear_items()
        for label,page in (("Overview","overview"),("Rules","rules"),("Policy","policy"),("Filters","filters"),("Logs","logs")):
            b=discord.ui.Button(label=label,style=discord.ButtonStyle.primary if self.page==page else discord.ButtonStyle.secondary,row=0);b.callback=self.nav(page);self.add_item(b)
        if self.page=='overview':
            for label,style,cb in (("Deploy / Repair","success",self.cog.setup_from_panel),("Disable","danger",self.cog.ui_disable),("Save","primary",self.cog.ui_save),("Quick Presets","secondary",self.quick_presets),("Health Check","secondary",self.cog.preflight)):
                b=discord.ui.Button(label=label,style=getattr(discord.ButtonStyle,style),row=1);b.callback=cb;self.add_item(b)
        elif self.page=='rules':
            opts=[discord.SelectOption(label=str(v['label']),value=k) for k,v in RULES.items()];s=discord.ui.Select(placeholder='Select a rule to edit…',min_values=1,max_values=1,options=opts,row=1);s.callback=self.select_rule;self.add_item(s)
            for label,style,cb in (("Arm All","success",self.cog.arm_all),("Disarm All","danger",self.cog.disarm_all)):b=discord.ui.Button(label=label,style=getattr(discord.ButtonStyle,style),row=2);b.callback=cb;self.add_item(b)
        elif self.page=='policy':
            b=discord.ui.Button(label='Edit Policy',style=discord.ButtonStyle.primary,row=1);b.callback=self.edit_policy;self.add_item(b)
            b=discord.ui.Button(label='Quarantine Role',style=discord.ButtonStyle.secondary,row=1);b.callback=self.cog.configure_quarantine_role;self.add_item(b)
            for label,p in (("Balanced","balanced"),("Strict","strict"),("Log Only","observe")):b=discord.ui.Button(label=label,style=discord.ButtonStyle.secondary,row=2);b.callback=self.cog.preset_callback(p,self);self.add_item(b)
        elif self.page=='filters':
            b=discord.ui.Button(label='Words: Add',style=discord.ButtonStyle.primary,row=1);b.callback=self.add_word;self.add_item(b);b=discord.ui.Button(label='Words: Remove',style=discord.ButtonStyle.secondary,row=1);b.callback=self.remove_word;self.add_item(b)
            b=discord.ui.Button(label='Allowed Domains',style=discord.ButtonStyle.primary,row=2);b.callback=self.allowed_domains;self.add_item(b);b=discord.ui.Button(label='Remove Allowed',style=discord.ButtonStyle.secondary,row=2);b.callback=self.remove_allowed_domains;self.add_item(b)
            b=discord.ui.Button(label='Blocked Domains',style=discord.ButtonStyle.secondary,row=2);b.callback=self.blocked_domains;self.add_item(b);b=discord.ui.Button(label='Remove Blocked',style=discord.ButtonStyle.secondary,row=2);b.callback=self.remove_blocked_domains;self.add_item(b)
            opts=[discord.SelectOption(label=k.replace('_',' ').title(),value=k,description='Toggle this link class') for k in self.cog.db.toggles(self.gid)]
            s=discord.ui.Select(placeholder='Toggle link class…',min_values=1,max_values=1,options=opts,row=3);s.callback=self.toggle_link;self.add_item(s)
            b=discord.ui.Button(label='Edit Trust',style=discord.ButtonStyle.primary,row=4);b.callback=self.edit_trust;self.add_item(b)
            b=discord.ui.Button(label='Links: '+str(self.cog.settings(self.gid).get('link_policy','block_all')).replace('_',' ').upper(),style=discord.ButtonStyle.danger,row=4);b.callback=self.cycle_link_policy;self.add_item(b)
            b=discord.ui.Button(label='Ignore Bots: '+('ON' if self.cog.settings(self.gid)['ignore_bots'] else 'OFF'),style=discord.ButtonStyle.secondary,row=4);b.callback=self.toggle_bots;self.add_item(b)
        elif self.page=='logs':
            pass
        b=discord.ui.Button(label='Refresh',style=discord.ButtonStyle.secondary,row=4);b.callback=self.refresh;self.add_item(b)
        bind_view_emojis(self)
    def nav(self,page:str):
        async def cb(interaction:discord.Interaction)->None:self.page=page;self.rebuild();await interaction.response.edit_message(embed=self.cog.panel(self.gid,page),view=self)
        return cb
    async def refresh(self,interaction:discord.Interaction)->None:self.cog.invalidate(self.gid);self.rebuild();await interaction.response.edit_message(embed=self.cog.panel(self.gid,self.page),view=self)
    async def select_rule(self,interaction:discord.Interaction)->None:await interaction.response.send_modal(RuleModal(self.cog,self.gid,interaction.data['values'][0],self))
    async def edit_policy(self,interaction:discord.Interaction)->None:await interaction.response.send_modal(GlobalPolicyModal(self.cog,self.gid,self))
    async def quick_presets(self,interaction:discord.Interaction)->None:self.page='policy';self.rebuild();await interaction.response.edit_message(embed=self.cog.panel(self.gid,'policy'),view=self)
    async def add_word(self,interaction:discord.Interaction)->None:await interaction.response.send_modal(TextListModal(self.cog,self.gid,'word',True,self))
    async def remove_word(self,interaction:discord.Interaction)->None:await interaction.response.send_modal(TextListModal(self.cog,self.gid,'word',False,self))
    async def allowed_domains(self,interaction:discord.Interaction)->None:await interaction.response.send_modal(TextListModal(self.cog,self.gid,'allowed_domain',True,self))
    async def blocked_domains(self,interaction:discord.Interaction)->None:await interaction.response.send_modal(TextListModal(self.cog,self.gid,'blocked_domain',True,self))
    async def remove_allowed_domains(self,interaction:discord.Interaction)->None:await interaction.response.send_modal(TextListModal(self.cog,self.gid,'allowed_domain',False,self))
    async def remove_blocked_domains(self,interaction:discord.Interaction)->None:await interaction.response.send_modal(TextListModal(self.cog,self.gid,'blocked_domain',False,self))
    async def toggle_link(self,interaction:discord.Interaction)->None:
        k=interaction.data['values'][0];cur=self.cog.db.toggles(self.gid)[k];self.cog.db.toggle_link(self.gid,k,not cur);self.cog.invalidate(self.gid);await interaction.response.edit_message(embed=self.cog.panel(self.gid,'filters'),view=self)
    async def edit_trust(self,interaction:discord.Interaction)->None:await interaction.response.send_modal(TrustModal(self.cog,self.gid,self))
    async def cycle_link_policy(self,interaction:discord.Interaction)->None:
        cur=str(self.cog.settings(self.gid).get('link_policy','block_all'));nxt=LINK_POLICIES[(LINK_POLICIES.index(cur)+1)%len(LINK_POLICIES)] if cur in LINK_POLICIES else 'block_all'
        self.cog.db.update_settings(self.gid,link_policy=nxt);self.cog.invalidate(self.gid);self.page='filters';self.rebuild();await interaction.response.edit_message(embed=self.cog.panel(self.gid,'filters'),view=self)
    async def toggle_bots(self,interaction:discord.Interaction)->None:self.cog.db.update_settings(self.gid,ignore_bots=0 if self.cog.settings(self.gid)['ignore_bots'] else 1);self.cog.invalidate(self.gid);self.rebuild();await interaction.response.edit_message(embed=self.cog.panel(self.gid,'trust'),view=self)


class TrustModal(discord.ui.Modal,title='AutoMod • Trust Editor'):
    kind=discord.ui.TextInput(label='Type',placeholder='user / role / channel',max_length=7)
    target=discord.ui.TextInput(label='Discord ID',placeholder='123456789012345678',max_length=20)
    action=discord.ui.TextInput(label='Action',placeholder='add / remove',max_length=6)
    def __init__(self,cog:'Automod',gid:int,view:AMView)->None:super().__init__();self.cog,self.gid,self.view=cog,gid,view
    async def on_submit(self,interaction:discord.Interaction)->None:
        kind=str(self.kind.value).strip().lower();act=str(self.action.value).strip().lower()
        try:tid=int(str(self.target.value).strip())
        except ValueError:await interaction.response.send_message('Discord ID must be numeric.',ephemeral=False);return
        if kind not in {'user','role','channel'} or act not in {'add','remove'}:await interaction.response.send_message('Use user/role/channel and add/remove.',ephemeral=False);return
        self.cog.db.trust(self.gid,kind,tid,act=='add');self.cog.invalidate(self.gid);self.cog.spawn(self.cog.sync_native_rules(interaction.guild));self.view.page='trust';self.view.rebuild();await interaction.response.edit_message(embed=self.cog.panel(self.gid,'trust'),view=self.view)


class Automod(commands.Cog):
    automod_group=app_commands.Group(name='automod',description='Gogeta AutoMod control center')
    def __init__(self,bot:commands.Bot)->None:
        self.bot=bot;self.db=AMDB();self._cache={};self._rule_cache={};self._trust_cache={};self._history=defaultdict(lambda: defaultdict(lambda: {'times': deque(maxlen=MAX_HISTORY), 'contents': deque(maxlen=MAX_HISTORY)}));self._action_locks=defaultdict(asyncio.Lock);self._native_sync_lock=asyncio.Lock();self._native_sync_done=False;self._filter_cache={};self._bg_tasks=set()
    def settings(self,gid:int)->dict:
        n=time.monotonic();c=self._cache.get(gid)
        if c and n-c[0]<CACHE_TTL:return c[1]
        v=self.db.settings(gid);self._cache[gid]=(n,v);return v
    def rules(self,gid:int)->dict[str,dict]:
        n=time.monotonic();c=self._rule_cache.get(gid)
        if c and n-c[0]<CACHE_TTL:return c[1]
        v=self.db.rules(gid);self._rule_cache[gid]=(n,v);return v
    def trust(self,gid:int)->dict[str,set[int]]:
        n=time.monotonic();c=self._trust_cache.get(gid)
        if c and n-c[0]<CACHE_TTL:return c[1]
        v=self.db.trust_sets(gid);self._trust_cache[gid]=(n,v);return v
    def invalidate(self,gid:int)->None:self._cache.pop(gid,None);self._rule_cache.pop(gid,None);self._trust_cache.pop(gid,None);self._filter_cache.pop(gid,None)
    def filters(self,gid:int)->dict:
        n=time.monotonic();c=self._filter_cache.get(gid)
        if c and n-c[0]<CACHE_TTL:return c[1]
        v={'words':self.db.list_table('am_words',gid,'word'),'allowed':self.db.list_table('am_allowed_domains',gid,'domain'),'blocked':self.db.list_table('am_blocked_domains',gid,'domain'),'toggles':self.db.toggles(gid)}
        v['patterns']=[word_pattern(w) for w in v['words']]
        self._filter_cache[gid]=(n,v);return v
    def spawn(self,coro)->None:
        task=asyncio.ensure_future(coro);self._bg_tasks.add(task);task.add_done_callback(self._bg_tasks.discard)
    def admin(self,m:discord.Member|discord.User|None)->bool:return isinstance(m,discord.Member) and (m.id==m.guild.owner_id or m.guild_permissions.administrator or m.guild_permissions.manage_guild)
    async def guard(self,interaction:discord.Interaction)->bool:
        if interaction.guild is None or not self.admin(interaction.user):
            await (interaction.followup.send if interaction.response.is_done() else interaction.response.send_message)("AutoMod configuration requires Server Management permissions.",ephemeral=False);return False
        return True
    def exempt(self,message:discord.Message)->bool:
        if message.guild is None:return True
        if self.bot.user is not None and message.author.id==self.bot.user.id:return True
        s=self.settings(message.guild.id);t=self.trust(message.guild.id)
        webhook=getattr(message,'webhook_id',None) is not None
        # Followed-announcement crossposts arrive through a webhook but are legitimate.
        if webhook and getattr(getattr(message,'flags',None),'is_crossposted',False):return True
        # Bot *accounts* can be ignored, but webhook posts are scanned: a nuker-created webhook is
        # exactly how spam/links get around "ignore bots".
        if s['ignore_bots'] and message.author.bot and not webhook:return True
        if message.author.id in t['user']:return True
        if message.channel.id in t['channel']:return True
        parent=getattr(message.channel,'parent_id',None)
        if parent and parent in t['channel']:return True
        if isinstance(message.author,discord.Member) and any(r.id in t['role'] for r in message.author.roles):return True
        return False

    def channel_permissions(self,message:discord.Message)->discord.Permissions|None:
        if message.guild is None or not message.guild.me:return None
        try:return message.channel.permissions_for(message.guild.me)
        except Exception:return message.guild.me.guild_permissions

    def content_visible(self,message:discord.Message)->bool:
        # An empty content field on a normal text message is the most common
        # symptom of Message Content being unavailable at the Discord Gateway.
        # Do not call this a failure for attachment-only/empty messages.
        return bool((message.content or '').strip() or message.attachments or message.embeds)
    async def ensure_log_channel(self,guild:discord.Guild)->discord.TextChannel|None:
        s=self.settings(guild.id);ch=guild.get_channel(int(s.get('log_channel_id') or 0))
        if isinstance(ch,discord.TextChannel):return ch
        ch=discord.utils.get(guild.text_channels,name='gogeta-automod-logs')
        if isinstance(ch,discord.TextChannel):self.db.update_settings(guild.id,log_channel_id=ch.id);return ch
        me=guild.me
        if me and me.guild_permissions.manage_channels:
            try:ch=await guild.create_text_channel('gogeta-automod-logs',reason='Gogeta AutoMod security logs');self.db.update_settings(guild.id,log_channel_id=ch.id);return ch
            except (discord.Forbidden,discord.HTTPException):pass
        return None
    async def get_or_create_quarantine_role(self,guild:discord.Guild)->discord.Role|None:
        me=guild.me
        if not me or not me.guild_permissions.manage_roles:return None
        role=guild.get_role(int(self.settings(guild.id).get('quarantine_role_id') or 0))
        if role is None: role=discord.utils.find(lambda r:r.name=='Gogeta Quarantine',guild.roles)
        try:
            if role is None: role=await guild.create_role(name='Gogeta Quarantine',colour=discord.Colour.from_rgb(237,66,69),reason='Gogeta AutoMod quarantine')
            for channel in guild.channels:
                if isinstance(channel,(discord.TextChannel,discord.ForumChannel,discord.StageChannel)):
                    try:
                        await channel.set_permissions(role,send_messages=False,add_reactions=False,create_public_threads=False,create_private_threads=False,send_messages_in_threads=False,reason='Gogeta AutoMod quarantine policy')
                    except (discord.Forbidden,discord.HTTPException):
                        pass
            self.db.update_settings(guild.id,quarantine_role_id=role.id);self.invalidate(guild.id);return role
        except (discord.Forbidden,discord.HTTPException):return None

    async def configure_quarantine_role(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction): return
        guild=interaction.guild; assert guild is not None
        role=await self.get_or_create_quarantine_role(guild)
        if role is None:
            await interaction.response.send_message(embed=embed('AUTOMOD / QUARANTINE FAILED','Bot needs Manage Roles and usable channel permission control.',0xED4245),ephemeral=False); return
        await interaction.response.send_message(embed=embed('AUTOMOD / QUARANTINE READY',f'Using {role.mention}. The role restricts normal chat participation in accessible channels.',0x57F287),ephemeral=False)

    @staticmethod
    def _emoji(name: str) -> str:
        return E(name)

    def _setup_embed(self, guild: discord.Guild, statuses: dict[str, str], current: str | None, detail: str, *, final: bool=False, enabled: bool=False) -> discord.Embed:
        total=len(RULES);completed=sum(1 for v in statuses.values() if v in {"READY","WARN","FAILED","SKIPPED"});width=18
        filled=max(0,min(width,round((completed/max(1,total))*width)));bar="━"*filled+"─"*(width-filled)
        title='AUTOMOD / DEPLOYMENT COMPLETE' if final else 'AUTOMOD / LIVE SETUP';c=0x57F287 if final and enabled else (0xED4245 if final and not enabled else 0x5865F2)
        e=embed(title,f"{self._emoji('q_shield')} **Moderation deployment**  ·  `{completed}/{total}` detectors deployed\n`{bar}`\n\n{detail}",c)
        success=self._emoji('q_success');deploying=self._emoji('diamond');bad=self._emoji('q_error');disabled=self._emoji('q_minus')
        rules=self.rules(guild.id);s=self.settings(guild.id);ordered=list(RULES)
        visible_count=completed
        if current is not None and current in ordered:visible_count=max(visible_count,ordered.index(current)+1)
        lines=[]
        for rule in ordered[:visible_count]:
            spec=RULES[rule];state=statuses.get(rule,'QUEUED');r=rules.get(rule,{})
            threshold=int(r.get('threshold',spec['threshold']));window=int(r.get('window_seconds',spec['window']));action=str(r.get('action','inherit'));action=s['default_action'] if action=='inherit' else action
            marker={'READY':success,'WARN':success,'FAILED':bad,'SKIPPED':disabled,'CHECKING':deploying}.get(state,deploying);suffix='  ← deploying' if current==rule and state=='CHECKING' else ''
            lines.append(f"{marker} **{spec['label']}** · `{threshold}/{window}s` · `{action}`{suffix}")
        if lines:
            midpoint=(len(lines)+1)//2
            if len(lines)<=8:e.add_field(name=f'DETECTORS · 01–{len(lines):02d}',value='\n'.join(lines),inline=False)
            else:
                e.add_field(name=f'DETECTORS · 01–{midpoint:02d}',value='\n'.join(lines[:midpoint]),inline=False)
                e.add_field(name=f'DETECTORS · {midpoint+1:02d}–{len(lines):02d}',value='\n'.join(lines[midpoint:]),inline=False)
        if final:e.add_field(name='FINAL STATE',value=f"{self._emoji('q_shield')} **{'ARMED' if enabled else 'NOT ARMED'}** · `/automod config` for configuration",inline=False)
        return e

    def _deploy_rule(self, guild: discord.Guild, rule: str) -> tuple[str,str]:
        """Validate and commit one AutoMod detector before revealing the next one."""
        status,reason=self._detector_readiness(guild,rule)
        if status in {'READY','WARN'}:
            current=self.db.rule(guild.id,rule)
            self.db.update_rule(
                guild.id,rule,
                enabled=int(current['enabled']),
                threshold=int(current['threshold']),
                window_seconds=int(current['window_seconds']),
                action=str(current['action']),
                weight=int(current['weight']),
            )
            self.invalidate(guild.id)
            return 'READY',f"{self._emoji('q_success')} **{RULES[rule]['label']}** deployed and armed."
        return status,reason

    def _native_available(self) -> bool:
        return hasattr(discord.Guild, 'create_automod_rule') and hasattr(discord.Guild, 'fetch_automod_rules') and hasattr(discord, 'AutoModTrigger')

    def _native_actions(self, log_channel_id: int | None, *, timeout_seconds: int = 0) -> list[discord.AutoModRuleAction]:
        actions = [discord.AutoModRuleAction()]
        if timeout_seconds:
            actions.append(discord.AutoModRuleAction(duration=timedelta(seconds=max(60, min(28 * 86400, int(timeout_seconds))))))
        if log_channel_id:
            actions.append(discord.AutoModRuleAction(channel_id=int(log_channel_id)))
        return actions

    async def sync_native_rules(self, guild: discord.Guild) -> tuple[bool, str]:
        if not self.settings(guild.id)['enabled']:
            return False, 'Local AutoMod is disabled.'
        if not self._native_available():
            return False, 'discord.py AutoMod API is unavailable.'
        me = guild.me
        if not me or not me.guild_permissions.manage_guild:
            return False, 'Bot needs Manage Server to maintain native shields.'
        try:
            native_rules = await guild.fetch_automod_rules()
        except (discord.Forbidden, discord.HTTPException) as exc:
            return False, f'Unable to read Discord AutoMod rules: {type(exc).__name__}: {exc}'

        log_channel = await self.ensure_log_channel(guild)
        log_id = log_channel.id if log_channel else int(self.settings(guild.id).get('log_channel_id') or 0) or None
        trusts = self.trust(guild.id)
        exempt_roles = [discord.Object(id=x) for x in sorted(trusts['role'])]
        exempt_channels = [discord.Object(id=x) for x in sorted(trusts['channel'])]
        by_name = {r.name: r for r in native_rules}
        rules = self.rules(guild.id)
        s = self.settings(guild.id)

        desired = [
            (NATIVE_INVITE_RULE, discord.AutoModTrigger(keyword_filter=['*discord.gg/*','*discord.com/invite/*','*discordapp.com/invite/*']), self._native_actions(log_id, timeout_seconds=300)),
            (NATIVE_SPAM_RULE, discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.spam), self._native_actions(log_id)),
            (NATIVE_MENTION_RULE, discord.AutoModTrigger(mention_limit=max(1, min(50, int(rules['mass_mentions']['threshold'])))), self._native_actions(log_id, timeout_seconds=max(60, int(s.get('timeout_seconds') or 300)))),
        ]
        errors = []
        for name, trigger, actions in desired:
            try:
                current = by_name.get(name)
                if current is None:
                    await guild.create_automod_rule(name=name, event_type=discord.AutoModRuleEventType.message_send, trigger=trigger, actions=actions, enabled=True, exempt_roles=exempt_roles, exempt_channels=exempt_channels, reason=NATIVE_RULE_MARKER)
                else:
                    await current.edit(name=name, event_type=discord.AutoModRuleEventType.message_send, trigger=trigger, actions=actions, enabled=True, exempt_roles=exempt_roles, exempt_channels=exempt_channels, reason=NATIVE_RULE_MARKER)
            except (discord.Forbidden, discord.HTTPException, ValueError) as exc:
                errors.append(f'{name}: {type(exc).__name__}: {exc}')
        if errors:
            return False, 'Native shields partially unavailable: ' + ' | '.join(errors)
        return True, 'Native Invite + Spam + Mention shields are active.'

    async def disable_native_rules(self, guild: discord.Guild) -> None:
        if not self._native_available() or not guild.me or not guild.me.guild_permissions.manage_guild:
            return
        try:
            rules = await guild.fetch_automod_rules()
        except (discord.Forbidden, discord.HTTPException):
            return
        for rule in rules:
            if rule.name not in {NATIVE_INVITE_RULE, NATIVE_SPAM_RULE, NATIVE_MENTION_RULE}:
                continue
            try:
                await rule.edit(enabled=False, reason=NATIVE_RULE_MARKER + ' disabled')
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def _startup_native_sync(self) -> None:
        if self._native_sync_done:
            return
        async with self._native_sync_lock:
            if self._native_sync_done:
                return
            for guild in list(self.bot.guilds):
                try:
                    if self.settings(guild.id)['enabled']:
                        ok, detail = await self.sync_native_rules(guild)
                        print(f'[AutoMod] {guild.id}: {detail}')
                except Exception as exc:
                    print(f'[AutoMod] {guild.id}: native shield startup error: {type(exc).__name__}: {exc}')
            self._native_sync_done = True

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self._startup_native_sync()

    @commands.Cog.listener()
    async def on_automod_action(self, execution: discord.AutoModAction) -> None:
        guild = self.bot.get_guild(int(execution.guild_id))
        if guild is None:
            return
        try:
            native_rules = await guild.fetch_automod_rules()
            rule = next((r for r in native_rules if r.id == execution.rule_id), None)
            if rule is None or rule.name not in {NATIVE_INVITE_RULE, NATIVE_SPAM_RULE, NATIVE_MENTION_RULE}:
                return
            primary = {NATIVE_INVITE_RULE:'discord_invites', NATIVE_SPAM_RULE:'rapid_spam', NATIVE_MENTION_RULE:'mass_mentions'}[rule.name]
            self.db.incident(guild.id, int(execution.user_id), primary, 'native_block', 0, True, f'Discord-native AutoMod triggered: {rule.name}')
        except (discord.Forbidden, discord.HTTPException):
            pass
        except Exception as exc:
            print(f'[AutoMod] native action log error in guild {execution.guild_id}: {type(exc).__name__}: {exc}')

    def _detector_readiness(self,guild:discord.Guild,rule:str)->tuple[str,str]:
        s=self.settings(guild.id);r=self.rules(guild.id)[rule];me=guild.me
        if not r['enabled']:return 'SKIPPED','Detector is disabled in configuration.'
        missing=[x for x in RULE_LISTENERS.get(rule,()) if not callable(getattr(self,x,None))]
        if missing:return 'FAILED','Missing listener: '+', '.join(missing)
        if not bool(getattr(self.bot.intents,'message_content',False)):
            if rule in {'discord_invites','rapid_spam','mass_mentions'} and self._native_available() and me and me.guild_permissions.manage_guild:
                return 'READY', 'Discord-native fallback shield is configured for this detector.'
            return 'FAILED','Message Content intent is disabled.'
        if not me or not me.guild_permissions.view_channel:return 'FAILED','Bot cannot view the channel traffic it needs to moderate.'
        action=str(r['action']) if r['action']!='inherit' else str(s['default_action']);p=me.guild_permissions;missing_perm=[]
        if s['delete_trigger'] and action in {'delete','warn','timeout','quarantine','kick','ban'} and not p.manage_messages:missing_perm.append('Manage Messages')
        if action in {'timeout','quarantine'} and not p.moderate_members:missing_perm.append('Moderate Members')
        if action=='quarantine' and not p.manage_roles:missing_perm.append('Manage Roles')
        if action=='kick' and not p.kick_members:missing_perm.append('Kick Members')
        if action=='ban' and not p.ban_members:missing_perm.append('Ban Members')
        if missing_perm:return 'FAILED','Missing permission: '+', '.join(dict.fromkeys(missing_perm))
        return 'READY',f"Listener + content scan + `{action}` response ready."

    async def setup_wizard(self,interaction:discord.Interaction,*,reuse_message:bool=False)->None:
        if not await self.guard(interaction):return
        guild=interaction.guild;assert guild is not None
        self.db.ensure(guild.id);self.invalidate(guild.id);statuses={rule:'QUEUED' for rule in RULES};me=guild.me;s=self.settings(guild.id);base_fail=[]
        active=self.rules(guild.id)
        if not bool(getattr(self.bot.intents,'message_content',False)):
            local_only=[name for name in active if name not in {'discord_invites','rapid_spam','mass_mentions'} and active[name]['enabled']]
            if local_only:base_fail.append('Message Content intent (required by local detectors: '+', '.join(local_only[:6])+('…' if len(local_only)>6 else '')+')')
        if not me or not me.guild_permissions.view_channel:base_fail.append('View Channel')
        actions={str(r['action']) if r['action']!='inherit' else str(s['default_action']) for r in active.values() if r['enabled']} or {str(s['default_action'])}
        if s['delete_trigger'] and actions & {'delete','warn','timeout','quarantine','kick','ban'} and not (me and me.guild_permissions.manage_messages):base_fail.append('Manage Messages')
        if actions & {'timeout','quarantine'} and not (me and me.guild_permissions.moderate_members):base_fail.append('Moderate Members')
        if 'quarantine' in actions and not (me and me.guild_permissions.manage_roles):base_fail.append('Manage Roles')
        if 'kick' in actions and not (me and me.guild_permissions.kick_members):base_fail.append('Kick Members')
        if 'ban' in actions and not (me and me.guild_permissions.ban_members):base_fail.append('Ban Members')
        detail=f"Gateway **online** · Message Content **{'ready' if 'Message Content intent' not in base_fail else 'missing'}** · Enforcement **{'ready' if not base_fail else 'missing: '+', '.join(dict.fromkeys(base_fail))}**"
        initial=self._setup_embed(guild,statuses,None,detail)
        if reuse_message:await interaction.response.edit_message(embed=initial,view=None)
        else:await interaction.response.send_message(embed=initial,ephemeral=False)
        async def edit_setup(message_embed: discord.Embed) -> None:
            if reuse_message and interaction.message is not None:
                await interaction.message.edit(embed=message_embed,view=None)
            else:
                await interaction.edit_original_response(embed=message_embed)

        ordered=list(RULES);blocked_reason=None
        for index,rule in enumerate(ordered):
            statuses[rule]='CHECKING'
            if index == 0:
                await edit_setup(self._setup_embed(guild,statuses,rule,f"{self._emoji('diamond')} Deploying **{RULES[rule]['label']}** …"))
            await asyncio.sleep(1.05)
            try:
                status,reason=self._deploy_rule(guild,rule)
            except Exception as exc:
                status,reason='FAILED',f"Deployment exception: {type(exc).__name__}: {exc}"
            statuses[rule]=status
            if status=='FAILED':
                blocked_reason=reason
                await edit_setup(self._setup_embed(guild,statuses,None,reason))
                break
            next_rule=ordered[index+1] if index+1<len(ordered) else None
            if next_rule is not None:
                statuses[next_rule]='CHECKING'
                detail=f"{self._emoji('q_success')} **{RULES[rule]['label']}** deployed.  {self._emoji('q_shield')} Next: **{RULES[next_rule]['label']}**"
                await edit_setup(self._setup_embed(guild,statuses,next_rule,detail))
                statuses[next_rule]='QUEUED'
            else:
                await edit_setup(self._setup_embed(guild,statuses,None,f"{self._emoji('q_success')} **{RULES[rule]['label']}** deployed."))
        failed=sum(v=='FAILED' for v in statuses.values());ok=not base_fail and failed==0 and blocked_reason is None;self.db.update_settings(guild.id,enabled=int(ok));self.invalidate(guild.id)
        native_ok=False;native_detail='Native shields not attempted because local AutoMod did not arm.'
        if ok:
            native_ok,native_detail=await self.sync_native_rules(guild)
        detail=(f"{self._emoji('q_success')} All configured detectors are deployed. **{native_detail}** `/automod config` now acts as the control center." if ok else f"{self._emoji('q_error')} Deployment stopped before all detectors were armed. {blocked_reason or ('Fix required capabilities and use **Deploy / Repair** again.')}")
        final_embed=self._setup_embed(guild,statuses,None,detail,final=True,enabled=ok)
        if reuse_message and interaction.message is not None:
            await interaction.message.edit(embed=final_embed,view=None)
        else:
            await interaction.edit_original_response(embed=final_embed,view=None)

    async def setup_from_panel(self,interaction:discord.Interaction)->None:
        await self.setup_wizard(interaction,reuse_message=True)

    async def preflight(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction):return
        gid=interaction.guild.id;me=interaction.guild.me;s=self.settings(gid);rules=self.rules(gid)
        actions_needed={str(r['action']) if r['action']!='inherit' else str(s['default_action']) for r in rules.values() if r['enabled']} or {str(s['default_action'])}
        need_delete=bool(s['delete_trigger']) and bool(actions_needed & {'delete','warn','timeout','quarantine','kick','ban'});need_mod=bool(actions_needed & {'timeout','quarantine'});need_kick='kick' in actions_needed;need_ban='ban' in actions_needed
        checks=[check_line('Read Messages',bool(me and me.guild_permissions.view_channel)),check_line('Manage Messages',not need_delete or bool(me and me.guild_permissions.manage_messages),'required by active responses' if need_delete else 'not required'),check_line('Moderate Members',not need_mod or bool(me and me.guild_permissions.moderate_members),'required by active responses' if need_mod else 'not required'),check_line('Kick Members',not need_kick or bool(me and me.guild_permissions.kick_members),'required by active responses' if need_kick else 'not required'),check_line('Ban Members',not need_ban or bool(me and me.guild_permissions.ban_members),'required by active responses' if need_ban else 'not required')]
        ch=await self.ensure_log_channel(interaction.guild);checks.append(check_line('Security Log',bool(ch),ch.mention if ch else 'optional'))
        local_content_ready=bool(getattr(self.bot.intents,'message_content',False))
        native_ready=bool(me and me.guild_permissions.manage_guild and self._native_available())
        ok=bool(me and me.guild_permissions.view_channel) and (local_content_ready or native_ready)
        if need_delete:ok=ok and (bool(me and me.guild_permissions.manage_messages) or native_ready)
        if need_mod:ok=ok and (bool(me and me.guild_permissions.moderate_members) or native_ready)
        if need_kick:ok=ok and (bool(me and me.guild_permissions.kick_members) or native_ready)
        if need_ban:ok=ok and (bool(me and me.guild_permissions.ban_members) or native_ready)
        self.db.update_settings(gid,enabled=int(ok));self.invalidate(gid)
        checks.append(check_line('Local Message Content',local_content_ready,'enabled in bot code' if local_content_ready else 'enable Message Content in Developer Portal for local detectors'))
        checks.append(check_line('Native Shield API',native_ready,'Manage Server + discord.py AutoMod' if native_ready else 'not available'))
        if ok:
            native_ok,native_detail=await self.sync_native_rules(interaction.guild)
            checks.append(check_line('Native Shield Sync',native_ok,native_detail))
        e=embed('AUTOMOD / HEALTH CHECK','Quick validation only. `/automod setup` is the animated deployment wizard.',0x57F287 if ok else 0xED4245);e.add_field(name='CHECKS',value='\n'.join(checks),inline=False);e.add_field(name='ACTIVE',value=f"{sum(1 for r in self.rules(gid).values() if r['enabled'])}/{len(RULES)} detectors",inline=True)
        await interaction.response.send_message(embed=e,view=AMView(self,interaction.user.id,gid),ephemeral=False)

    async def ui_save(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction):return
        gid=interaction.guild.id;self.db.ensure(gid);self.invalidate(gid)
        await interaction.response.send_message(embed=embed('AUTOMOD / SAVED',f"{E('q_check')} Current moderation configuration is persisted. No detectors were changed by Save.",0x57F287),ephemeral=False)
    async def ui_disable(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction):return
        self.db.update_settings(interaction.guild.id,enabled=0);self.invalidate(interaction.guild.id);await self.disable_native_rules(interaction.guild);await interaction.response.edit_message(embed=self.panel(interaction.guild.id),view=AMView(self,interaction.user.id,interaction.guild.id))
    async def arm_all(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction):return
        for r in RULES:self.db.update_rule(interaction.guild.id,r,enabled=1)
        self.db.update_settings(interaction.guild.id,enabled=1);self.invalidate(interaction.guild.id);await self.sync_native_rules(interaction.guild);await interaction.response.edit_message(embed=self.panel(interaction.guild.id,'rules'),view=AMView(self,interaction.user.id,interaction.guild.id,'rules'))
    async def disarm_all(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction):return
        for r in RULES:self.db.update_rule(interaction.guild.id,r,enabled=0)
        self.invalidate(interaction.guild.id);await interaction.response.edit_message(embed=self.panel(interaction.guild.id,'rules'),view=AMView(self,interaction.user.id,interaction.guild.id,'rules'))
    def apply_preset(self,gid:int,name:str)->None:
        if name=='observe':self.db.update_settings(gid,default_action='log_only',trigger_after=1);[self.db.update_rule(gid,r,enabled=1,action='log_only') for r in RULES]
        elif name=='strict':self.db.update_settings(gid,default_action='timeout',trigger_after=1,ban_after=4);[self.db.update_rule(gid,r,enabled=1,threshold=max(1,int(v['threshold'])-1),action='inherit') for r,v in RULES.items()]
        else:self.db.update_settings(gid,default_action='delete',trigger_after=1,ban_after=5);[self.db.update_rule(gid,r,enabled=1,action='inherit',weight=int(v['weight'])) for r,v in RULES.items()]
        self.invalidate(gid)
    def preset_callback(self,name:str,view:AMView):
        async def cb(interaction:discord.Interaction)->None:self.apply_preset(view.gid,name);await interaction.response.edit_message(embed=self.panel(view.gid,'policy'),view=view)
        return cb

    def detect(self,message:discord.Message)->list[str]:
        c=message_text(message);gid=message.guild.id;uid=message.author.id;now=time.monotonic();rules=self.rules(gid);s=self.settings(gid);flt=self.filters(gid);state=self._history[gid][uid];state['times'].append(now);state['contents'].append(c)
        while state['times'] and state['times'][0]<now-120:state['times'].popleft()
        while len(state['contents'])>MAX_HISTORY:state['contents'].popleft()
        signals=[]
        for name,r in rules.items():
            if not r['enabled']:continue
            hit=False
            if name=='rapid_spam':
                hit=sum(1 for t in state['times'] if t>=now-int(r['window_seconds']))>=int(r['threshold'])
            elif name=='duplicate':
                recent=[normalize(x) for x in state['contents'] if x];cur=normalize(c);hit=cur and recent.count(cur)>=int(r['threshold'])
            elif name=='mass_mentions':hit=len(message.mentions)+len(message.role_mentions)>=int(r['threshold'])
            elif name=='discord_invites':hit=has_invite(c) or bool(INVITE_RE.search(c) or OBFUSCATED_INVITE_RE.search(c))
            elif name=='links':
                policy=str(s.get('link_policy') or 'block_all');allowed=flt['allowed'];blocked=flt['blocked'];filters=flt['toggles']
                for raw in find_links(c):
                    h=host(raw)
                    if not h:continue
                    blocked_hit=any(h==d or h.endswith('.'+d) for d in blocked);allowed_hit=any(h==d or h.endswith('.'+d) for d in allowed)
                    if allowed_hit:continue
                    if blocked_hit:hit=True;break
                    if policy=='block_all':hit=True;break
                    if policy=='block_configured' and filters.get(link_kind(raw),False):hit=True;break
            elif name=='caps':
                letters=[ch for ch in c if ch.isalpha()];upper=sum(ch.isupper() for ch in letters);hit=len(letters)>=int(r['window_seconds']) and upper/max(1,len(letters))*100>=int(r['threshold'])
            elif name=='emoji_flood':hit=len(EMOJI_RE.findall(c))>=int(r['threshold'])
            elif name=='zalgo':hit=len(ZALGO_RE.findall(c))>=int(r['threshold'])
            elif name=='blocked_words':
                norm=normalize(c);hit=any(p.search(norm) for p in flt['patterns'])
            elif name=='repeated_chars':hit=bool(REPEAT_RE.search(c))
            elif name=='newline_flood':hit=c.count('\n')+1>=int(r['threshold'])
            elif name=='attachment_flood':hit=len(message.attachments)>=int(r['threshold'])
            elif name=='message_length':hit=len(c)>=int(r['threshold'])
            elif name=='markdown_flood':hit=len(MARKDOWN_RE.findall(c))>=int(r['threshold'])
            elif name=='invisible_chars':hit=len(INVISIBLE_RE.findall(c))>=int(r['threshold'])
            elif name=='everyone_here':hit=message.mention_everyone or '@everyone' in c.lower() or '@here' in c.lower()
            if hit:signals.append(name)
        return signals

    async def warn(self,message:discord.Message,text:str)->None:
        try:
            m=await message.channel.send(text,allowed_mentions=discord.AllowedMentions(users=True,roles=False,everyone=False))
            await asyncio.sleep(WARN_DELETE_AFTER);await m.delete()
        except (discord.Forbidden,discord.HTTPException,discord.NotFound):pass
    async def enforce(self,message:discord.Message,signals:list[str])->None:
        gid=message.guild.id;uid=message.author.id;lock=self._action_locks[(gid,uid)]
        async with lock:
            s=self.settings(gid);rules=self.rules(gid);primary=max(signals,key=lambda x:int(rules[x]['weight']));r=rules[primary]
            action=str(r['action']) if r['action']!='inherit' else str(s['default_action'])
            strike=self.db.strike(gid,uid,int(r['weight']),int(s['strike_decay']));action_done=action;success=True
            notes=['Triggered: '+', '.join(RULES[x]['label'] for x in signals)];warn_text=None
            perms=self.channel_permissions(message)
            # 'delete' always deletes; delete_trigger decides whether punishing actions ALSO delete.
            wants_delete=action!='log_only' and (action=='delete' or bool(s['delete_trigger']))
            if wants_delete:
                if not bool(perms and perms.manage_messages):
                    success=False;notes.append('delete: bot lacks Manage Messages in this channel')
                else:
                    try:await message.delete(reason='Gogeta AutoMod: '+RULES[primary]['label'])
                    except discord.NotFound:pass
                    except (discord.Forbidden,discord.HTTPException) as exc:success=False;notes.append(f'delete: {exc}')
            member=message.author if isinstance(message.author,discord.Member) else None
            try:
                if action!='log_only' and strike>=int(s['ban_after']):
                    # Strike escalation applies to EVERY punishing action (it used to apply only to
                    # warn/timeout, so 'delete' users could rack up 12 strikes and never be banned).
                    await message.guild.ban(discord.Object(id=uid),reason=f'Gogeta AutoMod: {strike} strikes ({RULES[primary]["label"]})',delete_message_seconds=0);action_done='ban'
                elif action=='warn':
                    warn_text=f'⚠️ {message.author.mention}, please slow down. Automated moderation detected **{RULES[primary]["label"]}**.'
                elif action=='timeout':
                    if member is None:raise RuntimeError('Author is not a server member (webhook/bot post).')
                    await member.timeout(discord.utils.utcnow()+timedelta(seconds=int(s['timeout_seconds'])),reason='Gogeta AutoMod: '+RULES[primary]['label'])
                elif action=='quarantine' and strike>=int(s['trigger_after']):
                    if member is None:raise RuntimeError('Author is not a server member.')
                    role=message.guild.get_role(int(s.get('quarantine_role_id') or 0)) or await self.get_or_create_quarantine_role(message.guild)
                    if role is None:raise RuntimeError('No quarantine role is available.')
                    await member.add_roles(role,reason='Gogeta AutoMod: '+RULES[primary]['label'])
                elif action=='kick' and strike>=int(s['trigger_after']):
                    if member is None:raise RuntimeError('Author is not a server member.')
                    await member.kick(reason='Gogeta AutoMod: '+RULES[primary]['label'])
                elif action=='ban' and strike>=int(s['trigger_after']):
                    await message.guild.ban(discord.Object(id=uid),reason='Gogeta AutoMod: '+RULES[primary]['label'],delete_message_seconds=0)
            except discord.NotFound:pass
            except (discord.Forbidden,discord.HTTPException) as exc:success=False;notes.append(f'enforcement: {exc}')
            except Exception as exc:success=False;notes.append(f'enforcement: {type(exc).__name__}: {exc}')
            detail=' | '.join(notes)
            self.db.incident(gid,uid,primary,action_done,strike,success,detail);await self.log(message,primary,action_done,strike,success,detail)
            if action_done=='ban' and success:self.db.clear_strike(gid,uid)
            if warn_text:self.spawn(self.warn(message,warn_text))
    async def log(self,message:discord.Message,rule:str,action:str,strike:int,success:bool,detail:str)->None:
        ch=message.guild.get_channel(int(self.settings(message.guild.id).get('log_channel_id') or 0))
        if not isinstance(ch,discord.TextChannel):return
        e=embed('AUTOMOD / '+('ACTION' if success else 'ACTION FAILED'),f'**Member:** <@{message.author.id}>\n**Rule:** `{RULES[rule]["label"]}`\n**Strike:** `{strike}`\n**Response:** `{action}`\n\n{detail}',0x57F287 if success else 0xED4245)
        try:await ch.send(embed=e,allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden,discord.HTTPException):pass

    @commands.Cog.listener()
    async def on_message(self,message:discord.Message)->None:
        if message.guild is None or self.exempt(message):return
        s=self.settings(message.guild.id)
        if not s['enabled']:return
        try:
            signals=self.detect(message)
            if signals:
                await self.enforce(message,signals)
        except Exception as exc:
            # AutoMod must never take down the event dispatch loop. Record the
            # detector error and continue processing all other bot listeners.
            print(f'[AutoMod] on_message failure in guild {message.guild.id}: {type(exc).__name__}: {exc}')
    @commands.Cog.listener()
    async def on_message_edit(self,before:discord.Message,after:discord.Message)->None:
        if after.guild is None or self.exempt(after) or after.content==before.content:return
        if not self.settings(after.guild.id)['enabled']:return
        try:
            signals=self.detect(after)
            if signals:await self.enforce(after,signals)
        except Exception as exc:
            print(f'[AutoMod] on_message_edit failure in guild {after.guild.id}: {type(exc).__name__}: {exc}')

    def panel(self,gid:int,page:str='overview')->discord.Embed:
        s=self.settings(gid);rules=self.rules(gid);t=self.trust(gid);armed=sum(1 for r in rules.values() if r['enabled']);c=colour(bool(s['enabled']))
        if page=='rules':
            e=embed('AUTOMOD / RULE MATRIX',f'**{armed}/{len(RULES)}** detectors armed. Every detector has its own threshold, window, action and strike weight.',c);e.add_field(name='DETECTORS',value='\n'.join(f"{E('q_check') if r['enabled'] else E('q_minus')} **{RULES[k]['label']}** · `{r['threshold']}` / `{r['window_seconds']}s` · `{r['action']}` · weight `{r['weight']}`" for k,r in rules.items()),inline=False);return e
        if page=='policy':
            e=embed('AUTOMOD / RESPONSE POLICY','Global escalation controls.',c);e.add_field(name='DEFAULT',value=f"`{s['default_action']}`",inline=True);e.add_field(name='TRIGGER',value=f"`{s['trigger_after']}` strikes",inline=True);e.add_field(name='BAN AFTER',value=f"`{s['ban_after']}` strikes",inline=True);e.add_field(name='DECAY',value=f"`{s['strike_decay']}s`",inline=True);e.add_field(name='TIMEOUT',value=f"`{s['timeout_seconds']}s`",inline=True);e.add_field(name='DELETE',value='ON' if s['delete_trigger'] else 'OFF',inline=True);return e
        if page=='filters':
            words=self.db.list_table('am_words',gid,'word');allow=self.db.list_table('am_allowed_domains',gid,'domain');block=self.db.list_table('am_blocked_domains',gid,'domain');links=self.db.toggles(gid);e=embed('AUTOMOD / FILTER MATRIX','Choose exactly what is allowed and what is blocked.',c);e.add_field(name='WORDS',value=', '.join(f'`{w}`' for w in words[:40]) or 'None',inline=False);e.add_field(name='ALLOWED',value=', '.join(f'`{d}`' for d in allow[:20]) or 'None',inline=False);e.add_field(name='BLOCKED DOMAINS',value=', '.join(f'`{d}`' for d in block[:20]) or 'None',inline=False);e.add_field(name='LINK POLICY',value=f"`{s.get('link_policy','block_all')}` (block_all = every link except Allowed Domains)",inline=False);e.add_field(name='LINK CLASSES',value=', '.join(k for k,v in links.items() if v) or 'None',inline=False);return e
        if page=='trust':
            e=embed('AUTOMOD / TRUST MATRIX','Exempt users, roles and channels are skipped before detection.',c);e.add_field(name='USERS',value=str(len(t['user'])),inline=True);e.add_field(name='ROLES',value=str(len(t['role'])),inline=True);e.add_field(name='CHANNELS',value=str(len(t['channel'])),inline=True);e.add_field(name='IGNORE BOTS',value='ON' if s['ignore_bots'] else 'OFF',inline=True);return e
        if page=='logs':
            rows=self.db.incidents(gid,10);e=embed('AUTOMOD / INCIDENT LEDGER','Persistent enforcement history.',0xFEE75C if rows else c);e.add_field(name='RECENT',value='\n\n'.join(f"<t:{r['timestamp']}:R> • <@{r['user_id']}> • **{RULES.get(r['rule'],{}).get('label',r['rule'])}** → `{r['action']}` `{r['strike']}` {'✅' if r['success'] else '❌'}" for r in rows) or 'No incidents.',inline=False);return e
        e=embed('GOGETA / AUTOMOD v6','Local detectors + Discord-native fallback shields. Invite links and spam can be blocked server-side even when Gateway message content is unavailable.',c);e.add_field(name='STATUS',value=E('q_online')+' ONLINE' if s['enabled'] else E('q_offline')+' OFFLINE',inline=True);e.add_field(name='DETECTORS',value=f'`{armed}/{len(RULES)}` armed',inline=True);e.add_field(name='NATIVE',value='Invite + Spam + Mention shields are synchronized on startup/setup.',inline=False);e.add_field(name='WORDS',value=f"`{len(self.db.list_table('am_words',gid,'word'))}`",inline=True);e.add_field(name='LINK CLASSES',value=f"`{sum(self.db.toggles(gid).values())}` armed",inline=True);e.add_field(name='TRUST',value=f"`{len(t['user'])}` users · `{len(t['role'])}` roles · `{len(t['channel'])}` channels",inline=True);e.add_field(name='RESPONSE',value=f"`{s['default_action']}` → trigger `{s['trigger_after']}` → ban `{s['ban_after']}`",inline=True);return e

    @automod_group.command(name='setup',description='Run the animated AutoMod deployment wizard.')
    async def setup_cmd(self,interaction:discord.Interaction)->None:
        await self.setup_wizard(interaction)
    @automod_group.command(name='config',description='Open the AutoMod control center without running setup.')
    async def config_cmd(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction):return
        await interaction.response.send_message(embed=self.panel(interaction.guild.id),view=AMView(self,interaction.user.id,interaction.guild.id),ephemeral=False)
    @automod_group.command(name='disable',description='Disable AutoMod.')
    async def disable_cmd(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction):return
        self.db.update_settings(interaction.guild.id,enabled=0);self.invalidate(interaction.guild.id);await self.disable_native_rules(interaction.guild);await interaction.response.send_message(embed=embed('AUTOMOD / OFFLINE','AutoMod disabled, including Discord-native fallback shields.',0x747F8D),ephemeral=False)
    @automod_group.command(name='links',description='Set the link policy: block every link, only configured classes, or allow all.')
    @app_commands.describe(policy='What to do with links from non-trusted members')
    @app_commands.choices(policy=[app_commands.Choice(name='Block ALL links (except Allowed Domains)',value='block_all'),app_commands.Choice(name='Block only configured classes/domains',value='block_configured'),app_commands.Choice(name='Allow all (only Blocked Domains)',value='allow_all')])
    async def links_cmd(self,interaction:discord.Interaction,policy:app_commands.Choice[str])->None:
        if not await self.guard(interaction):return
        self.db.update_settings(interaction.guild.id,link_policy=policy.value);self.invalidate(interaction.guild.id)
        await interaction.response.send_message(embed=embed('AUTOMOD / LINK POLICY',f'Link policy is now `{policy.value}`. Use **Allowed Domains** in `/automod config` → Filters to whitelist sites.',0x57F287),ephemeral=False)
    @automod_group.command(name='words',description='Manage blocked words and phrases.')
    @app_commands.describe(action='Add, remove, or list',words='Comma-separated or one per line')
    @app_commands.choices(action=[app_commands.Choice(name='Add',value='add'),app_commands.Choice(name='Remove',value='remove'),app_commands.Choice(name='List',value='list')])
    async def words_cmd(self,interaction:discord.Interaction,action:app_commands.Choice[str],words:str|None=None)->None:
        if not await self.guard(interaction):return
        gid=interaction.guild.id
        if action.value=='list': vals=self.db.list_table('am_words',gid,'word');await interaction.response.send_message(embed=embed('AUTOMOD / WORDS',', '.join(f'`{x}`' for x in vals) or 'No blocked words.',0x5865F2),ephemeral=False);return
        vals=[x.strip() for x in re.split(r'[\n,]',words or '') if x.strip()][:100]
        for v in vals:(self.db.add_value if action.value=='add' else self.db.remove_value)('am_words','word',gid,v)
        await interaction.response.send_message(embed=embed('AUTOMOD / WORDS',f'Updated `{len(vals)}` entries.',0x57F287),ephemeral=False)
    @automod_group.command(name='whitelist',description='Trust a user, role, or channel.')
    @app_commands.describe(kind='User, role, or channel',action='Add or remove',user='User',role='Role',channel='Channel')
    @app_commands.choices(kind=[app_commands.Choice(name='User',value='user'),app_commands.Choice(name='Role',value='role'),app_commands.Choice(name='Channel',value='channel')],action=[app_commands.Choice(name='Add',value='add'),app_commands.Choice(name='Remove',value='remove')])
    async def whitelist_cmd(self,interaction:discord.Interaction,kind:app_commands.Choice[str],action:app_commands.Choice[str],user:discord.Member|None=None,role:discord.Role|None=None,channel:discord.TextChannel|None=None)->None:
        if not await self.guard(interaction):return
        target={'user':user,'role':role,'channel':channel}[kind.value]
        if target is None:await interaction.response.send_message('Select the matching target.',ephemeral=False);return
        self.db.trust(interaction.guild.id,kind.value,target.id,action.value=='add');self.invalidate(interaction.guild.id);self.spawn(self.sync_native_rules(interaction.guild));await interaction.response.send_message(embed=embed('AUTOMOD / TRUST UPDATED',f'{target.mention} was {"trusted" if action.value=="add" else "untrusted"}.',0x57F287),ephemeral=False)
    @commands.hybrid_command(name='automod-incidents',description='View recent AutoMod incidents.')
    async def incidents_cmd(self,ctx:commands.Context)->None:
        if not await self.guard_ctx(ctx):return
        rows=self.db.incidents(ctx.guild.id,20);await ctx.send(embed=embed('AUTOMOD / INCIDENTS','\n'.join(f"<t:{r['timestamp']}:R> • <@{r['user_id']}> • {RULES.get(r['rule'],{}).get('label',r['rule'])} → `{r['action']}` `{r['strike']}` {'OK' if r['success'] else 'FAILED'}" for r in rows) or 'No incidents.',0xFEE75C if rows else 0x5865F2),allowed_mentions=discord.AllowedMentions.none())
    async def guard_ctx(self,ctx:commands.Context)->bool:return isinstance(ctx.guild,discord.Guild) and self.admin(ctx.author)


async def setup(bot:commands.Bot)->None:
    await bot.add_cog(Automod(bot))
