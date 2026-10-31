# Credits: gogeta_gg
"""Gogeta Anti-Nuke v3.

A self-contained, audit-log-correlated destructive-action firewall.
The module intentionally has no dependency on the old ``security_ui`` mixins
and no ``Cog.require`` helper: every permission check is local and typed.

Highlights:
- 24 configurable protection modules.
- Per-module threshold/window/action/rollback policy.
- Global actor burst circuit breaker.
- User/role/bot trust matrix.
- Optional quarantine response.
- Safe rollback hooks for supported mutations.
- Persistent SQLite configuration, migration from the v2 tables, and incident log.
- Native Discord UI dashboard with selectors/modals/presets.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands
from ui.emoji import E, bind_view_emojis

DB_PATH = Path(__file__).resolve().parent / "antinuke_v2.db"
CACHE_TTL = 3.0
AUDIT_MAX_AGE = 15.0
AUDIT_RETRIES = (0.0, 0.35, 0.9)
AUDIT_SEEN_TTL = 30.0
ROLLBACK_MEMORY = 120.0
FAILED_RETRY_COOLDOWN = 4.0
FALLBACKS = {
    "ban": ("ban", "kick", "strip_roles", "quarantine"),
    "kick": ("kick", "strip_roles", "quarantine"),
    "strip_roles": ("strip_roles", "quarantine"),
    "quarantine": ("quarantine", "strip_roles"),
    "log_only": ("log_only",),
}
LOG_CHANNEL_NAME = "gogeta-security-logs"

ACTIONS = ("log_only", "strip_roles", "quarantine", "kick", "ban")

RULES: dict[str, dict[str, object]] = {
    "ban": {"label": "Member Bans", "threshold": 3, "window": 10, "action": "ban", "rollback": False},
    "kick": {"label": "Member Kicks", "threshold": 3, "window": 10, "action": "ban", "rollback": False},
    "prune_members": {"label": "Member Prune", "threshold": 1, "window": 10, "action": "ban", "rollback": False},
    "bot_add": {"label": "Untrusted Bot Add", "threshold": 1, "window": 10, "action": "ban", "rollback": False},
    "channel_create": {"label": "Channel Create", "threshold": 5, "window": 10, "action": "ban", "rollback": True},
    "channel_delete": {"label": "Channel Delete", "threshold": 2, "window": 10, "action": "ban", "rollback": False},
    "channel_update": {"label": "Channel Update", "threshold": 5, "window": 10, "action": "ban", "rollback": False},
    "role_create": {"label": "Role Create", "threshold": 5, "window": 10, "action": "ban", "rollback": True},
    "role_delete": {"label": "Role Delete", "threshold": 2, "window": 10, "action": "ban", "rollback": False},
    "role_update": {"label": "Role Update", "threshold": 5, "window": 10, "action": "ban", "rollback": False},
    "role_dangerous": {"label": "Dangerous Role Permissions", "threshold": 1, "window": 10, "action": "ban", "rollback": True},
    "everyone_dangerous": {"label": "@everyone Dangerous Permissions", "threshold": 1, "window": 10, "action": "ban", "rollback": True},
    "member_role_grant": {"label": "Privileged Role Grant", "threshold": 2, "window": 10, "action": "ban", "rollback": True},
    "webhook_create": {"label": "Webhook Create", "threshold": 2, "window": 10, "action": "ban", "rollback": False},
    "webhook_update": {"label": "Webhook Update", "threshold": 2, "window": 10, "action": "ban", "rollback": False},
    "webhook_delete": {"label": "Webhook Delete", "threshold": 2, "window": 10, "action": "ban", "rollback": False},
    "integration_change": {"label": "Integration Change", "threshold": 1, "window": 10, "action": "ban", "rollback": False},
    "emoji_change": {"label": "Emoji Changes", "threshold": 5, "window": 15, "action": "ban", "rollback": False},
    "sticker_change": {"label": "Sticker Changes", "threshold": 5, "window": 15, "action": "ban", "rollback": False},
    "thread_create": {"label": "Thread Create", "threshold": 8, "window": 10, "action": "ban", "rollback": False},
    "thread_delete": {"label": "Thread Delete", "threshold": 3, "window": 10, "action": "ban", "rollback": False},
    "thread_update": {"label": "Thread Update", "threshold": 8, "window": 10, "action": "ban", "rollback": False},
    "scheduled_event_change": {"label": "Scheduled Events", "threshold": 2, "window": 15, "action": "ban", "rollback": False},
    "guild_update": {"label": "Server Configuration", "threshold": 2, "window": 20, "action": "ban", "rollback": False},
}

DANGEROUS_PERMS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "manage_webhooks", "ban_members", "kick_members", "manage_messages",
    "mention_everyone",
)

LABEL_TO_RULE = {str(v["label"]): k for k, v in RULES.items()}

RULE_LISTENERS: dict[str, tuple[str, ...]] = {
    "ban": ("on_member_ban",),
    "kick": ("on_member_remove",),
    "prune_members": ("on_member_remove",),
    "bot_add": ("on_member_join",),
    "channel_create": ("on_guild_channel_create",),
    "channel_delete": ("on_guild_channel_delete",),
    "channel_update": ("on_guild_channel_update",),
    "role_create": ("on_guild_role_create",),
    "role_delete": ("on_guild_role_delete",),
    "role_update": ("on_guild_role_update",),
    "role_dangerous": ("on_guild_role_create", "on_guild_role_update"),
    "everyone_dangerous": ("on_guild_role_update",),
    "member_role_grant": ("on_member_update",),
    "webhook_create": ("on_webhooks_update",),
    "webhook_update": ("on_webhooks_update",),
    "webhook_delete": ("on_webhooks_update",),
    "integration_change": ("on_integration_create", "on_integration_update", "on_integration_delete"),
    "emoji_change": ("on_guild_emojis_update",),
    "sticker_change": ("on_guild_stickers_update",),
    "thread_create": ("on_thread_create",),
    "thread_delete": ("on_thread_delete",),
    "thread_update": ("on_thread_update",),
    "scheduled_event_change": ("on_scheduled_event_create", "on_scheduled_event_update", "on_scheduled_event_delete"),
    "guild_update": ("on_guild_update",),
}

# v3 stock profile. It is used only to recognize a completely untouched older
# installation. Customized configurations are left exactly as they are.
LEGACY_STOCK_ACTIONS = {
    "ban": "strip_roles", "kick": "strip_roles", "prune_members": "strip_roles",
    "bot_add": "kick", "channel_create": "strip_roles", "channel_delete": "strip_roles",
    "channel_update": "strip_roles", "role_create": "strip_roles", "role_delete": "strip_roles",
    "role_update": "strip_roles", "role_dangerous": "strip_roles", "everyone_dangerous": "strip_roles",
    "member_role_grant": "strip_roles", "webhook_create": "strip_roles", "webhook_update": "strip_roles",
    "webhook_delete": "strip_roles", "integration_change": "strip_roles", "emoji_change": "strip_roles",
    "sticker_change": "strip_roles", "thread_create": "strip_roles", "thread_delete": "strip_roles",
    "thread_update": "strip_roles", "scheduled_event_change": "strip_roles", "guild_update": "strip_roles",
}
LEGACY_ROLE_UPDATE_THRESHOLD = 4

def _safe(text: object, limit: int = 1300) -> str:
    value = str(text or "")
    return value.replace("@everyone", "@\u000beveryone").replace("@here", "@\u000bhere")[:limit]


def _action_name(action: str) -> str:
    return action.replace("_", " ").title()


def _check_line(name: str, ok: bool, detail: str = "") -> str:
    return f"{'✅' if ok else '❌'} **{name}**{(' — ' + detail) if detail else ''}"


def _embed(title: str, description: str = "", colour: int = 0x5865F2) -> discord.Embed:
    e = discord.Embed(title=title, description=description, colour=colour, timestamp=discord.utils.utcnow())
    e.set_footer(text="Gogeta Security Suite • Anti-Nuke v3")
    return e


class ANDB:
    """Small synchronous SQLite layer; each operation is short and bounded."""

    def __init__(self) -> None:
        self.setup()

    def db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def setup(self) -> None:
        with self.db() as db:
            had_meta = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='an_meta'").fetchone()
            has_settings = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='an_settings'").fetchone()
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS an_settings (
                    guild_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    log_channel_id INTEGER,
                    default_action TEXT NOT NULL DEFAULT 'ban',
                    global_threshold INTEGER NOT NULL DEFAULT 3,
                    global_window INTEGER NOT NULL DEFAULT 10,
                    actor_cooldown INTEGER NOT NULL DEFAULT 30,
                    quarantine_role_id INTEGER,
                    auto_rollback INTEGER NOT NULL DEFAULT 1,
                    owner_immune INTEGER NOT NULL DEFAULT 1,
                    bots_require_trust INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS an_rules (
                    guild_id INTEGER NOT NULL,
                    rule TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    threshold INTEGER NOT NULL DEFAULT 3,
                    window_seconds INTEGER NOT NULL DEFAULT 10,
                    action TEXT NOT NULL DEFAULT 'inherit',
                    rollback INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(guild_id, rule)
                );
                CREATE TABLE IF NOT EXISTS an_trust (
                    guild_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    target_id INTEGER NOT NULL,
                    PRIMARY KEY(guild_id, kind, target_id)
                );
                CREATE TABLE IF NOT EXISTS an_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    actor_id INTEGER,
                    target_id INTEGER,
                    rule TEXT NOT NULL,
                    action TEXT NOT NULL,
                    success INTEGER NOT NULL DEFAULT 0,
                    detail TEXT,
                    timestamp INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_an_incidents ON an_incidents(guild_id, timestamp DESC);
                CREATE TABLE IF NOT EXISTS an_meta (key TEXT PRIMARY KEY, value TEXT);
                """
            )
            if not had_meta and has_settings:
                # Guilds that existed before the one-time-import fix have already been (repeatedly)
                # imported; mark them done so the first run after upgrading does not overwrite their config.
                db.execute("INSERT OR IGNORE INTO an_meta(key,value) SELECT 'legacy_import:'||guild_id,'1' FROM an_settings")

    def ensure(self, guild_id: int) -> None:
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO an_settings(guild_id) VALUES(?)", (guild_id,))
            db.executemany(
                """INSERT OR IGNORE INTO an_rules
                   (guild_id,rule,enabled,threshold,window_seconds,action,rollback)
                   VALUES(?,?,?,?,?,?,?)""",
                [
                    (guild_id, name, 1, int(spec["threshold"]), int(spec["window"]), str(spec["action"]), int(bool(spec["rollback"])))
                    for name, spec in RULES.items()
                ],
            )

            # One-time migration from the old security_* schema. It used to run on EVERY call,
            # which re-added whitelist entries after an admin removed them, re-enabled a firewall
            # the admin had disabled, and reverted rule edits. It is now strictly once per guild.
            marker = f"legacy_import:{guild_id}"
            if db.execute("SELECT 1 FROM an_meta WHERE key=?", (marker,)).fetchone():
                return
            db.execute("INSERT OR IGNORE INTO an_meta(key,value) VALUES(?,'1')", (marker,))
            old = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='security_settings'").fetchone()
            if not old:
                return
            row = db.execute("SELECT enabled,log_channel_id,punishment,global_threshold,global_window,auto_deploy FROM security_settings WHERE guild_id=?", (guild_id,)).fetchone()
            if row:
                db.execute(
                    """UPDATE an_settings SET enabled=?,log_channel_id=?,default_action=?,global_threshold=?,global_window=?
                       WHERE guild_id=? AND enabled=0 AND log_channel_id IS NULL""",
                    (row[0], row[1], row[2] if row[2] in ACTIONS else "strip_roles", row[3], row[4], guild_id),
                )
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='security_rules'").fetchone():
                rows = db.execute("SELECT category,enabled,threshold,window_seconds,punishment FROM security_rules WHERE guild_id=?", (guild_id,)).fetchall()
                for r in rows:
                    if r[0] in RULES:
                        act = r[4] if r[4] in ACTIONS or r[4] == 'inherit' else 'inherit'
                        db.execute("UPDATE an_rules SET enabled=?,threshold=?,window_seconds=?,action=? WHERE guild_id=? AND rule=?", (r[1], r[2], r[3], act, guild_id, r[0]))
            for table, kind, col in (("whitelist_users", "user", "user_id"), ("whitelist_roles", "role", "role_id"), ("whitelist_bots", "bot", "bot_id")):
                if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    rows = db.execute(f"SELECT {col} FROM {table} WHERE guild_id=?", (guild_id,)).fetchall()
                    db.executemany("INSERT OR IGNORE INTO an_trust(guild_id,kind,target_id) VALUES(?,?,?)", [(guild_id, kind, int(x[0])) for x in rows])

    def settings(self, guild_id: int) -> dict:
        self.ensure(guild_id)
        with self.db() as db:
            return dict(db.execute("SELECT * FROM an_settings WHERE guild_id=?", (guild_id,)).fetchone())

    def update_settings(self, guild_id: int, **fields: object) -> None:
        self.ensure(guild_id)
        allowed = {"enabled","log_channel_id","default_action","global_threshold","global_window","actor_cooldown","quarantine_role_id","auto_rollback","owner_immune","bots_require_trust"}
        clean = {k:v for k,v in fields.items() if k in allowed}
        if not clean:
            return
        with self.db() as db:
            db.execute(f"UPDATE an_settings SET {','.join(f'{k}=?' for k in clean)} WHERE guild_id=?", [*clean.values(), guild_id])

    def rules(self, guild_id: int) -> dict[str, dict]:
        self.ensure(guild_id)
        with self.db() as db:
            return {row["rule"]: dict(row) for row in db.execute("SELECT * FROM an_rules WHERE guild_id=?", (guild_id,))}

    def rule(self, guild_id: int, name: str) -> dict:
        self.ensure(guild_id)
        with self.db() as db:
            return dict(db.execute("SELECT * FROM an_rules WHERE guild_id=? AND rule=?", (guild_id,name)).fetchone())

    def update_rule(self, guild_id: int, name: str, **fields: object) -> None:
        self.ensure(guild_id)
        allowed = {"enabled","threshold","window_seconds","action","rollback"}
        clean = {k:v for k,v in fields.items() if k in allowed}
        if not clean:
            return
        with self.db() as db:
            db.execute(f"UPDATE an_rules SET {','.join(f'{k}=?' for k in clean)} WHERE guild_id=? AND rule=?", [*clean.values(),guild_id,name])

    def trust(self, guild_id: int, kind: str, target_id: int, add: bool) -> None:
        with self.db() as db:
            if add:
                db.execute("INSERT OR IGNORE INTO an_trust(guild_id,kind,target_id) VALUES(?,?,?)", (guild_id,kind,int(target_id)))
            else:
                db.execute("DELETE FROM an_trust WHERE guild_id=? AND kind=? AND target_id=?", (guild_id,kind,int(target_id)))

    def trust_sets(self, guild_id: int) -> tuple[set[int],set[int],set[int]]:
        with self.db() as db:
            rows = db.execute("SELECT kind,target_id FROM an_trust WHERE guild_id=?", (guild_id,)).fetchall()
        out = {"user":set(),"role":set(),"bot":set()}
        for row in rows:
            out.setdefault(row["kind"], set()).add(int(row["target_id"]))
        return out["user"], out["role"], out["bot"]

    def trust_count(self, guild_id: int) -> tuple[int,int,int]:
        u,r,b = self.trust_sets(guild_id); return len(u),len(r),len(b)

    def incident(self, guild_id: int, actor_id: int|None, target_id: int|None, rule: str, action: str, success: bool, detail: str) -> None:
        with self.db() as db:
            db.execute("INSERT INTO an_incidents(guild_id,actor_id,target_id,rule,action,success,detail,timestamp) VALUES(?,?,?,?,?,?,?,?)", (guild_id,actor_id,target_id,rule,action,int(success),_safe(detail),int(time.time())))
            db.execute("DELETE FROM an_incidents WHERE guild_id=? AND id NOT IN (SELECT id FROM an_incidents WHERE guild_id=? ORDER BY timestamp DESC LIMIT 1000)", (guild_id,guild_id))

    def incidents(self, guild_id: int, limit: int = 12) -> list[sqlite3.Row]:
        with self.db() as db:
            return db.execute("SELECT * FROM an_incidents WHERE guild_id=? ORDER BY timestamp DESC, id DESC LIMIT ?", (guild_id,max(1,min(100,int(limit))))).fetchall()


