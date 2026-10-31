# Credits: gogeta_gg
"""Gogeta Anti-Betray — privileged-identity threat monitor.

Anti-Betray complements Anti-Nuke: Anti-Nuke protects against destructive
activity in general, while this layer specifically watches privileged or
explicitly watched identities. It is audit-log driven, rate based, and
serialized per actor to avoid duplicate containment.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

import discord
from discord import app_commands
from discord.ext import commands

from . import antibetray_db, antinuke_db
from .security_ui import AdminModal, AdminView, security_embed, check_line, state
from ui import embeds as ui
from ui.emoji import E
from ui.theme import Color

LABELS = {
    "trusted_mass_ban": "Trusted Mass Ban",
    "trusted_mass_kick": "Trusted Mass Kick",
    "trusted_channel_delete": "Trusted Channel Destruction",
    "trusted_role_delete": "Trusted Role Destruction",
    "trusted_dangerous_role": "Trusted Dangerous Role Change",
    "trusted_member_role_grant": "Trusted Privileged Role Grant",
    "trusted_bot_add": "Trusted Bot Addition",
    "trusted_webhook": "Trusted Webhook Change",
    "trusted_role_create": "Trusted Role Creation",
    "trusted_guild_change": "Trusted Server Change",
    "trusted_integration": "Trusted Integration Change",
}
CATEGORY_LABELS = LABELS  # compatibility alias used by the web serializers

DANGEROUS_PERMS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "manage_webhooks", "ban_members", "kick_members", "manage_messages",
    "mention_everyone",
)
LOG_CHANNEL_NAME = "gogeta-security-logs"
CACHE_TTL = 3.0
AUDIT_MAX_AGE = 12.0
AUDIT_RETRY_DELAYS = (0.0, 0.35, 0.85)
AUDIT_SEEN_TTL = 20.0


def _bar(value: int, total: int, width: int = 10) -> str:
    total = max(1, total)
    filled = max(0, min(width, round(value / total * width)))
    return "▰" * filled + "▱" * (width - filled)


def _safe(text: str | None) -> str:
    return (text or "").replace("@everyone", "@\u000beveryone").replace("@here", "@\u000bhere")[:1200]


def panel_embed(guild: discord.Guild, cog: "Antibetray", page: str = "overview") -> discord.Embed:
    settings = cog.settings(guild.id)
    enabled = bool(settings["enabled"])
    colour = Color.MODERATION if enabled else Color.NEUTRAL
    armed = sum(antibetray_db.is_category_enabled(guild.id, cat) for cat in antibetray_db.CATEGORIES)

    if page == "threats":
        embed = security_embed(
            "ANTI-BETRAY / THREAT MATRIX",
            f"`{armed}/{len(antibetray_db.CATEGORIES)}` trusted-identity lanes are armed.",
            colour,
            icon=E("q_lock"),
        )
        lines = []
        for category in antibetray_db.CATEGORIES:
            rule = antibetray_db.get_rule(guild.id, category)
            mark = E("q_online") if rule["enabled"] else E("q_offline")
            lines.append(f"{mark} **{LABELS[category]}** · `{rule['threshold']}/{rule['window_seconds']}s`")
        embed.add_field(name="THREAT LANES", value="\n".join(lines), inline=False)
        return embed

    if page == "policy":
        embed = security_embed(
            "ANTI-BETRAY / CONTAINMENT POLICY",
            "Containment occurs when either a lane threshold or the global actor burst threshold is reached.",
            colour,
            icon=E("q_admin"),
        )
        embed.add_field(name="GLOBAL BURST", value=f"`{settings['threshold']}` actions\nwithin `{settings['window_seconds']}s`", inline=True)
        embed.add_field(name="RESPONSE", value=f"`{settings['punishment'].replace('_', ' ').title()}`", inline=True)
        embed.add_field(name="ARMED", value=f"`{armed}/{len(antibetray_db.CATEGORIES)}`\n{_bar(armed, len(antibetray_db.CATEGORIES))}", inline=True)
        return embed

    if page == "trust":
        users = antibetray_db.list_trusted_users(guild.id)
        roles = antibetray_db.list_trusted_roles(guild.id)
        embed = security_embed(
            "ANTI-BETRAY / WATCH LIST",
            "The watch list adds identities to monitoring; it does not exempt them. Privileged staff are watched automatically.",
            colour,
            icon=E("q_lock"),
        )
        embed.add_field(name="EXPLICIT USERS", value=f"`{len(users)}`", inline=True)
        embed.add_field(name="EXPLICIT ROLES", value=f"`{len(roles)}`", inline=True)
        embed.add_field(name="PRIVILEGED STAFF", value="Admins and members with server-management powers are automatically monitored.", inline=False)
        return embed

    if page == "incidents":
        rows = antibetray_db.get_incidents(guild.id, 8)
        embed = security_embed(
            "ANTI-BETRAY / INCIDENT LEDGER",
            "Recent privileged-identity activity and containment results.",
            Color.WARNING if rows else Color.NEUTRAL,
            icon=E("q_logs"),
        )
        lines = []
        for row in rows:
            mark = E("q_success") if row["success"] else E("q_error")
            actor = f"<@{row['user_id']}>" if row["user_id"] else "Unknown actor"
            lines.append(f"{mark} <t:{row['timestamp']}:R> {actor}\n↳ **{LABELS.get(row['category'], row['category'])}** → `{row['punishment']}`")
        embed.add_field(name="RECENT EVENTS", value="\n\n".join(lines) if lines else "`No incidents recorded.`", inline=False)
        return embed

    embed = security_embed(
        "GOGETA / ANTI-BETRAY",
        "Insider-threat monitoring for privileged and explicitly watched identities.",
        colour,
        icon=E("q_lock"),
    )
    embed.add_field(name="STATUS", value=state(enabled), inline=True)
    embed.add_field(name="BURST", value=f"`{settings['threshold']}/{settings['window_seconds']}s`", inline=True)
    embed.add_field(name="RESPONSE", value=f"`{settings['punishment'].replace('_', ' ').title()}`", inline=True)
    embed.add_field(name="WATCH LIST", value=f"`{len(antibetray_db.list_trusted_users(guild.id))}` users · `{len(antibetray_db.list_trusted_roles(guild.id))}` roles", inline=True)
    embed.add_field(name="ANTI-NUKE TRUST", value=f"`{len(antinuke_db.list_whitelisted_users(guild.id))}` users · `{len(antinuke_db.list_whitelisted_roles(guild.id))}` roles", inline=True)
    embed.add_field(name="LOG ROUTE", value=f"<#{settings['log_channel_id']}>" if settings.get("log_channel_id") else "`Not deployed`", inline=True)
    return embed


class PolicyModal(AdminModal, title="Anti-Betray • Containment Policy"):
    threshold = discord.ui.TextInput(label="Global actions before containment", placeholder="3", max_length=2, required=True)
    window = discord.ui.TextInput(label="Global window in seconds", placeholder="12", max_length=3, required=True)
    punishment = discord.ui.TextInput(label="Punishment: strip_roles / kick / ban", placeholder="strip_roles", max_length=20, required=True)

    def __init__(self, cog: "Antibetray", guild_id: int, parent: "AntibetrayView"):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        try:
            antibetray_db.set_threshold(self.guild_id, int(str(self.threshold).strip()), int(str(self.window).strip()))
            antibetray_db.set_punishment(self.guild_id, str(self.punishment).strip())
        except (ValueError, TypeError) as exc:
            await interaction.response.send_message(embed=ui.error("ANTI-BETRAY / INVALID POLICY", str(exc)), ephemeral=True)
            return
        self.cog.invalidate(self.guild_id)
        self.parent.page = "policy"
        self.parent.build()
        await interaction.response.edit_message(embed=panel_embed(interaction.guild, self.cog, "policy"), view=self.parent)


class TrustModal(AdminModal, title="Anti-Betray • Watch Identity"):
    target_id = discord.ui.TextInput(label="Discord ID", placeholder="User or role ID", max_length=20, required=True)
    kind = discord.ui.TextInput(label="Type", placeholder="user / role", max_length=4, required=True)
    action = discord.ui.TextInput(label="Action", placeholder="add / remove", max_length=6, required=True)

    def __init__(self, cog: "Antibetray", guild_id: int, parent: "AntibetrayView"):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        try:
            target_id = int(str(self.target_id).strip())
        except (ValueError, TypeError):
            await interaction.response.send_message(embed=ui.error("ANTI-BETRAY / INVALID ID", "The Discord ID must be numeric."), ephemeral=True)
            return
        kind = str(self.kind).strip().lower()
        action = str(self.action).strip().lower()
        if kind not in {"user", "role"} or action not in {"add", "remove"}:
            await interaction.response.send_message(embed=ui.error("ANTI-BETRAY / INVALID ACTION", "Use `user` or `role` and `add` or `remove`."), ephemeral=True)
            return
        add = action == "add"
        if kind == "user":
            (antibetray_db.add_trusted_user if add else antibetray_db.remove_trusted_user)(self.guild_id, target_id)
        else:
            (antibetray_db.add_trusted_role if add else antibetray_db.remove_trusted_role)(self.guild_id, target_id)
        self.cog.invalidate(self.guild_id)
        self.parent.page = "trust"
        self.parent.build()
        await interaction.response.edit_message(embed=panel_embed(interaction.guild, self.cog, "trust"), view=self.parent)


class AntibetrayView(AdminView):
    def __init__(self, cog: "Antibetray", author_id: int, guild_id: int, page: str = "overview"):
        super().__init__(author_id, timeout=900)
        self.cog = cog
        self.guild_id = guild_id
        self.page = page
        self.build()

    def build(self):
        self.clear_items()
        for label, target in (
            ("Overview", "overview"),
            ("Threats", "threats"),
            ("Policy", "policy"),
            ("Watch List", "trust"),
            ("Incidents", "incidents"),
        ):
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary if self.page == target else discord.ButtonStyle.secondary, row=0)
            button.callback = self._switch(target)
            self.add_item(button)

        if self.page == "threats":
            select = discord.ui.Select(
                placeholder="Toggle a threat lane…",
                min_values=1,
                max_values=1,
                options=[discord.SelectOption(label=LABELS[cat][:100], value=cat) for cat in antibetray_db.CATEGORIES],
                row=1,
            )
            select.callback = self.toggle_rule
            self.add_item(select)

        elif self.page == "policy":
            edit = discord.ui.Button(label="Edit Policy", emoji=E("q_admin"), style=discord.ButtonStyle.primary, row=1)
            edit.callback = self.configure
            self.add_item(edit)

        elif self.page == "trust":
            manage = discord.ui.Button(label="Edit Watch List", emoji=E("q_lock"), style=discord.ButtonStyle.primary, row=1)
            manage.callback = self.manage_trust
            self.add_item(manage)

        elif self.page == "overview":
            settings = self.cog.settings(self.guild_id)
            toggle = discord.ui.Button(
                label="Disable Monitor" if settings["enabled"] else "Enable Monitor",
                emoji=E("q_offline") if settings["enabled"] else E("q_online"),
                style=discord.ButtonStyle.danger if settings["enabled"] else discord.ButtonStyle.success,
                row=1,
            )
            policy = discord.ui.Button(label="Policy", emoji=E("q_admin"), style=discord.ButtonStyle.primary, row=1)
            deploy = discord.ui.Button(label="Deploy / Repair", emoji=E("q_lock"), style=discord.ButtonStyle.secondary, row=1)
            toggle.callback = self.toggle
            policy.callback = self.configure
            deploy.callback = self.deploy
            self.add_item(toggle)
            self.add_item(policy)
            self.add_item(deploy)

        refresh = discord.ui.Button(label="Refresh", emoji=E("q_sync"), style=discord.ButtonStyle.secondary, row=4)
        refresh.callback = self.refresh
        self.add_item(refresh)

    def _switch(self, target):
        async def callback(interaction: discord.Interaction):
            self.page = target
            self.build()
            await interaction.response.edit_message(embed=panel_embed(interaction.guild, self.cog, target), view=self)
        return callback

    async def refresh(self, interaction):
        self.cog.invalidate(self.guild_id)
        self.build()
        await interaction.response.edit_message(embed=panel_embed(interaction.guild, self.cog, self.page), view=self)

    async def configure(self, interaction):
        await interaction.response.send_modal(PolicyModal(self.cog, self.guild_id, self))

    async def manage_trust(self, interaction):
        await interaction.response.send_modal(TrustModal(self.cog, self.guild_id, self))

    async def toggle(self, interaction):
        enabled = bool(self.cog.settings(self.guild_id)["enabled"])
        antibetray_db.set_enabled(self.guild_id, not enabled)
        self.cog.invalidate(self.guild_id)
        self.page = "overview"
        self.build()
        await interaction.response.edit_message(embed=panel_embed(interaction.guild, self.cog, "overview"), view=self)

    async def toggle_rule(self, interaction):
        category = interaction.data["values"][0]
        current = bool(antibetray_db.get_rule(self.guild_id, category)["enabled"])
        antibetray_db.set_rule(self.guild_id, category, enabled=not current)
        self.cog.invalidate(self.guild_id)
        self.build()
        await interaction.response.edit_message(embed=panel_embed(interaction.guild, self.cog, "threats"), view=self)

    async def deploy(self, interaction):
        await self.cog.deploy(interaction)


class SetupView(AdminView):
    def __init__(self, cog: "Antibetray", author_id: int):
        super().__init__(author_id, timeout=300)
        self.cog = cog

    @discord.ui.button(label="Run Trust Preflight", emoji="🔐", style=discord.ButtonStyle.success)
    async def deploy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Deployment output is intentionally view-less. Disable the setup
        # controls immediately so no SetupView buttons survive into the
        # deployment result. The normal /antibetray config panel keeps its
        # own controls unchanged.
        for child in self.children:
            child.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except (discord.NotFound, discord.HTTPException):
            pass
        await self.cog.deploy(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=ui.info("ANTI-BETRAY / CANCELLED", "No configuration was changed."), view=None)


class Antibetray(commands.Cog):
    antibetray_group = app_commands.Group(name="antibetray", description="Gogeta privileged-identity monitor")

    def __init__(self, bot):
        self.bot = bot
        antibetray_db.setup_database()
        self._settings_cache: dict[int, tuple[float, dict]] = {}
        self._watch_cache: dict[int, tuple[float, tuple[set[int], set[int]]]] = {}
        self._events = defaultdict(lambda: defaultdict(lambda: defaultdict(deque)))
        self._containment_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._audit_seen: dict[int, float] = {}
        self._audit_semaphore = defaultdict(lambda: asyncio.Semaphore(2))
        self._recent_bans: dict[tuple[int, int], float] = {}

    def settings(self, guild_id: int) -> dict:
        now = time.monotonic()
        cached = self._settings_cache.get(guild_id)
        if cached and now - cached[0] < CACHE_TTL:
            return cached[1]
        settings = antibetray_db.get_settings(guild_id)
        self._settings_cache[guild_id] = (now, settings)
        return settings

    def _watch_lists(self, guild_id: int):
        now = time.monotonic()
        cached = self._watch_cache.get(guild_id)
        if cached and now - cached[0] < CACHE_TTL:
            return cached[1]
        value = (
            set(antibetray_db.list_trusted_users(guild_id)),
            set(antibetray_db.list_trusted_roles(guild_id)),
        )
        self._watch_cache[guild_id] = (now, value)
        return value

    def invalidate(self, guild_id: int):
        self._settings_cache.pop(guild_id, None)
        self._watch_cache.pop(guild_id, None)
        self._events.pop(guild_id, None)

    async def require(self, interaction: discord.Interaction) -> bool:
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if not interaction.guild or not member or not member.guild_permissions.administrator:
            await interaction.response.send_message(embed=ui.permission_denied(), ephemeral=True)
            return False
        return True

    async def require_ctx(self, ctx: commands.Context) -> bool:
        if not ctx.guild or not isinstance(ctx.author, discord.Member) or not ctx.author.guild_permissions.administrator:
            await ctx.send(embed=ui.permission_denied(), allowed_mentions=discord.AllowedMentions.none())
            return False
        return True

    def watched(self, guild: discord.Guild, actor) -> bool:
        if not actor or actor.id in {guild.owner_id, getattr(self.bot.user, "id", 0)}:
            return False
        if getattr(actor, "bot", False):
            return False
        users, roles = self._watch_lists(guild.id)
        if actor.id in users:
            return True
        if isinstance(actor, discord.Member):
            if any(role.id in roles for role in actor.roles):
                return True
            perms = actor.guild_permissions
            return bool(perms.administrator or perms.manage_guild or perms.manage_roles or perms.manage_channels or perms.manage_webhooks or perms.ban_members or perms.kick_members)
        return bool(antinuke_db.is_user_whitelisted(guild.id, actor.id))

    @staticmethod
    def _action_value(name: str):
        return getattr(discord.AuditLogAction, name, None)

    async def _audit_entry(self, guild: discord.Guild, actions, target_id=None, channel_id=None, retries=None):
        me = guild.me
        if not me or not me.guild_permissions.view_audit_log:
            return None
        action_list = [action for action in actions if action is not None]
        if not action_list:
            return None
        async with self._audit_semaphore[guild.id]:
            for delay in (retries if retries is not None else AUDIT_RETRY_DELAYS):
                if delay:
                    await asyncio.sleep(delay)
                best = None
                now = time.monotonic()
                for audit_id, seen_at in list(self._audit_seen.items()):
                    if now - seen_at > AUDIT_SEEN_TTL:
                        self._audit_seen.pop(audit_id, None)
                try:
                    for action in action_list:
                        async for entry in guild.audit_logs(limit=25, action=action):
                            age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                            if age > AUDIT_MAX_AGE:
                                break
                            if age < -2:
                                continue
                            # Skip entries already consumed by an earlier event. (Picking the newest
                            # entry first and then discarding it when seen made rapid-fire actions
                            # invisible to Anti-Betray.)
                            if entry.id in self._audit_seen:
                                continue
                            target = getattr(entry, "target", None)
                            if target_id is not None and getattr(target, "id", None) != target_id:
                                continue
                            if channel_id is not None:
                                target_channel = getattr(target, "channel_id", None)
                                target_obj = getattr(getattr(target, "channel", None), "id", None)
                                if target_channel != channel_id and target_obj != channel_id:
                                    continue
                            if best is None or entry.created_at > best.created_at:
                                best = entry
                except (discord.Forbidden, discord.HTTPException):
                    return None
                if best is not None:
                    self._audit_seen[best.id] = time.monotonic()
                    return best
        return None

    async def audit_actor(self, guild, actions, target_id=None, channel_id=None):
        entry = await self._audit_entry(guild, actions, target_id, channel_id)
        return entry.user if entry else None

    def _hit(self, guild_id: int, actor_id: int, category: str, category_window: int):
        now = time.monotonic()
        bucket = self._events[guild_id][actor_id]
        category_q = bucket[category]
        global_q = bucket["__global__"]
        category_q.append(now)
        global_q.append(now)
        global_window = self.settings(guild_id)["window_seconds"]
        while category_q and category_q[0] < now - category_window:
            category_q.popleft()
        while global_q and global_q[0] < now - global_window:
            global_q.popleft()
        return len(category_q), len(global_q)

    def _clear_actor(self, guild_id: int, actor_id: int):
        self._events.get(guild_id, {}).pop(actor_id, None)

    def _containment_lock(self, guild_id: int, actor_id: int):
        key = (guild_id, actor_id)
        lock = self._containment_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._containment_locks[key] = lock
        return lock

    async def _ensure_log_channel(self, guild: discord.Guild):
        configured = self.settings(guild.id).get("log_channel_id")
        if configured:
            channel = guild.get_channel(configured)
            if isinstance(channel, discord.TextChannel):
                return channel
        channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
        if isinstance(channel, discord.TextChannel):
            antibetray_db.set_log_channel(guild.id, channel.id)
            self.invalidate(guild.id)
            return channel
        if not guild.me or not guild.me.guild_permissions.manage_channels:
            return None
        try:
            channel = await guild.create_text_channel(LOG_CHANNEL_NAME, reason="Gogeta security log route")
        except (discord.Forbidden, discord.HTTPException):
            return None
        antibetray_db.set_log_channel(guild.id, channel.id)
        self.invalidate(guild.id)
        return channel

    async def deploy(self, interaction: discord.Interaction):
        if not await self.require(interaction):
            return
        if not interaction.response.is_done():
            await interaction.response.defer()
        guild = interaction.guild
        me = guild.me
        settings = self.settings(guild.id)
        checks = [
            check_line("View Audit Log", bool(me and me.guild_permissions.view_audit_log)),
            check_line("Manage Roles", bool(me and me.guild_permissions.manage_roles), "needed by strip-roles containment/recovery"),
        ]
        if settings["punishment"] == "kick":
            checks.append(check_line("Kick Members", bool(me and me.guild_permissions.kick_members)))
        elif settings["punishment"] == "ban":
            checks.append(check_line("Ban Members", bool(me and me.guild_permissions.ban_members)))
        mandatory = bool(me and me.guild_permissions.view_audit_log and me.guild_permissions.manage_roles)
        if settings["punishment"] == "kick":
            mandatory = mandatory and bool(me.guild_permissions.kick_members)
        elif settings["punishment"] == "ban":
            mandatory = mandatory and bool(me.guild_permissions.ban_members)
        if not mandatory:
            # Never attach the configuration/setup view to a deployment result.
            await interaction.edit_original_response(
                embed=security_embed("ANTI-BETRAY / PREFLIGHT FAILED", "\n".join(checks), Color.ERROR, icon=E("q_error")),
                view=None,
            )
            return
        channel = await self._ensure_log_channel(guild)
        checks.append(check_line("Security Log", bool(channel), channel.mention if channel else "optional; incidents remain in SQLite"))
        antibetray_db.set_enabled(guild.id, True)
        self.invalidate(guild.id)
        # Final deploy message is deliberately button-free. Buttons remain
        # available only when the user opens /antibetray config.
        await interaction.edit_original_response(
            embed=security_embed("ANTI-BETRAY / ONLINE", "**Deployment complete.**\n\n" + "\n".join(checks), Color.SUCCESS, icon=E("q_lock")),
            view=None,
        )

    async def _run_corrections(self, corrections) -> str:
        failures = []
        for operation in corrections or ():
            try:
                await operation()
            except discord.NotFound:
                pass
            except discord.Forbidden:
                failures.append("rollback denied by Discord")
            except discord.HTTPException:
                failures.append("rollback request failed")
        return "; ".join(failures)

    async def _apply_punishment(self, guild, actor, step: str, category: str) -> None:
        reason = f"Gogeta Anti-Betray: {LABELS[category]}"
        member = guild.get_member(actor.id)
        if step == "strip_roles":
            if not member:
                raise RuntimeError("Actor is no longer present.")
            if not guild.me or not guild.me.guild_permissions.manage_roles:
                raise RuntimeError("Bot lacks Manage Roles.")
            removable = [r for r in member.roles if r.is_assignable()]
            stuck = [r for r in member.roles if not r.is_default() and not r.is_assignable() and not r.managed]
            if removable:
                await member.remove_roles(*removable, reason=reason)
            if stuck:
                raise RuntimeError("Role hierarchy prevents removing: " + ", ".join(r.name for r in stuck[:5]))
        elif step == "kick":
            if not member:
                raise RuntimeError("Actor is no longer present.")
            await member.kick(reason=reason)
        elif step == "ban":
            await guild.ban(discord.Object(id=actor.id), reason=reason, delete_message_seconds=0)
        else:
            raise RuntimeError("Invalid containment configuration.")

    async def punish(self, guild, actor, category, detail=""):
        lock = self._containment_lock(guild.id, actor.id)
        async with lock:
            # Claim and clear the burst before touching Discord. A second
            # simultaneous signal can wait on this lock, see the cleared
            # bucket, and exit instead of issuing a duplicate punishment.
            bucket = self._events.get(guild.id, {}).get(actor.id)
            if not bucket:
                return
            self._clear_actor(guild.id, actor.id)
            settings = self.settings(guild.id)
            punishment = settings["punishment"]
            chain = {"ban": ("ban", "kick", "strip_roles"), "kick": ("kick", "strip_roles"), "strip_roles": ("strip_roles",)}.get(punishment, ("strip_roles",))
            success = False
            used = punishment
            notes = []
            for step in chain:
                try:
                    await self._apply_punishment(guild, actor, step, category)
                    success = True
                    used = step
                    if step != punishment:
                        notes.append(f"fallback: `{punishment}` failed, applied `{step}`")
                    break
                except discord.NotFound:
                    success = True
                    used = step
                    break
                except discord.Forbidden:
                    notes.append(f"{step}: Discord denied it (check permissions and role hierarchy)")
                except discord.HTTPException as exc:
                    notes.append(f"{step}: Discord API error: {exc}")
                except RuntimeError as exc:
                    notes.append(f"{step}: {exc}")
                except Exception as exc:
                    notes.append(f"{step}: {type(exc).__name__}: {exc}")
            text = _safe(" ".join(notes) or detail)
            if notes and detail:
                text = _safe(f"{detail} {' '.join(notes)}")
            antibetray_db.add_incident(guild.id, actor.id, category, used, success=success, detail=text)
            antibetray_db.cleanup_incidents(guild.id)
            await self.log(guild, actor, category, used, success, text)

    async def log(self, guild, actor, category, punishment, success, detail=""):
        channel = guild.get_channel(self.settings(guild.id).get("log_channel_id"))
        if not isinstance(channel, discord.TextChannel):
            if not success:
                print(f"[AntiBetray] guild={guild.id} actor={getattr(actor, 'id', 0)} category={category} FAILED: {detail}")
            return
        embed = security_embed(
            f"ANTI-BETRAY / {'CONTAINED' if success else 'ALERT'}",
            f"**Actor:** <@{getattr(actor, 'id', 0)}>\n**Vector:** `{LABELS.get(category, category)}`\n**Response:** `{punishment}`\n**Result:** `{'SUCCESS' if success else 'FAILED'}`\n\n{_safe(detail) or 'No additional detail.'}",
            Color.MODERATION if success else Color.ERROR,
            icon=E("q_emergency"),
        )
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            if not success:
                print(f"[AntiBetray] guild={guild.id}: unable to write security log")

    async def process(self, guild, actions, category, *, target_id=None, channel_id=None, actor=None, detail="", corrections=None, alert_only=False):
        settings = self.settings(guild.id)
        if not settings["enabled"] or not antibetray_db.is_category_enabled(guild.id, category):
            return
        if actor is None:
            entry = await self._audit_entry(guild, actions, target_id, channel_id)
            actor = entry.user if entry else None
        if not actor or not self.watched(guild, actor):
            return

        correction_note = await self._run_corrections(corrections)
        if correction_note:
            detail = f"{detail} Correction: {correction_note}".strip()

        rule = antibetray_db.get_rule(guild.id, category)
        category_count, global_count = self._hit(guild.id, actor.id, category, rule["window_seconds"])
        if alert_only:
            antibetray_db.add_incident(guild.id, actor.id, category, "alert", success=False, detail=_safe(detail))
            antibetray_db.cleanup_incidents(guild.id)
            await self.log(guild, actor, category, "alert", False, detail)
            return
        if category_count < rule["threshold"] and global_count < settings["threshold"]:
            return
        await self.punish(guild, actor, category, detail)

    async def handle_bot_add(self, member: discord.Member):
        guild = member.guild
        settings = self.settings(guild.id)
        if not settings["enabled"] or not antibetray_db.is_category_enabled(guild.id, "trusted_bot_add"):
            return
        # Anti-Nuke owns the actual bot allow-list (shared an_trust table).
        if antinuke_db.is_bot_whitelisted(guild.id, member.id):
            return
        # Look up who added it, but do NOT wait on that before the bot is removed.
        entry = await self._audit_entry(guild, [self._action_value("bot_add")], target_id=member.id, retries=(0.0, 0.5))
        actor = entry.user if entry else None
        if not actor or not self.watched(guild, actor):
            return

        async def remove_bot():
            try:
                await member.kick(reason="Gogeta Anti-Betray: unapproved bot addition by watched identity")
            except discord.NotFound:
                pass

        await self.process(
            guild,
            (),
            "trusted_bot_add",
            target_id=member.id,
            actor=actor,
            detail="A watched identity added a bot that is not on the Anti-Nuke bot whitelist.",
            corrections=[remove_bot],
        )

    async def runtime_health(self) -> tuple[bool, list[str]]:
        """Validate live Anti-Betray prerequisites for every guild.

        Configuration/deployment can be persisted even when the bot's role or
        Audit Log capability changes later. This health check prevents a
        misleading ONLINE state and leaves an actionable console trail.
        """
        issues: list[str] = []
        for guild in self.bot.guilds:
            settings = self.settings(guild.id)
            if not settings["enabled"]:
                continue
            me = guild.me
            if not me:
                issues.append(f"guild={guild.id}: bot member unavailable")
                continue
            if not me.guild_permissions.view_audit_log:
                issues.append(f"guild={guild.id}: missing View Audit Log")
            if not me.guild_permissions.manage_roles:
                issues.append(f"guild={guild.id}: missing Manage Roles")
            punishment = str(settings.get("punishment", "strip_roles"))
            if punishment == "kick" and not me.guild_permissions.kick_members:
                issues.append(f"guild={guild.id}: missing Kick Members")
            if punishment == "ban" and not me.guild_permissions.ban_members:
                issues.append(f"guild={guild.id}: missing Ban Members")
        return (not issues, issues)

    @commands.Cog.listener()
    async def on_ready(self):
        ok, issues = await self.runtime_health()
        if ok:
            print(f"[AntiBetray] Runtime healthy in {sum(1 for g in self.bot.guilds if self.settings(g.id)['enabled'])} enabled guild(s).")
        else:
            print("[AntiBetray] Runtime health warning: " + " | ".join(issues[:20]))

    # ---------- listeners ----------
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        self._recent_bans[(guild.id, user.id)] = time.monotonic()
        try:
            await self.process(guild, [self._action_value("ban")], "trusted_mass_ban", target_id=user.id)
        except Exception as exc:
            print(f"[AntiBetray] on_member_ban failed in guild={guild.id}: {type(exc).__name__}: {exc}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        key = (member.guild.id, member.id)
        seen = self._recent_bans.get(key)
        if seen and time.monotonic() - seen < 5:
            return
        try:
            await self.process(member.guild, [self._action_value("kick")], "trusted_mass_kick", target_id=member.id)
        except Exception as exc:
            print(f"[AntiBetray] on_member_remove failed in guild={member.guild.id}: {type(exc).__name__}: {exc}")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            await self.handle_bot_add(member)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self.process(channel.guild, [self._action_value("channel_delete")], "trusted_channel_delete", target_id=channel.id)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self.process(role.guild, [self._action_value("role_delete")], "trusted_role_delete", target_id=role.id)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        dangerous = any(getattr(role.permissions, perm, False) for perm in DANGEROUS_PERMS)
        await self.process(
            role.guild,
            [self._action_value("role_create")],
            "trusted_dangerous_role" if dangerous else "trusted_role_create",
            target_id=role.id,
            detail="A watched identity created a role with dangerous permissions." if dangerous else "A watched identity created a role.",
        )

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        added = [perm for perm in DANGEROUS_PERMS if getattr(after.permissions, perm, False) and not getattr(before.permissions, perm, False)]
        if not added:
            return

        async def restore():
            await after.edit(permissions=before.permissions, reason="Gogeta Anti-Betray: rollback dangerous role permission grant")

        await self.process(
            after.guild,
            [self._action_value("role_update")],
            "trusted_dangerous_role",
            target_id=after.id,
            detail="Dangerous permissions added: " + ", ".join(added),
            corrections=[restore],
        )

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        added_roles = [role for role in after.roles if role not in before.roles]
        dangerous = [role for role in added_roles if any(getattr(role.permissions, perm, False) for perm in DANGEROUS_PERMS)]
        if not dangerous:
            return
        actor = await self.audit_actor(after.guild, [self._action_value("member_role_update")], target_id=after.id)
        if not actor or not self.watched(after.guild, actor):
            return

        async def rollback():
            await after.remove_roles(*dangerous, reason="Gogeta Anti-Betray: rollback privileged role grant")

        await self.process(
            after.guild,
            (),
            "trusted_member_role_grant",
            target_id=after.id,
            actor=actor,
            detail="A watched identity granted a privileged role.",
            corrections=[rollback],
        )

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel):
        actions = [self._action_value(name) for name in ("webhook_create", "webhook_update", "webhook_delete")]
        entry = await self._audit_entry(channel.guild, actions, channel_id=channel.id)
        if not entry:
            return
        if not self.watched(channel.guild, entry.user):
            return
        await self.process(channel.guild, (), "trusted_webhook", channel_id=channel.id, actor=entry.user, detail="A webhook change was made by a watched identity.")

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        changed = []
        if getattr(before, "owner_id", None) != getattr(after, "owner_id", None): changed.append("ownership")
        if getattr(before, "vanity_url_code", None) != getattr(after, "vanity_url_code", None): changed.append("vanity URL")
        if getattr(before, "name", None) != getattr(after, "name", None): changed.append("server name")
        if changed:
            await self.process(after, [self._action_value("guild_update")], "trusted_guild_change", detail="Server configuration changed: " + ", ".join(changed), alert_only=True)

    @commands.Cog.listener()
    async def on_integration_create(self, integration):
        await self.process(integration.guild, [self._action_value("integration_create")], "trusted_integration", target_id=getattr(integration, "id", None))

    @commands.Cog.listener()
    async def on_integration_update(self, integration):
        await self.process(integration.guild, [self._action_value("integration_update")], "trusted_integration", target_id=getattr(integration, "id", None))

    @commands.Cog.listener()
    async def on_integration_delete(self, integration):
        await self.process(integration.guild, [self._action_value("integration_delete")], "trusted_integration", target_id=getattr(integration, "id", None))

    # ---------- command surface ----------
    @antibetray_group.command(name="setup", description="Run Anti-Betray preflight and deploy the trust guard.")
    async def setup_cmd(self, interaction):
        if not await self.require(interaction):
            return
        antibetray_db.get_settings(interaction.guild.id)
        await interaction.response.send_message(embed=panel_embed(interaction.guild, self, "overview"), view=SetupView(self, interaction.user.id), ephemeral=True)

    @antibetray_group.command(name="config", description="Open the Anti-Betray control center.")
    async def config(self, interaction):
        if not await self.require(interaction):
            return
        await interaction.response.send_message(embed=panel_embed(interaction.guild, self, "overview"), view=AntibetrayView(self, interaction.user.id, interaction.guild.id), ephemeral=True)

    @antibetray_group.command(name="whitelist", description="Add or remove an explicitly watched user or role.")
    @app_commands.describe(kind="Target type", action="Add or remove", user="User target", role="Role target")
    @app_commands.choices(
        kind=[app_commands.Choice(name="User", value="user"), app_commands.Choice(name="Role", value="role")],
        action=[app_commands.Choice(name="Add", value="add"), app_commands.Choice(name="Remove", value="remove")],
    )
    async def whitelist(
        self,
        interaction: discord.Interaction,
        kind: app_commands.Choice[str],
        action: app_commands.Choice[str],
        user: discord.Member | None = None,
        role: discord.Role | None = None,
    ):
        if not await self.require(interaction):
            return
        target = user if kind.value == "user" else role
        if target is None:
            await interaction.response.send_message(embed=ui.error("ANTI-BETRAY / INVALID TARGET", f"Select a {kind.value} target."), ephemeral=True)
            return
        add = action.value == "add"
        if kind.value == "user":
            (antibetray_db.add_trusted_user if add else antibetray_db.remove_trusted_user)(interaction.guild.id, target.id)
        else:
            (antibetray_db.add_trusted_role if add else antibetray_db.remove_trusted_role)(interaction.guild.id, target.id)
        self.invalidate(interaction.guild.id)
        await interaction.response.send_message(embed=ui.success("ANTI-BETRAY / WATCH LIST UPDATED", f"{target.mention} is now {'watched' if add else 'removed from the explicit watch list'}."), ephemeral=True)

    @commands.hybrid_command(name="antibetray-incidents", description="View recent Anti-Betray incidents.")
    async def incidents(self, ctx):
        if not await self.require_ctx(ctx):
            return
        rows = antibetray_db.get_incidents(ctx.guild.id, 15)
        body = "\n\n".join(f"<t:{row['timestamp']}:R> • <@{row['user_id'] or 0}> • **{LABELS.get(row['category'], row['category'])}** → `{row['punishment']}`" for row in rows)
        await ctx.send(embed=security_embed("ANTI-BETRAY / INCIDENT LEDGER", body or "No Anti-Betray incidents recorded.", Color.WARNING if rows else Color.NEUTRAL, icon=E("q_logs")), allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(Antibetray(bot))
