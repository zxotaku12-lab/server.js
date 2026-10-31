# Credits: gogeta_gg
import re
import asyncio
from datetime import timedelta

import discord
from discord.ext import commands
from discord import app_commands

from . import moderation_db, prefix_db
from ui import embeds
from ui.views import ConfirmView
from ui.pagination import Paginator, chunk


def parse_duration(duration: str) -> int:
    """
    Converts:
        30s
        10m
        2h
        7d
    into seconds. Raises ValueError on anything else.
    """
    duration = duration.lower().strip()
    match = re.fullmatch(r"(\d+)([smhd])", duration)

    if not match:
        raise ValueError("Invalid duration")

    value = int(match.group(1))
    unit = match.group(2)

    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return value * multipliers[unit]


def action_embed(title: str, target: discord.abc.User, moderator: discord.abc.User, reason: str, extra: list = None) -> discord.Embed:
    """The shared shape for every moderation result: Member / Moderator /
    Reason, plus optional extra fields (delete-days, duration, etc)."""
    embed = embeds.moderation(title)
    embed.add_field(name="Member", value=target.mention, inline=True)
    embed.add_field(name="Moderator", value=moderator.mention, inline=True)
    embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
    for name, value in (extra or []):
        embed.add_field(name=name, value=value, inline=True)
    embed.set_thumbnail(url=target.display_avatar.url)
    return embed


def hierarchy_blocked_embed(action: str, actor: discord.Member, target: discord.Member) -> discord.Embed:
    """Structured 'ACTION BLOCKED' embed instead of a one-line X mark —
    explains exactly why the role hierarchy stopped the action."""
    embed = embeds.warning(
        "Action Blocked",
        f"You can't **{action}** this member — role hierarchy prevents it.",
    )
    embed.add_field(name="Target", value=target.mention, inline=True)
    embed.add_field(name="Your Highest Role", value=actor.top_role.mention, inline=True)
    embed.add_field(name="Target's Highest Role", value=target.top_role.mention, inline=True)
    return embed


def bot_hierarchy_blocked_embed(guild: discord.Guild, target: discord.Member = None, role: discord.Role = None) -> discord.Embed:
    embed = embeds.warning(
        "Action Blocked",
        "I can't do that — my own role isn't high enough in this server's hierarchy.",
    )
    embed.add_field(name="My Highest Role", value=guild.me.top_role.mention, inline=True)
    if target is not None:
        embed.add_field(name="Target's Highest Role", value=target.top_role.mention, inline=True)
    if role is not None:
        embed.add_field(name="Role In Question", value=role.mention, inline=True)
    return embed