class PolicyModal(discord.ui.Modal, title="Anti-Nuke • Global Policy"):
    threshold = discord.ui.TextInput(label="Global burst threshold", placeholder="3", max_length=3)
    window = discord.ui.TextInput(label="Global burst window (seconds)", placeholder="10", max_length=4)
    action = discord.ui.TextInput(label="Default response", placeholder="strip_roles / quarantine / kick / ban / log_only", max_length=20)
    cooldown = discord.ui.TextInput(label="Actor containment cooldown (seconds)", placeholder="30", max_length=4)

    def __init__(self, cog: "Antinuke", guild_id: int, view: "ANView") -> None:
        super().__init__()
        self.cog,self.guild_id,self.view = cog,guild_id,view
        s = cog.settings(guild_id)
        self.threshold.default = str(s["global_threshold"])
        self.window.default = str(s["global_window"])
        self.action.default = str(s["default_action"])
        self.cooldown.default = str(s["actor_cooldown"])

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            threshold=max(1,min(50,int(str(self.threshold.value))))
            window=max(2,min(300,int(str(self.window.value))))
            action=str(self.action.value).strip().lower()
            cooldown=max(5,min(3600,int(str(self.cooldown.value))))
            if action not in ACTIONS: raise ValueError("Unknown response action.")
        except (ValueError,TypeError) as exc:
            await interaction.response.send_message(embed=_embed("ANTI-NUKE / INVALID POLICY",str(exc),0xED4245),ephemeral=False); return
        self.cog.update_settings(self.guild_id,global_threshold=threshold,global_window=window,default_action=action,actor_cooldown=cooldown)
        self.view.page="policy"; self.view.rebuild()
        await interaction.response.edit_message(embed=self.cog.panel(self.guild_id,"policy"),view=self.view)