class Moderation(commands.Cog):
    """Moderation & server management commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        moderation_db.setup_database()

    # ── Shared error handling for every command in this cog ────────────────

    async def cog_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ):
        # Hybrid commands wrap the real error in HybridCommandError when
        # invoked as a slash command — unwrap it so both invocation styles
        # (`$kick` and `/kick`) get the same friendly message.
        original = getattr(error, "original", error)

        if isinstance(original, (commands.MissingPermissions, app_commands.MissingPermissions)):
            embed = embeds.permission_denied(
                f"You need **{', '.join(original.missing_permissions)}** permission to use this command."
            )
        elif isinstance(original, (commands.BotMissingPermissions, app_commands.BotMissingPermissions)):
            embed = embeds.error("Missing Permissions", f"I need **{', '.join(original.missing_permissions)}** permission to do that.")
        elif isinstance(original, commands.NoPrivateMessage):
            embed = embeds.error("Not Available Here", "This command can't be used in DMs.")
        elif isinstance(original, commands.BadArgument):
            embed = embeds.error("Invalid Input", str(original))
        else:
            embed = embeds.error("Something Went Wrong", f"`{original}`")

        await ctx.send(embed=embed, ephemeral=True)

    async def _confirm_destructive(self, ctx: commands.Context, action: str, target: discord.Member) -> bool:
        """Shows a Confirm/Cancel prompt for a destructive action. Returns
        True if confirmed, False if cancelled/timed out (and handles
        sending the follow-up message either way)."""
        view = ConfirmView(ctx.author.id, confirm_label=action.title(), danger=True, timeout=30)
        prompt = embeds.warning(
            f"Confirm {action.title()}",
            f"Are you sure you want to **{action}** {target.mention}? This action cannot be undone easily.",
        )
        message = await ctx.send(embed=prompt, view=view, ephemeral=True)
        view.message = message
        await view.wait()

        if not view.result:
            cancelled = embeds.info("Cancelled", f"{action.title()} was cancelled — no action was taken.")
            try:
                await message.edit(embed=cancelled, view=None)
            except discord.HTTPException:
                pass
            return False
        return True

    # ── Kick ─────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="kick", description="Kick a member from the server.")
    @app_commands.describe(member="The member to kick.", reason="Why they're being kicked.")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx: commands.Context, member: discord.Member, reason: str = "No reason provided"):
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            await ctx.send(embed=hierarchy_blocked_embed("kick", ctx.author, member), ephemeral=True)
            return

        if not await self._confirm_destructive(ctx, "kick", member):
            return

        try:
            await member.send(embed=embeds.warning("You Were Kicked", f"**Server:** {ctx.guild.name}\n**Reason:** {reason}"))
        except discord.HTTPException:
            pass

        await member.kick(reason=f"{ctx.author}: {reason}")
        moderation_db.add_modlog(ctx.guild.id, member.id, ctx.author.id, "kick", reason)

        await ctx.send(embed=action_embed("Member Kicked", member, ctx.author, reason))

    # ── Ban / Unban ──────────────────────────────────────────────────────

    @commands.hybrid_command(name="ban", description="Ban a member from the server.")
    @app_commands.describe(member="The member to ban.", reason="Why they're being banned.", delete_days="Days of their messages to delete (0-7).")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx: commands.Context, member: discord.Member, reason: str = "No reason provided", delete_days: commands.Range[int, 0, 7] = 0):
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            await ctx.send(embed=hierarchy_blocked_embed("ban", ctx.author, member), ephemeral=True)
            return

        if not await self._confirm_destructive(ctx, "ban", member):
            return

        try:
            await member.send(embed=embeds.error("You Were Banned", f"**Server:** {ctx.guild.name}\n**Reason:** {reason}"))
        except discord.HTTPException:
            pass

        await member.ban(reason=f"{ctx.author}: {reason}", delete_message_seconds=delete_days * 86400)
        moderation_db.add_modlog(ctx.guild.id, member.id, ctx.author.id, "ban", reason)

        await ctx.send(embed=action_embed(
            "Member Banned", member, ctx.author, reason,
            extra=[("Action", "Permanent Ban"), ("Messages Deleted", f"{delete_days} day(s)" if delete_days else "None")],
        ))

    @commands.hybrid_command(name="unban", description="Unban a user by their ID.")
    @app_commands.describe(user_id="The ID of the user to unban.", reason="Why they're being unbanned.")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx: commands.Context, user_id: str, reason: str = "No reason provided"):
        try:
            user_id_int = int(user_id)
        except ValueError:
            await ctx.send(embed=embeds.error("Invalid User ID", "That doesn't look like a valid user ID."), ephemeral=True)
            return

        try:
            user = await self.bot.fetch_user(user_id_int)
            await ctx.guild.unban(user, reason=f"{ctx.author}: {reason}")
        except discord.NotFound:
            await ctx.send(embed=embeds.error("Not Banned", "That user isn't banned (or doesn't exist)."), ephemeral=True)
            return

        moderation_db.add_modlog(ctx.guild.id, user_id_int, ctx.author.id, "unban", reason)
        await ctx.send(embed=action_embed("Member Unbanned", user, ctx.author, reason))

    @commands.hybrid_command(name="softban", description="Ban then immediately unban a member, purging their recent messages.")
    @app_commands.describe(member="The member to softban.", reason="Why they're being softbanned.")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def softban(self, ctx: commands.Context, member: discord.Member, reason: str = "No reason provided"):
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            await ctx.send(embed=hierarchy_blocked_embed("softban", ctx.author, member), ephemeral=True)
            return

        if not await self._confirm_destructive(ctx, "softban", member):
            return

        await member.ban(reason=f"Softban by {ctx.author}: {reason}", delete_message_seconds=86400)
        await ctx.guild.unban(member, reason="Softban cleanup")
        moderation_db.add_modlog(ctx.guild.id, member.id, ctx.author.id, "softban", reason)

        await ctx.send(embed=action_embed(
            "Member Softbanned", member, ctx.author, reason,
            extra=[("Action", "Softban (messages purged, can rejoin)")],
        ))

    # ── Timeout / Untimeout ──────────────────────────────────────────────

    @commands.hybrid_command(name="timeout", description="Timeout (mute) a member for a duration.")
    @app_commands.describe(member="The member to timeout.", duration="e.g. 30s, 10m, 2h, 7d", reason="Why they're being timed out.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def timeout(self, ctx: commands.Context, member: discord.Member, duration: str, reason: str = "No reason provided"):
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            await ctx.send(embed=hierarchy_blocked_embed("timeout", ctx.author, member), ephemeral=True)
            return

        try:
            seconds = parse_duration(duration)
        except ValueError:
            await ctx.send(embed=embeds.error("Invalid Duration", "Use something like `30s`, `10m`, `2h`, or `7d`."), ephemeral=True)
            return

        if seconds > 28 * 86400:
            await ctx.send(embed=embeds.error("Duration Too Long", "Timeouts can't be longer than 28 days."), ephemeral=True)
            return

        await member.timeout(discord.utils.utcnow() + timedelta(seconds=seconds), reason=f"{ctx.author}: {reason}")
        moderation_db.add_modlog(ctx.guild.id, member.id, ctx.author.id, f"timeout ({duration})", reason)

        await ctx.send(embed=action_embed(
            "Member Timed Out", member, ctx.author, reason,
            extra=[("Duration", duration)],
        ))

    @commands.hybrid_command(name="untimeout", description="Remove a member's timeout.")
    @app_commands.describe(member="The member to remove timeout from.", reason="Why the timeout is being removed.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def untimeout(self, ctx: commands.Context, member: discord.Member, reason: str = "No reason provided"):
        await member.timeout(None, reason=f"{ctx.author}: {reason}")
        moderation_db.add_modlog(ctx.guild.id, member.id, ctx.author.id, "untimeout", reason)

        await ctx.send(embed=embeds.success("Timeout Removed", f"{member.mention}'s timeout was removed."))

    # ── Warnings ─────────────────────────────────────────────────────────

    @commands.hybrid_command(name="warn", description="Warn a member.")
    @app_commands.describe(member="The member to warn.", reason="Why they're being warned.")
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx: commands.Context, member: discord.Member, reason: str = "No reason provided"):
        warning_id = moderation_db.add_warning(ctx.guild.id, member.id, ctx.author.id, reason)
        moderation_db.add_modlog(ctx.guild.id, member.id, ctx.author.id, "warn", reason)

        try:
            await member.send(embed=embeds.warning("You Were Warned", f"**Server:** {ctx.guild.name}\n**Reason:** {reason}"))
        except discord.HTTPException:
            pass

        await ctx.send(embed=action_embed(
            "Member Warned", member, ctx.author, reason,
            extra=[("Warning ID", f"#{warning_id}")],
        ))

    @commands.hybrid_command(name="warnings", description="View a member's warnings.")
    @app_commands.describe(member="The member to check.")
    @commands.has_permissions(moderate_members=True)
    async def warnings(self, ctx: commands.Context, member: discord.Member):
        rows = moderation_db.get_warnings(ctx.guild.id, member.id)

        if not rows:
            await ctx.send(embed=embeds.empty_state("No Warnings", f"{member.mention} has no warnings."))
            return

        entries = [f"**#{row['id']}** — {row['reason']} (<t:{row['timestamp']}:R>, by <@{row['moderator_id']}>)" for row in rows]
        pages_of_entries = chunk(entries, 10)

        pages = []
        for page_entries in pages_of_entries:
            embed = embeds.warning(f"Warnings — {member}", "\n".join(page_entries))
            embed.set_thumbnail(url=member.display_avatar.url)
            pages.append(embed)

        if len(pages) == 1:
            pages[0].set_footer(text=f"Gogeta Sentinel • Total: {len(rows)} warning(s)")
            await ctx.send(embed=pages[0])
        else:
            paginator = Paginator(pages, ctx.author.id)
            message = await ctx.send(embed=paginator.current, view=paginator)
            paginator.message = message

    @commands.hybrid_command(name="clearwarnings", description="Clear all warnings for a member.")
    @app_commands.describe(member="The member whose warnings should be cleared.")
    @commands.has_permissions(manage_guild=True)
    async def clearwarnings(self, ctx: commands.Context, member: discord.Member):
        removed = moderation_db.clear_warnings(ctx.guild.id, member.id)
        await ctx.send(embed=embeds.success("Warnings Cleared", f"Removed **{removed}** warning(s) for {member.mention}."))

    @commands.hybrid_command(name="delwarn", description="Remove a single warning by its ID.")
    @app_commands.describe(warning_id="The warning ID (shown in /warnings).")
    @commands.has_permissions(moderate_members=True)
    async def delwarn(self, ctx: commands.Context, warning_id: int):
        removed = moderation_db.remove_warning(warning_id, ctx.guild.id)
        if removed:
            await ctx.send(embed=embeds.success("Warning Removed", f"Warning #{warning_id} was deleted."))
        else:
            await ctx.send(embed=embeds.error("Not Found", "No warning with that ID was found in this server."), ephemeral=True)

    # ── Modlogs ──────────────────────────────────────────────────────────

    @commands.hybrid_command(name="modlogs", description="View a member's recent moderation history.")
    @app_commands.describe(member="The member to check.")
    @commands.has_permissions(moderate_members=True)
    async def modlogs(self, ctx: commands.Context, member: discord.Member):
        rows = moderation_db.get_modlogs(ctx.guild.id, member.id, limit=100)

        if not rows:
            await ctx.send(embed=embeds.empty_state("No Mod Logs", f"{member.mention} has no recorded moderation actions."))
            return

        entries = [f"**{row['action']}** — {row['reason'] or 'No reason'} (<t:{row['timestamp']}:R>, by <@{row['moderator_id']}>)" for row in rows]
        pages_of_entries = chunk(entries, 10)

        pages = []
        for page_entries in pages_of_entries:
            embed = embeds.moderation(f"Mod Logs — {member}", "\n".join(page_entries))
            embed.set_thumbnail(url=member.display_avatar.url)
            pages.append(embed)

        if len(pages) == 1:
            await ctx.send(embed=pages[0])
        else:
            paginator = Paginator(pages, ctx.author.id)
            message = await ctx.send(embed=paginator.current, view=paginator)
            paginator.message = message

    # ── Channel management ───────────────────────────────────────────────

    @commands.hybrid_command(name="purge", description="Bulk delete messages in this channel.")
    @app_commands.describe(amount="How many messages to delete (1-100).", member="Only delete messages from this member.")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purge(self, ctx: commands.Context, amount: commands.Range[int, 1, 100], member: discord.Member = None):
        await ctx.defer(ephemeral=True)

        def check(msg):
            return member is None or msg.author.id == member.id

        deleted = await ctx.channel.purge(limit=amount, check=check)
        moderation_db.add_modlog(ctx.guild.id, member.id if member else ctx.author.id, ctx.author.id, "purge", f"{len(deleted)} message(s)")

        await ctx.send(embed=embeds.success("Messages Purged", f"Deleted **{len(deleted)}** message(s)."), ephemeral=True)

    def _roles_at_or_below(self, guild: discord.Guild, cutoff_role: discord.Role) -> list[discord.Role]:
        """Every role in the guild whose position is <= the cutoff role's
        position, excluding @everyone (handled separately since it can't
        carry Administrator and is always included anyway)."""
        return [r for r in guild.roles if r.id != guild.default_role.id and r.position <= cutoff_role.position]

    @commands.hybrid_group(name="lockconfig", description="Configure the hierarchy cutoff used by /lock.", fallback="status")
    @commands.has_permissions(administrator=True)
    async def lockconfig(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            cutoff_id = moderation_db.get_lock_cutoff(ctx.guild.id)
            role = ctx.guild.get_role(cutoff_id) if cutoff_id else None
            desc = (
                f"**Current cutoff:** {role.mention if role else '`Not set`'}\n\n"
                "`/lock` denies **Send Messages** to every role at or below this "
                "role's position — including roles with Administrator, since the "
                "deny is written directly onto each role rather than relying on "
                "channel defaults.\n\nRoles above the cutoff, and the server owner, are never touched."
            )
            await ctx.send(embed=embeds.moderation("Lock Configuration", desc))

    @lockconfig.command(name="set-role", description="Set the role that /lock uses as its cutoff.")
    @app_commands.describe(role="Locking will affect this role and every role below it.")
    @commands.has_permissions(administrator=True)
    async def lockconfig_set_role(self, ctx: commands.Context, role: discord.Role):
        if role.id == ctx.guild.default_role.id:
            await ctx.send(embed=embeds.error("Invalid Cutoff", "Use a real role, not `@everyone` — `@everyone` is always included automatically."), ephemeral=True)
            return
        if role >= ctx.guild.me.top_role:
            await ctx.send(embed=embeds.error("Invalid Cutoff", f"{role.mention} is at or above my own top role, so I won't be able to override it on every affected role. Move my role above it first."), ephemeral=True)
            return
        moderation_db.set_lock_cutoff(ctx.guild.id, role.id)
        affected = self._roles_at_or_below(ctx.guild, role)
        await ctx.send(embed=embeds.success(
            "Lock Cutoff Updated",
            f"`/lock` will now restrict **{role.mention}** and everything below it "
            f"({len(affected)} role(s), plus @everyone) — this includes any of "
            f"those roles that carry Administrator.",
        ))

    @commands.hybrid_command(name="lock", description="Lock a channel for everyone at or below your configured cutoff role — including Administrators.")
    @app_commands.describe(channel="The channel to lock (defaults to the current channel).", reason="Why the channel is being locked.")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True, manage_roles=True)
    async def lock(self, ctx: commands.Context, channel: discord.TextChannel = None, reason: str = "No reason provided"):
        # Defer immediately — this command does a set_permissions() call per
        # affected role (plus @everyone and the owner exemption), which can
        # easily blow past Discord's 3-second interaction ack window on a
        # server with several roles below the cutoff. Without this, the
        # first ctx.send() below fails with "404 Unknown interaction"
        # because the interaction token had already expired.
        await ctx.defer()

        channel = channel or ctx.channel
        cutoff_id = moderation_db.get_lock_cutoff(ctx.guild.id)
        cutoff_role = ctx.guild.get_role(cutoff_id) if cutoff_id else None
        if cutoff_role is None:
            await ctx.send(embed=embeds.error("No Cutoff Configured", "Run `/lockconfig set-role` first and pick the role you want the lock to reach down to."), ephemeral=True)
            return
        if cutoff_role >= ctx.guild.me.top_role:
            await ctx.send(embed=embeds.error("Lock Blocked", f"My top role is no longer above {cutoff_role.mention}, so I can't safely override every affected role. Move my role higher and try again."), ephemeral=True)
            return

        targets = self._roles_at_or_below(ctx.guild, cutoff_role)
        prior_pairs = []

        everyone_overwrite = channel.overwrites_for(ctx.guild.default_role)
        prior_pairs.append((ctx.guild.default_role.id, everyone_overwrite.send_messages))
        everyone_overwrite.send_messages = False
        await channel.set_permissions(ctx.guild.default_role, overwrite=everyone_overwrite, reason=f"{ctx.author}: {reason}")

        for role in targets:
            overwrite = channel.overwrites_for(role)
            prior_pairs.append((role.id, overwrite.send_messages))
            overwrite.send_messages = False
            await channel.set_permissions(role, overwrite=overwrite, reason=f"{ctx.author}: {reason}")

        # The owner's account itself is exempted with a per-member overwrite,
        # since @everyone/role denies always apply to them too if their
        # highest role sits at or below the cutoff.
        owner = ctx.guild.owner
        if owner is not None:
            owner_overwrite = channel.overwrites_for(owner)
            prior_pairs.append((f"member:{owner.id}", owner_overwrite.send_messages))
            owner_overwrite.send_messages = True
            await channel.set_permissions(owner, overwrite=owner_overwrite, reason=f"{ctx.author}: {reason} (owner exemption)")

        moderation_db.save_lock_state(ctx.guild.id, channel.id, prior_pairs)
        moderation_db.add_modlog(ctx.guild.id, ctx.author.id, ctx.author.id, "lock", f"{channel.name}: {reason}")

        await ctx.send(embed=embeds.warning(
            "Channel Locked",
            f"{channel.mention} has been locked down to **{cutoff_role.mention}** and below "
            f"({len(targets) + 1} role(s) affected, Administrator included).\n**Reason:** {reason}",
        ))

    @commands.hybrid_command(name="unlock", description="Unlock this (or a given) channel, restoring exactly what /lock changed.")
    @app_commands.describe(channel="The channel to unlock (defaults to the current channel).")
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True, manage_roles=True)
    async def unlock(self, ctx: commands.Context, channel: discord.TextChannel = None):
        # Same reasoning as /lock — this loops set_permissions() over every
        # role that was affected by the original lock, which can exceed the
        # 3-second interaction ack window before the first send.
        await ctx.defer()

        channel = channel or ctx.channel
        prior_pairs = moderation_db.get_lock_state(ctx.guild.id, channel.id)

        if not prior_pairs:
            # Fall back to the old plain-@everyone behavior if this channel
            # wasn't locked via /lock (e.g. locked manually, or on an older version).
            await channel.set_permissions(ctx.guild.default_role, send_messages=None, reason=f"Unlocked by {ctx.author}")
            await ctx.send(embed=embeds.success("Channel Unlocked", f"{channel.mention} has been unlocked."))
            return

        for entry_key, prior_value in prior_pairs:
            if isinstance(entry_key, str) and entry_key.startswith("member:"):
                member = ctx.guild.get_member(int(entry_key.split(":", 1)[1]))
                if member is None:
                    continue
                overwrite = channel.overwrites_for(member)
                overwrite.send_messages = prior_value
                if overwrite.is_empty():
                    await channel.set_permissions(member, overwrite=None, reason=f"Unlocked by {ctx.author}")
                else:
                    await channel.set_permissions(member, overwrite=overwrite, reason=f"Unlocked by {ctx.author}")
                continue
            role = ctx.guild.get_role(entry_key)
            if role is None:
                continue
            overwrite = channel.overwrites_for(role)
            overwrite.send_messages = prior_value
            if overwrite.is_empty():
                await channel.set_permissions(role, overwrite=None, reason=f"Unlocked by {ctx.author}")
            else:
                await channel.set_permissions(role, overwrite=overwrite, reason=f"Unlocked by {ctx.author}")

        moderation_db.clear_lock_state(ctx.guild.id, channel.id)
        moderation_db.add_modlog(ctx.guild.id, ctx.author.id, ctx.author.id, "unlock", channel.name)
        await ctx.send(embed=embeds.success("Channel Unlocked", f"{channel.mention} has been unlocked and all affected roles restored to their prior state."))

    # ── Prefix ──────────────────────────────────────────────────────────

    @commands.hybrid_command(name="prefix", description="View or change this server's command prefix.")
    @app_commands.describe(new_prefix="The new prefix to use (leave blank to just view the current one).")
    @commands.has_permissions(administrator=True)
    async def prefix(self, ctx: commands.Context, new_prefix: str = None):
        if new_prefix is None:
            current = prefix_db.get_prefix(ctx.guild.id)
            await ctx.send(embed=embeds.info(
                "Current Prefix",
                f"This server's prefix is `{current}`.\n"
                f"You can also always use {ctx.guild.me.mention} instead of the prefix.\n\n"
                f"Run `/prefix <new_prefix>` to change it.",
            ))
            return

        new_prefix = new_prefix.strip()
        if not new_prefix:
            await ctx.send(embed=embeds.error("Invalid Prefix", "The prefix can't be empty or just whitespace."), ephemeral=True)
            return
        if len(new_prefix) > 5:
            await ctx.send(embed=embeds.error("Invalid Prefix", "Prefixes must be 5 characters or shorter."), ephemeral=True)
            return
        if new_prefix.startswith("/"):
            await ctx.send(embed=embeds.error("Invalid Prefix", "The prefix can't start with `/` — that's reserved for slash commands."), ephemeral=True)
            return

        prefix_db.set_prefix(ctx.guild.id, new_prefix)
        await ctx.send(embed=embeds.success(
            "Prefix Updated",
            f"This server's prefix is now `{new_prefix}`.\n"
            f"Example: `{new_prefix}lock` — or you can always use {ctx.guild.me.mention} instead.",
        ))

    @prefix.error
    async def prefix_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=embeds.error("Missing Permissions", "You need **Administrator** to change the server prefix."), ephemeral=True)

    @commands.hybrid_command(name="slowmode", description="Set this channel's slowmode delay.")
    @app_commands.describe(seconds="Delay in seconds (0 to disable, max 21600).")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def slowmode(self, ctx: commands.Context, seconds: commands.Range[int, 0, 21600]):
        await ctx.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            await ctx.send(embed=embeds.success("Slowmode Disabled", f"Slowmode has been turned off in {ctx.channel.mention}."))
        else:
            await ctx.send(embed=embeds.info("Slowmode Set", f"Slowmode set to **{seconds}s** in {ctx.channel.mention}."))

    # ── Member management ────────────────────────────────────────────────

    @commands.hybrid_command(name="nickname", description="Change a member's nickname.")
    @app_commands.describe(member="The member to rename.", nickname="The new nickname (leave blank to reset).")
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def nickname(self, ctx: commands.Context, member: discord.Member, nickname: str = None):
        await member.edit(nick=nickname, reason=f"Changed by {ctx.author}")
        if nickname:
            await ctx.send(embed=embeds.success("Nickname Changed", f"{member.mention}'s nickname is now **{nickname}**."))
        else:
            await ctx.send(embed=embeds.success("Nickname Reset", f"{member.mention}'s nickname has been reset."))

    @commands.hybrid_command(name="addrole", description="Add a role to a member.")
    @app_commands.describe(member="The member to give the role to.", role="The role to add.")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def addrole(self, ctx: commands.Context, member: discord.Member, role: discord.Role):
        if role >= ctx.guild.me.top_role:
            await ctx.send(embed=bot_hierarchy_blocked_embed(ctx.guild, role=role), ephemeral=True)
            return
        await member.add_roles(role, reason=f"Added by {ctx.author}")
        await ctx.send(embed=embeds.success("Role Added", f"Gave {role.mention} to {member.mention}."))

    @commands.hybrid_command(name="removerole", description="Remove a role from a member.")
    @app_commands.describe(member="The member to remove the role from.", role="The role to remove.")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def removerole(self, ctx: commands.Context, member: discord.Member, role: discord.Role):
        if role >= ctx.guild.me.top_role:
            await ctx.send(embed=bot_hierarchy_blocked_embed(ctx.guild, role=role), ephemeral=True)
            return
        await member.remove_roles(role, reason=f"Removed by {ctx.author}")
        await ctx.send(embed=embeds.success("Role Removed", f"Removed {role.mention} from {member.mention}."))

    @commands.hybrid_command(name="roleall", description="Give a role to every member who has another specific role.")
    @app_commands.describe(source_role="Members with this role will receive the new role.", role="The role to give them.")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def roleall(self, ctx: commands.Context, source_role: discord.Role, role: discord.Role):
        if role >= ctx.guild.me.top_role:
            await ctx.send(embed=bot_hierarchy_blocked_embed(ctx.guild, role=role), ephemeral=True)
            return

        targets = [m for m in source_role.members if role not in m.roles]
        if not targets:
            await ctx.send(embed=embeds.info("Nothing To Do", f"Every member with {source_role.mention} already has {role.mention}, or nobody currently has {source_role.mention}."))
            return

        view = ConfirmView(ctx.author.id, confirm_label="Give Role", danger=False, timeout=30)
        prompt = embeds.warning(
            "Confirm Bulk Role Add",
            f"Give {role.mention} to **{len(targets)}** member(s) who have {source_role.mention}?\nThis may take a moment for large groups.",
        )
        message = await ctx.send(embed=prompt, view=view)
        view.message = message
        await view.wait()
        if not view.result:
            cancelled = embeds.info("Cancelled", "Bulk role add was cancelled — no roles were changed.")
            try:
                await message.edit(embed=cancelled, view=None)
            except discord.HTTPException:
                pass
            return

        given, failed = 0, 0
        progress = embeds.info("Working…", f"Giving {role.mention} to {len(targets)} member(s)… 0/{len(targets)}")
        try:
            await message.edit(embed=progress, view=None)
        except discord.HTTPException:
            pass

        for idx, member in enumerate(targets, start=1):
            try:
                await member.add_roles(role, reason=f"/roleall by {ctx.author}: members with {source_role.name}")
                given += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1
            # Small delay between calls to stay well clear of rate limits on
            # large member lists — discord.py's HTTP layer already queues
            # and retries on 429s, but spacing calls out avoids hammering
            # the route on servers with hundreds of matching members.
            if idx % 10 == 0:
                await asyncio.sleep(1)
                try:
                    await message.edit(embed=embeds.info("Working…", f"Giving {role.mention} to {len(targets)} member(s)… {idx}/{len(targets)}"))
                except discord.HTTPException:
                    pass

        summary = embeds.success(
            "Bulk Role Add Complete",
            f"Gave {role.mention} to **{given}** member(s).\n{f'{failed} failed (permissions/hierarchy).' if failed else ''}",
        )
        try:
            await message.edit(embed=summary)
        except discord.HTTPException:
            await ctx.send(embed=summary)

    @commands.hybrid_command(name="rolerall", description="Remove a role from every member in the server.")
    @app_commands.describe(role="The role to remove from everyone.")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def rolerall(self, ctx: commands.Context, role: discord.Role):
        if role >= ctx.guild.me.top_role:
            await ctx.send(embed=bot_hierarchy_blocked_embed(ctx.guild, role=role), ephemeral=True)
            return

        targets = [m for m in role.members]
        if not targets:
            await ctx.send(embed=embeds.info("Nothing To Do", f"Nobody currently has {role.mention}."))
            return

        # This removes a role from every member who has it, server-wide —
        # deliberately requires confirmation and is flagged as dangerous,
        # since it's hard to undo cleanly on a large server.
        view = ConfirmView(ctx.author.id, confirm_label="Remove From Everyone", danger=True, timeout=30)
        prompt = embeds.warning(
            "Confirm Bulk Role Removal",
            f"Remove {role.mention} from **{len(targets)}** member(s) — this is everyone in the server who currently has it.\n"
            "This cannot be undone automatically. This may take a moment for large groups.",
        )
        message = await ctx.send(embed=prompt, view=view)
        view.message = message
        await view.wait()
        if not view.result:
            cancelled = embeds.info("Cancelled", "Bulk role removal was cancelled — no roles were changed.")
            try:
                await message.edit(embed=cancelled, view=None)
            except discord.HTTPException:
                pass
            return

        removed, failed = 0, 0
        progress = embeds.info("Working…", f"Removing {role.mention} from {len(targets)} member(s)… 0/{len(targets)}")
        try:
            await message.edit(embed=progress, view=None)
        except discord.HTTPException:
            pass

        for idx, member in enumerate(targets, start=1):
            try:
                await member.remove_roles(role, reason=f"/rolerall by {ctx.author}: removed from everyone")
                removed += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1
            if idx % 10 == 0:
                await asyncio.sleep(1)
                try:
                    await message.edit(embed=embeds.info("Working…", f"Removing {role.mention} from {len(targets)} member(s)… {idx}/{len(targets)}"))
                except discord.HTTPException:
                    pass

        summary = embeds.success(
            "Bulk Role Removal Complete",
            f"Removed {role.mention} from **{removed}** member(s).\n{f'{failed} failed (permissions/hierarchy).' if failed else ''}",
        )
        try:
            await message.edit(embed=summary)
        except discord.HTTPException:
            await ctx.send(embed=summary)



async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