class RuleModal(discord.ui.Modal, title="Anti-Nuke • Module Editor"):
    enabled = discord.ui.TextInput(label="Enabled?", placeholder="yes / no", max_length=3)
    threshold = discord.ui.TextInput(label="Trigger threshold", placeholder="3", max_length=4)
    window = discord.ui.TextInput(label="Window in seconds", placeholder="10", max_length=5)
    action = discord.ui.TextInput(label="Response", placeholder="inherit / log_only / strip_roles / quarantine / kick / ban", max_length=20)
    rollback = discord.ui.TextInput(label="Auto-rollback?", placeholder="yes / no", max_length=3)

    def __init__(self,cog:"Antinuke",guild_id:int,rule:str,view:"ANView") -> None:
        super().__init__(); self.cog,self.guild_id,self.rule,self.view=cog,guild_id,rule,view
        r=cog.db.rule(guild_id,rule); self.enabled.default="yes" if r["enabled"] else "no"; self.threshold.default=str(r["threshold"]); self.window.default=str(r["window_seconds"]); self.action.default=str(r["action"]); self.rollback.default="yes" if r["rollback"] else "no"

    async def on_submit(self,interaction:discord.Interaction)->None:
        try:
            enabled=str(self.enabled.value).strip().lower() in {"y","yes","on","true","1"}
            threshold=max(1,min(100,int(str(self.threshold.value))))
            window=max(2,min(300,int(str(self.window.value))))
            action=str(self.action.value).strip().lower()
            if action not in ("inherit",)+ACTIONS: raise ValueError("Invalid response action.")
            rollback=str(self.rollback.value).strip().lower() in {"y","yes","on","true","1"}
        except (ValueError,TypeError) as exc:
            await interaction.response.send_message(embed=_embed("ANTI-NUKE / INVALID MODULE",str(exc),0xED4245),ephemeral=False); return
        self.cog.update_rule(self.guild_id,self.rule,enabled=enabled,threshold=threshold,window_seconds=window,action=action,rollback=rollback)
        self.view.page="modules"; self.view.rebuild()
        await interaction.response.edit_message(embed=self.cog.panel(self.guild_id,"modules"),view=self.view)


class TrustModal(discord.ui.Modal, title="Anti-Nuke • Trust Editor"):
    kind=discord.ui.TextInput(label="Type",placeholder="user / role / bot",max_length=4)
    target=discord.ui.TextInput(label="Discord ID",placeholder="123456789012345678",max_length=20)
    action=discord.ui.TextInput(label="Action",placeholder="add / remove",max_length=6)

    def __init__(self,cog:"Antinuke",guild_id:int,view:"ANView")->None:
        super().__init__(); self.cog,self.guild_id,self.view=cog,guild_id,view

    async def on_submit(self,interaction:discord.Interaction)->None:
        kind=str(self.kind.value).strip().lower(); act=str(self.action.value).strip().lower()
        try: target=int(str(self.target.value).strip())
        except ValueError:
            await interaction.response.send_message(embed=_embed("ANTI-NUKE / INVALID ID","Discord IDs are numeric.",0xED4245),ephemeral=False); return
        if kind not in {"user","role","bot"} or act not in {"add","remove"}:
            await interaction.response.send_message(embed=_embed("ANTI-NUKE / INVALID TRUST","Use user/role/bot and add/remove.",0xED4245),ephemeral=False); return
        self.cog.db.trust(self.guild_id,kind,target,act=="add"); self.cog.invalidate(self.guild_id)
        self.view.page="trust"; self.view.rebuild(); await interaction.response.edit_message(embed=self.cog.panel(self.guild_id,"trust"),view=self.view)


class ANView(discord.ui.View):
    def __init__(self,cog:"Antinuke",author_id:int,guild_id:int,page:str="overview")->None:
        super().__init__(timeout=1200); self.cog,self.author_id,self.guild_id,self.page=cog,author_id,guild_id,page; self.rebuild()

    async def interaction_check(self,interaction:discord.Interaction)->bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This security panel belongs to another administrator.",ephemeral=False); return False
        return True

    def button(self,label:str,style:discord.ButtonStyle,row:int):
        b=discord.ui.Button(label=label,style=style,row=row); return b

    def rebuild(self)->None:
        self.clear_items()
        for label,page in (("Overview","overview"),("Modules","modules"),("Policy","policy"),("Trust","trust"),("Logs","logs")):
            b=self.button(label,discord.ButtonStyle.primary if self.page==page else discord.ButtonStyle.secondary,0); b.callback=self._nav(page); self.add_item(b)
        if self.page=="overview":
            for label,style,cb in (("Deploy / Repair","success",self.cog.setup_from_panel),("Disable","danger",self.cog.ui_disable),("Save","primary",self.cog.ui_save),("Quick Presets","secondary",self.quick_presets),("Health Check","secondary",self.cog.preflight)):
                b=self.button(label,getattr(discord.ButtonStyle,style),1); b.callback=cb; self.add_item(b)
        elif self.page=="modules":
            options=[discord.SelectOption(label=str(spec["label"]),value=name) for name,spec in RULES.items()]
            sel=discord.ui.Select(placeholder="Select a protection module…",min_values=1,max_values=1,options=options,row=1); sel.callback=self.module_select; self.add_item(sel)
            for label,style,cb in (("Arm All","success",self.cog.arm_all),("Disarm All","danger",self.cog.disarm_all)):
                b=self.button(label,getattr(discord.ButtonStyle,style),2); b.callback=cb; self.add_item(b)
        elif self.page=="policy":
            b=self.button("Edit Global Policy",discord.ButtonStyle.primary,1); b.callback=self.policy; self.add_item(b)
            b=self.button("Quarantine Role",discord.ButtonStyle.secondary,1); b.callback=self.quarantine_role; self.add_item(b)
            b=self.button("Auto-Rollback: " + ("ON" if self.cog.settings(self.guild_id)["auto_rollback"] else "OFF"),discord.ButtonStyle.secondary,1); b.callback=self.toggle_rollback; self.add_item(b)
            b=self.button("Preset: Balanced",discord.ButtonStyle.secondary,2); b.callback=self.apply_balanced; self.add_item(b)
            b=self.button("Preset: Strict",discord.ButtonStyle.secondary,2); b.callback=self.apply_strict; self.add_item(b)
            b=self.button("Preset: Observe",discord.ButtonStyle.secondary,2); b.callback=self.apply_observe; self.add_item(b)
        elif self.page=="trust":
            b=self.button("Edit Trust",discord.ButtonStyle.primary,1); b.callback=self.trust; self.add_item(b)
            b=self.button("Owner Always Immune",discord.ButtonStyle.secondary,1); b.callback=self.toggle_owner; self.add_item(b)
            b=self.button("Untrusted Bots Only",discord.ButtonStyle.secondary,2); b.callback=self.toggle_bots; self.add_item(b)
        elif self.page=="recovery":
            b=self.button("Quarantine Role",discord.ButtonStyle.primary,1); b.callback=self.quarantine_role; self.add_item(b)
            b=self.button("Toggle Auto-Rollback",discord.ButtonStyle.secondary,1); b.callback=self.toggle_rollback; self.add_item(b)
        elif self.page=="logs":
            pass
        b=self.button("Refresh",discord.ButtonStyle.secondary,4); b.callback=self.refresh; self.add_item(b)
        bind_view_emojis(self)

    def _nav(self,page:str):
        async def cb(interaction:discord.Interaction)->None:
            self.page=page; self.rebuild(); await interaction.response.edit_message(embed=self.cog.panel(self.guild_id,page),view=self)
        return cb
    async def refresh(self,interaction:discord.Interaction)->None:
        self.cog.invalidate(self.guild_id); self.rebuild(); await interaction.response.edit_message(embed=self.cog.panel(self.guild_id,self.page),view=self)
    async def module_select(self,interaction:discord.Interaction)->None:
        rule=interaction.data["values"][0]; await interaction.response.send_modal(RuleModal(self.cog,self.guild_id,rule,self))
    async def policy(self,interaction:discord.Interaction)->None: await interaction.response.send_modal(PolicyModal(self.cog,self.guild_id,self))
    async def trust(self,interaction:discord.Interaction)->None: await interaction.response.send_modal(TrustModal(self.cog,self.guild_id,self))
    async def quick_presets(self,interaction:discord.Interaction)->None: self.page="policy"; self.rebuild(); await interaction.response.edit_message(embed=self.cog.panel(self.guild_id,"policy"),view=self)
    async def apply_balanced(self,interaction:discord.Interaction)->None: self.cog.apply_preset(self.guild_id,"balanced"); self.cog.invalidate(self.guild_id); await interaction.response.edit_message(embed=self.cog.panel(self.guild_id,"policy"),view=self)
    async def apply_strict(self,interaction:discord.Interaction)->None: self.cog.apply_preset(self.guild_id,"strict"); self.cog.invalidate(self.guild_id); await interaction.response.edit_message(embed=self.cog.panel(self.guild_id,"policy"),view=self)
    async def apply_observe(self,interaction:discord.Interaction)->None: self.cog.apply_preset(self.guild_id,"observe"); self.cog.invalidate(self.guild_id); await interaction.response.edit_message(embed=self.cog.panel(self.guild_id,"policy"),view=self)
    async def toggle_owner(self,interaction:discord.Interaction)->None: self.cog.update_settings(self.guild_id,owner_immune=0 if self.cog.settings(self.guild_id)["owner_immune"] else 1); self.cog.invalidate(self.guild_id); await interaction.response.edit_message(embed=self.cog.panel(self.guild_id,"trust"),view=self)
    async def toggle_bots(self,interaction:discord.Interaction)->None: self.cog.update_settings(self.guild_id,bots_require_trust=0 if self.cog.settings(self.guild_id)["bots_require_trust"] else 1); self.cog.invalidate(self.guild_id); await interaction.response.edit_message(embed=self.cog.panel(self.guild_id,"trust"),view=self)
    async def quarantine_role(self,interaction:discord.Interaction)->None: await self.cog.configure_quarantine_role(interaction)
    async def toggle_rollback(self,interaction:discord.Interaction)->None: self.cog.update_settings(self.guild_id,auto_rollback=0 if self.cog.settings(self.guild_id)["auto_rollback"] else 1); self.cog.invalidate(self.guild_id); await interaction.response.edit_message(embed=self.cog.panel(self.guild_id,"recovery"),view=self)
    async def deploy(self,interaction:discord.Interaction)->None: await self.cog.preflight(interaction)


class Antinuke(commands.Cog):
    antinuke_group=app_commands.Group(name="antinuke",description="Gogeta Anti-Nuke security control center")

    def __init__(self,bot:commands.Bot)->None:
        self.bot=bot; self.db=ANDB(); self._cache:dict[int,tuple[float,dict]]={}; self._rule_cache:dict[int,tuple[float,dict[str,dict]]]={}; self._trust_cache:dict[int,tuple[float,tuple[set[int],set[int],set[int]]]]={}; self._events=defaultdict(lambda:defaultdict(lambda:defaultdict(deque))); self._locks:dict[tuple[int,int],asyncio.Lock]={}; self._audit_seen:dict[int,float]={}; self._audit_semaphore=defaultdict(lambda:asyncio.Semaphore(3)); self._recent_bans:dict[tuple[int,int],float]={}; self._contained:dict[tuple[int,int],tuple[float,bool]]={}; self._pending=defaultdict(lambda:deque(maxlen=60)); self._unattributed:dict[tuple[int,str],float]={}

    def settings(self,guild_id:int)->dict:
        now=time.monotonic(); c=self._cache.get(guild_id)
        if c and now-c[0]<CACHE_TTL: return c[1]
        v=self.db.settings(guild_id); self._cache[guild_id]=(now,v); return v
    def rules(self,guild_id:int)->dict[str,dict]:
        now=time.monotonic(); c=self._rule_cache.get(guild_id)
        if c and now-c[0]<CACHE_TTL:return c[1]
        v=self.db.rules(guild_id); self._rule_cache[guild_id]=(now,v); return v
    def invalidate(self,guild_id:int)->None:
        self._cache.pop(guild_id,None); self._rule_cache.pop(guild_id,None); self._trust_cache.pop(guild_id,None); self._events.pop(guild_id,None)
    def trust(self,guild_id:int)->tuple[set[int],set[int],set[int]]:
        now=time.monotonic(); c=self._trust_cache.get(guild_id)
        if c and now-c[0]<CACHE_TTL:return c[1]
        v=self.db.trust_sets(guild_id); self._trust_cache[guild_id]=(now,v); return v
    async def runtime_health(self) -> tuple[bool, list[str]]:
        """Validate the live prerequisites for every enabled Anti-Nuke guild."""
        issues: list[str] = []
        enabled_guilds = 0
        for guild in self.bot.guilds:
            s = self.settings(guild.id)
            if not s["enabled"]:
                continue
            enabled_guilds += 1
            me = guild.me
            if not me:
                issues.append(f"guild={guild.id}: bot member unavailable")
                continue
            if not me.guild_permissions.view_audit_log:
                issues.append(f"guild={guild.id}: missing View Audit Log")
            actions = {
                str(r["action"]) if r["action"] != "inherit" else str(s["default_action"])
                for r in self.rules(guild.id).values() if r["enabled"]
            } or {str(s["default_action"])}
            if "strip_roles" in actions or "quarantine" in actions:
                if not me.guild_permissions.manage_roles:
                    issues.append(f"guild={guild.id}: missing Manage Roles")
            if "kick" in actions and not me.guild_permissions.kick_members:
                issues.append(f"guild={guild.id}: missing Kick Members")
            if "ban" in actions and not me.guild_permissions.ban_members:
                issues.append(f"guild={guild.id}: missing Ban Members")
        if issues:
            print("[AntiNuke] Runtime health warning: " + " | ".join(issues[:30]))
        else:
            print(f"[AntiNuke] Runtime healthy in {enabled_guilds} enabled guild(s).")
        return (not issues, issues)

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            await self.runtime_health()
        except Exception as exc:
            print(f"[AntiNuke] Runtime health check failed: {type(exc).__name__}: {exc}")

    def allowed_admin(self,member:discord.Member|discord.User|None)->bool:
        if not isinstance(member,discord.Member): return False
        p=member.guild_permissions; return member.guild.owner_id==member.id or p.administrator or p.manage_guild
    async def guard(self,interaction:discord.Interaction)->bool:
        if interaction.guild is None or not self.allowed_admin(interaction.user):
            msg="This control center requires Server Management permissions (or the server owner)."
            if interaction.response.is_done(): await interaction.followup.send(msg,ephemeral=False)
            else: await interaction.response.send_message(msg,ephemeral=False)
            return False
        return True
    async def guard_ctx(self,ctx:commands.Context)->bool:
        return isinstance(ctx.guild,discord.Guild) and self.allowed_admin(ctx.author)

    def actor_exempt(self,guild:discord.Guild,actor:discord.abc.User|None)->bool:
        if actor is None:return True
        s=self.settings(guild.id)
        if s["owner_immune"] and actor.id==guild.owner_id:return True
        if actor.id==getattr(self.bot.user,"id",0):return True
        users,roles,bots=self.trust(guild.id)
        if actor.id in users:return True
        if isinstance(actor,discord.Member) and any(r.id in roles for r in actor.roles):return True
        if isinstance(actor,discord.Member) and actor.bot and actor.id in bots:return True
        if isinstance(actor,discord.Member) and actor.bot and s["bots_require_trust"]: return False
        return False

    @staticmethod
    def _audit_value(name:str): return getattr(discord.AuditLogAction,name,None)

    async def audit_entry(self,guild:discord.Guild,actions:list[object],target_id:int|None=None,retries:tuple[float,...]|None=None)->discord.AuditLogEntry|None:
        me=guild.me
        if not me or not me.guild_permissions.view_audit_log:return None
        acts=[a for a in actions if a is not None]
        if not acts:return None
        async with self._audit_semaphore[guild.id]:
            for delay in (retries if retries is not None else AUDIT_RETRIES):
                if delay: await asyncio.sleep(delay)
                best=None; now=time.monotonic()
                for key,seen in list(self._audit_seen.items()):
                    if now-seen>AUDIT_SEEN_TTL:self._audit_seen.pop(key,None)
                try:
                    for action in acts:
                        async for entry in guild.audit_logs(limit=25,action=action):
                            age=(discord.utils.utcnow()-entry.created_at).total_seconds()
                            if age>AUDIT_MAX_AGE:break
                            if age < -2:continue
                            # Skip entries an earlier event already consumed. Previously the NEWEST
                            # entry was picked first and then discarded if seen, so rapid-fire
                            # actions (emoji/webhook/guild changes) were silently never attributed.
                            if entry.id in self._audit_seen:continue
                            target=getattr(entry,"target",None)
                            if target_id is not None and getattr(target,"id",None)!=target_id:continue
                            if best is None or entry.created_at>best.created_at:best=entry
                except (discord.Forbidden,discord.HTTPException):return None
                if best:
                    self._audit_seen[best.id]=time.monotonic(); return best
        return None

    def _record(self,guild_id:int,actor_id:int,rule:str,window:int)->tuple[int,int]:
        now=time.monotonic(); bucket=self._events[guild_id][actor_id]; q=bucket[rule]; g=bucket["__global__"]; q.append(now); g.append(now); global_window=int(self.settings(guild_id)["global_window"])
        while q and q[0]<now-window:q.popleft()
        while g and g[0]<now-global_window:g.popleft()
        return len(q),len(g)

    def _lock(self,guild_id:int,actor_id:int)->asyncio.Lock:
        key=(guild_id,actor_id); return self._locks.setdefault(key,asyncio.Lock())

    async def ensure_log_channel(self,guild:discord.Guild)->discord.TextChannel|None:
        configured=self.settings(guild.id).get("log_channel_id")
        if configured:
            ch=guild.get_channel(int(configured))
            if isinstance(ch,discord.TextChannel):return ch
        ch=discord.utils.get(guild.text_channels,name=LOG_CHANNEL_NAME)
        if isinstance(ch,discord.TextChannel):self.update_settings(guild.id,log_channel_id=ch.id); return ch
        me=guild.me
        if not me or not me.guild_permissions.manage_channels:return None
        try: ch=await guild.create_text_channel(LOG_CHANNEL_NAME,reason="Gogeta Anti-Nuke security logs")
        except (discord.Forbidden,discord.HTTPException):return None
        self.update_settings(guild.id,log_channel_id=ch.id); return ch

    async def get_or_create_quarantine_role(self,guild:discord.Guild)->discord.Role|None:
        me=guild.me
        if not me or not me.guild_permissions.manage_roles:return None
        role=guild.get_role(int(self.settings(guild.id).get('quarantine_role_id') or 0))
        if role is None: role=discord.utils.find(lambda r:r.name=='Gogeta Quarantine',guild.roles)
        try:
            if role is None: role=await guild.create_role(name='Gogeta Quarantine',colour=discord.Colour.from_rgb(237,66,69),reason='Gogeta Anti-Nuke quarantine')
            for channel in guild.channels:
                if isinstance(channel,(discord.TextChannel,discord.Thread,discord.ForumChannel,discord.StageChannel)):
                    try:
                        await channel.set_permissions(role,send_messages=False,add_reactions=False,create_public_threads=False,create_private_threads=False,send_messages_in_threads=False,reason='Gogeta Anti-Nuke quarantine policy')
                    except (discord.Forbidden,discord.HTTPException):
                        pass
            self.update_settings(guild.id,quarantine_role_id=role.id); self.invalidate(guild.id); return role
        except (discord.Forbidden,discord.HTTPException):
            return None

    async def configure_quarantine_role(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction): return
        guild=interaction.guild; assert guild is not None
        role=await self.get_or_create_quarantine_role(guild)
        if role is None:
            await interaction.response.send_message(embed=_embed('ANTI-NUKE / QUARANTINE FAILED','Bot needs Manage Roles and usable channel permission control.',0xED4245),ephemeral=False); return
        await interaction.response.send_message(embed=_embed('ANTI-NUKE / QUARANTINE READY',f'Using {role.mention}. The role is configured to restrict normal chat participation in accessible channels.',0x57F287),ephemeral=False)

    @staticmethod
    def _emoji(name: str) -> str:
        return E(name)

    def _setup_embed(self, guild: discord.Guild, statuses: dict[str, str], current: str | None, detail: str, *, final: bool=False, enabled: bool=False) -> discord.Embed:
        total=len(RULES)
        completed=sum(1 for v in statuses.values() if v in {"READY","WARN","FAILED","SKIPPED"})
        width=18; filled=max(0,min(width,round((completed/max(1,total))*width)))
        bar="━"*filled+"─"*(width-filled)
        title="ANTI-NUKE / DEPLOYMENT COMPLETE" if final else "ANTI-NUKE / LIVE SETUP"
        colour=0x57F287 if final and enabled else (0xED4245 if final and not enabled else 0x5865F2)
        e=_embed(title,f"{self._emoji('q_shield')} **Protection deployment**  ·  `{completed}/{total}` modules deployed\n`{bar}`\n\n{detail}",colour)
        success=self._emoji('q_success')
        deploying=self._emoji('diamond')
        bad=self._emoji('q_error')
        disabled=self._emoji('q_minus')
        rules=self.rules(guild.id); s=self.settings(guild.id)

        # IMPORTANT: only the completed prefix plus the one currently deploying
        # module is rendered. Future modules are intentionally hidden until the
        # previous module has been persisted/deployed. This prevents the setup
        # screen from looking like every module was pasted at once.
        ordered=list(RULES)
        visible_count=completed
        if current is not None and current in ordered:
            visible_count=max(visible_count, ordered.index(current)+1)
        visible=ordered[:visible_count]
        lines=[]
        for rule in visible:
            spec=RULES[rule]; state=statuses.get(rule,'QUEUED'); r=rules.get(rule,{})
            threshold=int(r.get('threshold',spec['threshold'])); window=int(r.get('window_seconds',spec['window']))
            action=str(r.get('action','inherit')); action=s['default_action'] if action=='inherit' else action
            marker={
                'READY':success, 'WARN':success, 'FAILED':bad,
                'SKIPPED':disabled, 'CHECKING':deploying,
            }.get(state, deploying)
            suffix='  ← deploying' if current==rule and state=='CHECKING' else ''
            lines.append(f"{marker} **{spec['label']}** · `{threshold}/{window}s` · `{action}`{suffix}")
        if lines:
            midpoint=(len(lines)+1)//2
            if len(lines) <= 12:
                e.add_field(name=f'MODULES · 01–{len(lines):02d}',value='\n'.join(lines),inline=False)
            else:
                e.add_field(name=f'MODULES · 01–{midpoint:02d}',value='\n'.join(lines[:midpoint]),inline=False)
                e.add_field(name=f'MODULES · {midpoint+1:02d}–{len(lines):02d}',value='\n'.join(lines[midpoint:]),inline=False)
        if final:e.add_field(name='FINAL STATE',value=f"{self._emoji('q_shield')} **{'ARMED' if enabled else 'NOT ARMED'}** · `/antinuke config` for configuration",inline=False)
        return e

    def _deploy_rule(self, guild: discord.Guild, rule: str) -> tuple[str, str]:
        """Validate and commit one Anti-Nuke module before revealing the next one."""
        status, reason = self._module_readiness(guild, rule)
        if status in {'READY', 'WARN'}:
            current = self.db.rule(guild.id, rule)
            # A module is considered deployed only after its current policy has
            # been successfully persisted. We do not overwrite custom values.
            self.db.update_rule(
                guild.id, rule,
                enabled=int(current['enabled']),
                threshold=int(current['threshold']),
                window_seconds=int(current['window_seconds']),
                action=str(current['action']),
                rollback=int(current['rollback']),
            )
            self.invalidate(guild.id)
            return 'READY', f"{self._emoji('q_success')} **{RULES[rule]['label']}** deployed and armed."
        return status, reason

    def _module_readiness(self, guild: discord.Guild, rule: str) -> tuple[str,str]:
        s=self.settings(guild.id); r=self.rules(guild.id)[rule]; me=guild.me
        if not r['enabled']:return 'SKIPPED','Module is disabled in configuration.'
        missing_listeners=[x for x in RULE_LISTENERS.get(rule,()) if not callable(getattr(self,x,None))]
        if missing_listeners:return 'FAILED','Missing listener: '+', '.join(missing_listeners)
        if not me or not me.guild_permissions.view_audit_log:return 'FAILED','View Audit Log is required for live actor correlation.'
        action=str(r['action']) if r['action']!='inherit' else str(s['default_action'])
        p=me.guild_permissions;missing=[]
        if action=='ban' and not p.ban_members:missing.append('Ban Members')
        elif action=='kick' and not p.kick_members:missing.append('Kick Members')
        elif action in {'strip_roles','quarantine'} and not p.manage_roles:missing.append('Manage Roles')
        if rule=='channel_create' and r['rollback'] and s['auto_rollback'] and not p.manage_channels:missing.append('Manage Channels (rollback)')
        if rule=='role_create' and r['rollback'] and s['auto_rollback'] and not p.manage_roles:missing.append('Manage Roles (rollback)')
        if missing:return 'FAILED','Missing permission: '+', '.join(missing)
        return 'READY',f"Live listener + audit correlation + `{action}` response ready."

    def adopt_requested_baseline_if_untouched(self, guild_id: int) -> None:
        """Move an untouched v3 stock install to the owner's requested ban baseline."""
        settings=self.settings(guild_id); current=self.rules(guild_id)
        if settings.get("default_action") != "strip_roles" or int(settings.get("global_threshold",3)) != 3 or int(settings.get("global_window",10)) != 10:
            return
        for rule,spec in RULES.items():
            row=current.get(rule)
            if not row or int(row["enabled"]) != 1:
                return
            legacy_threshold=LEGACY_ROLE_UPDATE_THRESHOLD if rule=="role_update" else int(spec["threshold"])
            if int(row["threshold"]) != legacy_threshold or int(row["window_seconds"]) != int(spec["window"]):
                return
            if str(row["action"]) != LEGACY_STOCK_ACTIONS.get(rule, "strip_roles"):
                return
        self.db.update_settings(guild_id,default_action="ban")
        for rule,spec in RULES.items():
            self.db.update_rule(guild_id,rule,enabled=1,threshold=int(spec["threshold"]),window_seconds=int(spec["window"]),action=str(spec["action"]),rollback=int(bool(spec["rollback"])))
        self.invalidate(guild_id)

    async def setup_wizard(self, interaction: discord.Interaction, *, reuse_message: bool=False) -> None:
        if not await self.guard(interaction): return
        guild=interaction.guild; assert guild is not None
        self.db.ensure(guild.id); self.invalidate(guild.id)
        self.adopt_requested_baseline_if_untouched(guild.id)
        statuses={rule:'QUEUED' for rule in RULES}; me=guild.me; s=self.settings(guild.id)
        audit_ok=bool(me and me.guild_permissions.view_audit_log)
        active=self.rules(guild.id); actions={str(r['action']) if r['action']!='inherit' else str(s['default_action']) for r in active.values() if r['enabled']} or {str(s['default_action'])}
        perm_fail=[]
        if 'ban' in actions and not (me and me.guild_permissions.ban_members):perm_fail.append('Ban Members')
        if 'kick' in actions and not (me and me.guild_permissions.kick_members):perm_fail.append('Kick Members')
        if {'strip_roles','quarantine'} & actions and not (me and me.guild_permissions.manage_roles):perm_fail.append('Manage Roles')
        base_detail=f"Gateway **online** · Audit Log **{'ready' if audit_ok else 'missing'}** · Enforcement **{'ready' if not perm_fail else 'missing: '+', '.join(dict.fromkeys(perm_fail))}**"
        initial=self._setup_embed(guild,statuses,None,base_detail)
        if reuse_message:
            await interaction.response.edit_message(embed=initial,view=None)
        else:
            await interaction.response.send_message(embed=initial,ephemeral=False)
        async def edit_setup(message_embed: discord.Embed) -> None:
            if reuse_message and interaction.message is not None:
                await interaction.message.edit(embed=message_embed,view=None)
            else:
                await interaction.edit_original_response(embed=message_embed)

        # The live animation is deliberately single-edit-per-module. The current
        # module is shown with the diamond while deployment happens; only after
        # deployment succeeds is that line changed to q_success and the NEXT
        # module revealed. This is both visually sequential and rate-limit safe.
        ordered=list(RULES)
        blocked_reason=None
        for index, rule in enumerate(ordered):
            statuses[rule]='CHECKING'
            if index == 0:
                await edit_setup(self._setup_embed(guild,statuses,rule,f"{self._emoji('diamond')} Deploying **{RULES[rule]['label']}** …"))
            await asyncio.sleep(1.05)
            try:
                status,reason=self._deploy_rule(guild,rule)
            except Exception as exc:
                status,reason='FAILED',f"Deployment exception: {type(exc).__name__}: {exc}"
            statuses[rule]=status

            if status == 'FAILED':
                blocked_reason=reason
                await edit_setup(self._setup_embed(guild,statuses,None,reason))
                break

            next_rule=ordered[index+1] if index+1 < len(ordered) else None
            if next_rule is not None:
                statuses[next_rule]='CHECKING'
                detail=f"{self._emoji('q_success')} **{RULES[rule]['label']}** deployed.  {self._emoji('q_shield')} Next: **{RULES[next_rule]['label']}**"
                await edit_setup(self._setup_embed(guild,statuses,next_rule,detail))
                # The message already shows the next module as deploying. Keep
                # its internal state queued until its deployment call begins.
                statuses[next_rule]='QUEUED'
            else:
                await edit_setup(self._setup_embed(guild,statuses,None,f"{self._emoji('q_success')} **{RULES[rule]['label']}** deployed."))

        failed=sum(v=='FAILED' for v in statuses.values())
        ok=audit_ok and not perm_fail and failed==0 and blocked_reason is None
        self.update_settings(guild.id,enabled=int(ok));self.invalidate(guild.id)
        skipped=sum(v=='SKIPPED' for v in statuses.values())
        detail=(f"{self._emoji('q_success')} All configured protection modules are deployed. `{len(RULES)-skipped}` active · `{skipped}` skipped by choice." if ok else f"{self._emoji('q_error')} Deployment stopped before all modules were armed. {blocked_reason or ('Fix required capabilities and use **Deploy / Repair** again.')}")
        final_embed=self._setup_embed(guild,statuses,None,detail,final=True,enabled=ok)
        if reuse_message and interaction.message is not None:
            await interaction.message.edit(embed=final_embed,view=ANView(self,interaction.user.id,guild.id,'overview'))
        else:
            await interaction.edit_original_response(embed=final_embed,view=ANView(self,interaction.user.id,guild.id,'overview'))

    async def setup_from_panel(self,interaction:discord.Interaction)->None:
        await self.setup_wizard(interaction,reuse_message=True)

    async def preflight(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction):return
        guild=interaction.guild; assert guild is not None
        me=guild.me; s=self.settings(guild.id)
        actions_needed={str(r['action']) if r['action']!='inherit' else str(s['default_action']) for r in self.rules(guild.id).values() if r['enabled']} or {str(s['default_action'])}
        checks=[_check_line("View Audit Log",bool(me and me.guild_permissions.view_audit_log))]
        need_roles='strip_roles' in actions_needed or 'quarantine' in actions_needed; need_kick='kick' in actions_needed; need_ban='ban' in actions_needed
        checks.append(_check_line("Manage Roles",not need_roles or bool(me and me.guild_permissions.manage_roles),"required by active response" if need_roles else "not required"))
        checks.append(_check_line("Kick Members",not need_kick or bool(me and me.guild_permissions.kick_members),"required by active response" if need_kick else "not required"))
        checks.append(_check_line("Ban Members",not need_ban or bool(me and me.guild_permissions.ban_members),"required by active response" if need_ban else "not required"))
        ch=await self.ensure_log_channel(guild); checks.append(_check_line("Security Log",bool(ch),ch.mention if ch else "optional"))
        ok=bool(me and me.guild_permissions.view_audit_log) and (not need_roles or bool(me and me.guild_permissions.manage_roles)) and (not need_kick or bool(me and me.guild_permissions.kick_members)) and (not need_ban or bool(me and me.guild_permissions.ban_members))
        self.update_settings(guild.id,enabled=int(ok)); self.invalidate(guild.id)
        e=_embed("ANTI-NUKE / HEALTH CHECK","Quick validation only. `/antinuke setup` is the animated deployment wizard.",0x57F287 if ok else 0xED4245);e.add_field(name="CHECKS",value="\n".join(checks),inline=False);e.add_field(name="ACTIVE",value=f"{sum(1 for r in self.rules(guild.id).values() if r['enabled'])}/{len(RULES)} modules",inline=True)
        await interaction.response.send_message(embed=e,view=ANView(self,interaction.user.id,guild.id,"overview"),ephemeral=False)

    async def ui_save(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction):return
        gid=interaction.guild.id;self.db.ensure(gid);self.invalidate(gid)
        await interaction.response.send_message(embed=_embed("ANTI-NUKE / SAVED",f"{E('q_check')} Current protection configuration is persisted. No modules were changed by Save." ,0x57F287),ephemeral=False)
    async def ui_disable(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction):return
        self.update_settings(interaction.guild.id,enabled=0); self.invalidate(interaction.guild.id); await interaction.response.edit_message(embed=self.panel(interaction.guild.id,"overview"),view=ANView(self,interaction.user.id,interaction.guild.id))

    def update_settings(self,guild_id:int,**fields:object)->None:self.db.update_settings(guild_id,**fields)
    def update_rule(self,guild_id:int,rule:str,**fields:object)->None:self.db.update_rule(guild_id,rule,**fields)

    def apply_preset(self,guild_id:int,preset:str)->None:
        self.db.ensure(guild_id)
        if preset=="observe":
            self.update_settings(guild_id,default_action="log_only",global_threshold=3,global_window=10)
            for name in RULES:self.update_rule(guild_id,name,enabled=True,action="log_only")
        elif preset=="strict":
            self.update_settings(guild_id,default_action="ban",global_threshold=2,global_window=8)
            for name,spec in RULES.items():self.update_rule(guild_id,name,enabled=True,threshold=max(1,int(spec["threshold"])-1),window_seconds=max(5,int(spec["window"])),action="inherit")
        else:
            self.update_settings(guild_id,default_action="strip_roles",global_threshold=3,global_window=10)
            for name,spec in RULES.items():self.update_rule(guild_id,name,enabled=True,threshold=int(spec["threshold"]),window_seconds=int(spec["window"]),action="inherit",rollback=int(bool(spec["rollback"])))
        self.invalidate(guild_id)

    async def arm_all(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction):return
        for r in RULES:self.update_rule(interaction.guild.id,r,enabled=1)
        self.invalidate(interaction.guild.id); await interaction.response.edit_message(embed=self.panel(interaction.guild.id,"modules"),view=ANView(self,interaction.user.id,interaction.guild.id,"modules"))
    async def disarm_all(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction):return
        for r in RULES:self.update_rule(interaction.guild.id,r,enabled=0)
        self.invalidate(interaction.guild.id); await interaction.response.edit_message(embed=self.panel(interaction.guild.id,"modules"),view=ANView(self,interaction.user.id,interaction.guild.id,"modules"))

    async def _apply_response(self,guild:discord.Guild,actor:discord.abc.User,action:str,rule_name:str,s:dict)->None:
        reason=f"Gogeta Anti-Nuke: {RULES[rule_name]['label']}"
        if action=="log_only":return
        if action=="strip_roles":
            member=actor if isinstance(actor,discord.Member) else guild.get_member(actor.id)
            if member is None:raise RuntimeError("Actor is no longer a guild member.")
            if not guild.me or not guild.me.guild_permissions.manage_roles:raise RuntimeError("Bot lacks Manage Roles.")
            removable=[r for r in member.roles if r.is_assignable()]
            stuck=[r for r in member.roles if not r.is_default() and not r.is_assignable() and not r.managed]
            if removable:await member.remove_roles(*removable,reason=reason)
            if stuck:raise RuntimeError("Role hierarchy prevents removing: "+", ".join(r.name for r in stuck[:5]))
        elif action=="quarantine":
            member=actor if isinstance(actor,discord.Member) else guild.get_member(actor.id)
            if member is None:raise RuntimeError("Actor is no longer a guild member.")
            role=guild.get_role(int(s.get("quarantine_role_id") or 0)) or await self.get_or_create_quarantine_role(guild)
            if role is None:raise RuntimeError("No quarantine role configured/available.")
            await member.add_roles(role,reason=reason)
        elif action=="kick":
            await guild.kick(discord.Object(id=actor.id),reason=reason)
        elif action=="ban":
            await guild.ban(discord.Object(id=actor.id),reason=reason,delete_message_seconds=0)
        else:raise RuntimeError(f"Unsupported action: {action}")

    async def contain(self,guild:discord.Guild,actor:discord.abc.User,rule_name:str,target_id:int|None,detail:str,corrections:list[Callable[[],Awaitable[None]]]|None=None)->None:
        lock=self._lock(guild.id,actor.id)
        async with lock:
            key=(guild.id,actor.id); now=time.monotonic(); s=self.settings(guild.id)
            last,last_ok=self._contained.get(key,(float("-inf"),True))
            # A successful containment suppresses repeats for the cooldown; a FAILED one retries almost
            # immediately (it used to be silenced for the full cooldown, leaving the attacker free).
            if now-last<(float(s["actor_cooldown"]) if last_ok else FAILED_RETRY_COOLDOWN):return
            r=self.db.rule(guild.id,rule_name); configured=r["action"] if r["action"]!="inherit" else s["default_action"]
            chain=FALLBACKS.get(str(configured),(str(configured),))
            success=False; used=str(configured); notes=[]
            for step in chain:
                try:
                    await self._apply_response(guild,actor,step,rule_name,s); success=True; used=step
                    if step!=str(configured):notes.append(f"fallback: `{configured}` failed, applied `{step}`")
                    break
                except discord.NotFound:
                    success=True; used=step; break
                except (discord.Forbidden,discord.HTTPException,RuntimeError) as exc:
                    notes.append(f"{step}: {exc}")
                except Exception as exc:  # never let an unexpected error skip the incident record / next fallback
                    notes.append(f"{step}: {type(exc).__name__}: {exc}")
            self._contained[key]=(time.monotonic(),success)
            # Roll back EVERYTHING this actor did recently (not just the event that tripped the threshold).
            todo=[c for t,c in self._pending.pop(key,()) if now-t<ROLLBACK_MEMORY]
            for c in (corrections or []):
                if c not in todo:todo.append(c)
            if todo and s["auto_rollback"] and r["rollback"]:
                done=0
                for correction in todo:
                    try:await correction(); done+=1
                    except discord.NotFound:done+=1
                    except (discord.Forbidden,discord.HTTPException) as exc:notes.append(f"rollback: {exc}")
                if done:notes.append(f"rolled back {done} change(s)")
            detail=_safe((detail+" "+" ".join(notes)).strip())
            self.db.incident(guild.id,actor.id,target_id,rule_name,used,success,detail)
            await self.write_log(guild,actor,rule_name,used,success,detail)
            self._events.get(guild.id,{}).pop(actor.id,None)

    async def write_log(self,guild:discord.Guild,actor:discord.abc.User|None,rule:str,action:str,success:bool,detail:str)->None:
        ch=guild.get_channel(int(self.settings(guild.id).get("log_channel_id") or 0))
        if not isinstance(ch,discord.TextChannel):return
        actor_label = getattr(actor, 'mention', None) or f'`{getattr(actor, "id", 0)}`'
        e = _embed(f"ANTI-NUKE / {'CONTAINED' if success else 'ACTION FAILED'}", f"**Actor:** {actor_label}\n**Module:** `{RULES.get(rule, {}).get('label', rule)}`\n**Response:** `{action}`\n\n{detail}", 0x57F287 if success else 0xED4245)
        try:await ch.send(embed=e,allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden,discord.HTTPException):pass

    async def process(self,guild:discord.Guild,rule:str,actions:list[object],*,target_id:int|None=None,actor:discord.abc.User|None=None,detail:str="",corrections:list[Callable[[],Awaitable[None]]]|None=None)->None:
        try:
            s=self.settings(guild.id); r=self.db.rule(guild.id,rule)
            if not s["enabled"] or not r["enabled"]:return
            if actor is None:
                entry=await self.audit_entry(guild,actions,target_id); actor=entry.user if entry else None
                if actor is None:
                    now=time.monotonic(); k=(guild.id,rule)
                    if now-self._unattributed.get(k,float("-inf"))>60:
                        self._unattributed[k]=now
                        print(f"[AntiNuke] guild={guild.id} rule={rule}: no matching audit-log entry (missing View Audit Log, or Discord delayed it) - action NOT attributed")
                    return
            if self.actor_exempt(guild,actor):return
            if corrections and r["rollback"] and s["auto_rollback"]:
                pend=self._pending[(guild.id,actor.id)]
                for c in corrections:pend.append((time.monotonic(),c))
            count,global_count=self._record(guild.id,actor.id,rule,int(r["window_seconds"]))
            if count>=int(r["threshold"]) or global_count>=int(s["global_threshold"]):
                await self.contain(guild,actor,rule,target_id,detail or "Protection threshold reached.",corrections)
        except Exception as exc:
            print(f"[AntiNuke] Event processing failed in guild={guild.id}, rule={rule}: {type(exc).__name__}: {exc}")

    async def handle_bot_add(self,member:discord.Member)->None:
        guild=member.guild; s=self.settings(guild.id)
        if not s["enabled"] or not s["bots_require_trust"] or not self.db.rule(guild.id,"bot_add")["enabled"]:return
        _,_,bots=self.trust(guild.id)
        if member.id in bots:return
        # Remove the bot IMMEDIATELY. The audit-log lookup (with retries) used to run first, giving an
        # untrusted bot with permissions over a second to act before it was kicked.
        ok=True; detail="Untrusted bot was removed."; used="kick_bot"
        try:await member.kick(reason="Gogeta Anti-Nuke: untrusted bot")
        except discord.NotFound:pass
        except (discord.Forbidden,discord.HTTPException) as exc:
            try:
                await guild.ban(discord.Object(id=member.id),reason="Gogeta Anti-Nuke: untrusted bot (kick failed)",delete_message_seconds=0); used="ban_bot"; detail="Untrusted bot was banned (kick failed)."
            except (discord.Forbidden,discord.HTTPException) as exc2:
                ok=False; detail=f"Could not remove bot: kick={exc}; ban={exc2}. Move the Gogeta role above the bot's role."
        entry=await self.audit_entry(guild,[self._audit_value("bot_add")],member.id); actor=entry.user if entry else None
        self.db.incident(guild.id,getattr(actor,"id",None),member.id,"bot_add",used,ok,detail); await self.write_log(guild,actor,"bot_add",used,ok,detail)
        if actor and not self.actor_exempt(guild,actor):await self.process(guild,"bot_add",[],target_id=member.id,actor=actor,detail="An untrusted bot was added.")

    # ---- listeners ----
    @commands.Cog.listener()
    async def on_member_ban(self,guild:discord.Guild,user:discord.User)->None:
        self._recent_bans[(guild.id,user.id)]=time.monotonic(); await self.process(guild,"ban",[self._audit_value("ban")],target_id=user.id)
    @commands.Cog.listener()
    async def on_member_remove(self,member:discord.Member)->None:
        key=(member.guild.id,member.id)
        if self._recent_bans.get(key) and time.monotonic()-self._recent_bans[key]<5:return
        entry=await self.audit_entry(member.guild,[self._audit_value("kick"),self._audit_value("member_prune")],member.id,retries=(0.0,0.6))
        if not entry:return
        action_name=getattr(entry.action,"name","")
        rule="prune_members" if action_name=="member_prune" else "kick"
        await self.process(member.guild,rule,[],target_id=member.id,actor=entry.user,detail="Audit action: "+(action_name or "member_remove"))
    @commands.Cog.listener()
    async def on_member_join(self,member:discord.Member)->None:
        if member.bot:await self.handle_bot_add(member)
    @commands.Cog.listener()
    async def on_guild_channel_create(self,channel:discord.abc.GuildChannel)->None:
        async def rollback()->None:
            if hasattr(channel,"delete"):await channel.delete(reason="Gogeta Anti-Nuke: rollback channel creation")
        await self.process(channel.guild,"channel_create",[self._audit_value("channel_create")],target_id=channel.id,corrections=[rollback])
    @commands.Cog.listener()
    async def on_guild_channel_delete(self,channel:discord.abc.GuildChannel)->None:await self.process(channel.guild,"channel_delete",[self._audit_value("channel_delete")],target_id=channel.id)
    @commands.Cog.listener()
    async def on_guild_channel_update(self,before:discord.abc.GuildChannel,after:discord.abc.GuildChannel)->None:await self.process(after.guild,"channel_update",[self._audit_value("channel_update")],target_id=after.id)
    @commands.Cog.listener()
    async def on_guild_role_create(self,role:discord.Role)->None:
        dangerous=any(getattr(role.permissions,p,False) for p in DANGEROUS_PERMS); rule="role_dangerous" if dangerous else "role_create"
        async def rollback()->None:await role.delete(reason="Gogeta Anti-Nuke: rollback role creation")
        await self.process(role.guild,rule,[self._audit_value("role_create")],target_id=role.id,detail="Dangerous permissions detected." if dangerous else "Role created.",corrections=[rollback])
    @commands.Cog.listener()
    async def on_guild_role_delete(self,role:discord.Role)->None:await self.process(role.guild,"role_delete",[self._audit_value("role_delete")],target_id=role.id)
    @commands.Cog.listener()
    async def on_guild_role_update(self,before:discord.Role,after:discord.Role)->None:
        dangerous=[p for p in DANGEROUS_PERMS if getattr(after.permissions,p,False) and not getattr(before.permissions,p,False)]
        async def restore()->None:await after.edit(permissions=before.permissions,reason="Gogeta Anti-Nuke: rollback dangerous permission grant")
        if dangerous:
            await self.process(after.guild,"everyone_dangerous" if after.is_default() else "role_dangerous",[self._audit_value("role_update")],target_id=after.id,detail="Added: "+", ".join(dangerous),corrections=[restore])
        else:await self.process(after.guild,"role_update",[self._audit_value("role_update")],target_id=after.id)
    @commands.Cog.listener()
    async def on_member_update(self,before:discord.Member,after:discord.Member)->None:
        added=[r for r in after.roles if r not in before.roles and any(getattr(r.permissions,p,False) for p in DANGEROUS_PERMS)]
        if not added:return
        entry=await self.audit_entry(after.guild,[self._audit_value("member_role_update")],after.id); actor=entry.user if entry else None
        async def rollback()->None:await after.remove_roles(*added,reason="Gogeta Anti-Nuke: rollback privileged role grant")
        await self.process(after.guild,"member_role_grant",[],target_id=after.id,actor=actor,detail="Privileged role(s) granted.",corrections=[rollback])
    @commands.Cog.listener()
    async def on_webhooks_update(self,channel:discord.abc.GuildChannel)->None:
        acts=[self._audit_value("webhook_create"),self._audit_value("webhook_update"),self._audit_value("webhook_delete")]; entry=await self.audit_entry(channel.guild,acts); 
        if not entry:return
        mapping={"webhook_create":"webhook_create","webhook_update":"webhook_update","webhook_delete":"webhook_delete"}; name=getattr(entry.action,"name","")
        if name in mapping: await self.process(channel.guild, mapping[name], [], actor=entry.user, detail=f"Webhook action: {name}.")
    @commands.Cog.listener()
    async def on_guild_update(self,before:discord.Guild,after:discord.Guild)->None:
        watched=("name","vanity_url_code","verification_level","explicit_content_filter","default_notifications","mfa_level","afk_channel","afk_timeout","system_channel","rules_channel","public_updates_channel","icon","banner","splash","description","preferred_locale","owner_id")
        def _v(g,attr):
            v=getattr(g,attr,None); return getattr(v,"id",v) if not isinstance(v,(str,int,float,bool,type(None))) else v
        changed=[a for a in watched if _v(before,a)!=_v(after,a)]
        if changed:await self.process(after,"guild_update",[self._audit_value("guild_update")],detail="Changed: "+", ".join(changed))
    @commands.Cog.listener()
    async def on_integration_create(self,integration:discord.Integration)->None:await self.process(integration.guild,"integration_change",[self._audit_value("integration_create")],target_id=integration.id)
    @commands.Cog.listener()
    async def on_integration_update(self,integration:discord.Integration)->None:await self.process(integration.guild,"integration_change",[self._audit_value("integration_update")],target_id=integration.id)
    @commands.Cog.listener()
    async def on_integration_delete(self,integration:discord.Integration)->None:await self.process(integration.guild,"integration_change",[self._audit_value("integration_delete")],target_id=integration.id)
    @commands.Cog.listener()
    async def on_guild_emojis_update(self,guild:discord.Guild,before:tuple,after:tuple)->None:await self.process(guild,"emoji_change",[self._audit_value("emoji_create"),self._audit_value("emoji_update"),self._audit_value("emoji_delete")])
    @commands.Cog.listener()
    async def on_guild_stickers_update(self,guild:discord.Guild,before:tuple,after:tuple)->None:await self.process(guild,"sticker_change",[self._audit_value("sticker_create"),self._audit_value("sticker_update"),self._audit_value("sticker_delete")])
    @commands.Cog.listener()
    async def on_thread_create(self,thread:discord.Thread)->None:await self.process(thread.guild,"thread_create",[self._audit_value("thread_create")],target_id=thread.id)
    @commands.Cog.listener()
    async def on_thread_delete(self,thread:discord.Thread)->None:await self.process(thread.guild,"thread_delete",[self._audit_value("thread_delete")],target_id=thread.id)
    @commands.Cog.listener()
    async def on_thread_update(self,before:discord.Thread,after:discord.Thread)->None:await self.process(after.guild,"thread_update",[self._audit_value("thread_update")],target_id=after.id)
    @commands.Cog.listener()
    async def on_scheduled_event_create(self,event:discord.ScheduledEvent)->None:await self.process(event.guild,"scheduled_event_change",[self._audit_value("scheduled_event_create")],target_id=event.id)
    @commands.Cog.listener()
    async def on_scheduled_event_update(self,before:discord.ScheduledEvent,after:discord.ScheduledEvent)->None:await self.process(after.guild,"scheduled_event_change",[self._audit_value("scheduled_event_update")],target_id=after.id)
    @commands.Cog.listener()
    async def on_scheduled_event_delete(self,event:discord.ScheduledEvent)->None:await self.process(event.guild,"scheduled_event_change",[self._audit_value("scheduled_event_delete")],target_id=event.id)

    def panel(self,guild_id:int,page:str="overview")->discord.Embed:
        s=self.settings(guild_id); rules=self.rules(guild_id); users,roles,bots=self.trust(guild_id); colour=0x57F287 if s["enabled"] else 0x747F8D; armed=sum(1 for r in rules.values() if r["enabled"])
        if page=="modules":
            e=_embed("ANTI-NUKE / PROTECTION MATRIX",f"**{armed}/{len(RULES)}** modules armed. Select one to edit its entire policy.",colour); lines=[]
            for name,spec in RULES.items():
                r=rules[name]; mark=E("q_check") if r["enabled"] else E("q_minus"); act=r["action"] if r["action"]!="inherit" else s["default_action"]; lines.append(f"{mark} **{spec['label']}** · `{r['threshold']}/{r['window_seconds']}s` · `{act}`")
            e.add_field(name="MODULES",value="\n".join(lines),inline=False); return e
        if page=="policy":
            e=_embed("ANTI-NUKE / RESPONSE POLICY", "Global circuit breaker + per-module overrides.",colour); e.add_field(name="GLOBAL BURST",value=f"`{s['global_threshold']}` actions / `{s['global_window']}s`",inline=True); e.add_field(name="DEFAULT",value=f"`{_action_name(s['default_action'])}`",inline=True); e.add_field(name="COOLDOWN",value=f"`{s['actor_cooldown']}s`",inline=True); return e
        if page=="trust":
            e=_embed("ANTI-NUKE / TRUST MATRIX","Explicit exemptions. The owner can be made immune independently.",colour); e.add_field(name="USERS",value=f"`{len(users)}`",inline=True); e.add_field(name="ROLES",value=f"`{len(roles)}`",inline=True); e.add_field(name="BOTS",value=f"`{len(bots)}`",inline=True); e.add_field(name="OWNER",value="IMMUNE" if s["owner_immune"] else "PROTECTED",inline=True); e.add_field(name="BOT POLICY",value="Trust list required" if s["bots_require_trust"] else "Normal actor policy",inline=True); return e
        if page=="recovery":
            e=_embed("ANTI-NUKE / RECOVERY", "Rollback is only attempted for explicitly supported mutations and never bypasses Discord permissions.",colour); e.add_field(name="AUTO ROLLBACK",value="ON" if s["auto_rollback"] else "OFF",inline=True); e.add_field(name="QUARANTINE ROLE",value=(f"<@&{s['quarantine_role_id']}>" if s.get("quarantine_role_id") else "Not configured"),inline=True); return e
        if page=="logs":
            rows=self.db.incidents(guild_id,10); e=_embed("ANTI-NUKE / INCIDENT LEDGER","Persistent containment and failure records.",0xFEE75C if rows else colour); e.add_field(name="RECENT",value="\n\n".join(f"<t:{r['timestamp']}:R> • <@{r['actor_id'] or 0}> • **{RULES.get(r['rule'],{}).get('label',r['rule'])}** → `{r['action']}` {'✅' if r['success'] else '❌'}" for r in rows) or "No incidents recorded.",inline=False); return e
        e=_embed("GOGETA / ANTI-NUKE v3","A native interaction-based destructive-action firewall. Every module, response and trust rule is independently configurable.",colour); e.add_field(name="STATUS",value=E("q_online")+" ONLINE" if s["enabled"] else E("q_offline")+" OFFLINE",inline=True); e.add_field(name="MODULES",value=f"`{armed}/{len(RULES)}` armed",inline=True); e.add_field(name="BURST",value=f"`{s['global_threshold']}/{s['global_window']}s`",inline=True); e.add_field(name="DEFAULT ACTION",value=f"`{_action_name(s['default_action'])}`",inline=True); e.add_field(name="TRUST",value=f"`{len(users)}` users · `{len(roles)}` roles · `{len(bots)}` bots",inline=True); e.add_field(name="LOG ROUTE",value=(f"<#{s['log_channel_id']}>" if s.get('log_channel_id') else "Not configured"),inline=True); return e

    @antinuke_group.command(name="setup",description="Run the animated Anti-Nuke deployment wizard.")
    async def setup_cmd(self,interaction:discord.Interaction)->None:
        await self.setup_wizard(interaction)
    @antinuke_group.command(name="config",description="Open the Anti-Nuke control center without running setup.")
    async def config_cmd(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction):return
        await interaction.response.send_message(embed=self.panel(interaction.guild.id),view=ANView(self,interaction.user.id,interaction.guild.id),ephemeral=False)
    @antinuke_group.command(name="disable",description="Disable the Anti-Nuke firewall.")
    async def disable_cmd(self,interaction:discord.Interaction)->None:
        if not await self.guard(interaction):return
        self.update_settings(interaction.guild.id,enabled=0); self.invalidate(interaction.guild.id); await interaction.response.send_message(embed=_embed("ANTI-NUKE / OFFLINE","Firewall disabled.",0x747F8D),ephemeral=False)
    @antinuke_group.command(name="whitelist",description="Manage Anti-Nuke trust exemptions.")
    @app_commands.describe(kind="User, role or bot",action="Add or remove",user="User target",role="Role target",bot="Bot target")
    @app_commands.choices(kind=[app_commands.Choice(name="User",value="user"),app_commands.Choice(name="Role",value="role"),app_commands.Choice(name="Bot",value="bot")],action=[app_commands.Choice(name="Add",value="add"),app_commands.Choice(name="Remove",value="remove")])
    async def whitelist_cmd(self,interaction:discord.Interaction,kind:app_commands.Choice[str],action:app_commands.Choice[str],user:discord.Member|None=None,role:discord.Role|None=None,bot:discord.Member|None=None)->None:
        if not await self.guard(interaction):return
        target={"user":user,"role":role,"bot":bot}[kind.value]
        if target is None or (kind.value=="bot" and not target.bot):await interaction.response.send_message(embed=_embed("ANTI-NUKE / INVALID TARGET","Select the matching target.",0xED4245),ephemeral=False);return
        self.db.trust(interaction.guild.id,kind.value,target.id,action.value=="add");self.invalidate(interaction.guild.id);await interaction.response.send_message(embed=_embed("ANTI-NUKE / TRUST UPDATED",f"{target.mention} was {'trusted' if action.value=='add' else 'untrusted'}.",0x57F287),ephemeral=False)
    @commands.hybrid_command(name="antinuke-incidents",description="View Anti-Nuke incidents.")
    async def incidents_cmd(self,ctx:commands.Context)->None:
        if not await self.guard_ctx(ctx):return
        rows=self.db.incidents(ctx.guild.id,20); text="\n".join(f"<t:{r['timestamp']}:R> • <@{r['actor_id'] or 0}> • {RULES.get(r['rule'],{}).get('label',r['rule'])} → `{r['action']}` {'OK' if r['success'] else 'FAILED'}" for r in rows) or "No incidents."; await ctx.send(embed=_embed("ANTI-NUKE / INCIDENTS",text,0xFEE75C if rows else 0x5865F2),allowed_mentions=discord.AllowedMentions.none())


async def setup(bot:commands.Bot)->None:
    await bot.add_cog(Antinuke(bot))
