# Credits: gogeta_gg
from ui.emoji import E, bind_view_emojis
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord import app_commands

from . import invite_tracker_db
from ui import embeds
from ui.pagination import Paginator, chunk
from ui.rendering import render_stat_card

# How long we keep a just-deleted invite around as a fallback attribution
# target. Single-use invites are often auto-deleted by Discord the instant
# they're used, which means the join event can arrive after the invite has
# already vanished from guild.invites() — without this, that join would be
# misattributed as "unknown".
DELETED_INVITE_GRACE_SECONDS = 15

LEADERBOARD_PAGE_SIZE = 8

RANK_MEDALS = {1: E('q_medal'), 2: E('q_medal'), 3: E('q_medal')}


class InviteCardView(discord.ui.View):
    """Sits under the /invites check image card. Author-locked like every
    other panel in the bot — implemented directly here (rather than via
    ui.views.BaseView) because this view swaps between an image attachment
    and an embed depending which button was pressed, which needs its own
    edit_original_response handling either way."""

    def __init__(self, cog: "InviteTracker", author_id: int, target_id: int, *, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.author_id = author_id
        self.target_id = target_id
        self.message: discord.Message | None = None
        bind_view_emojis(self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            embed=embeds.permission_denied("Only the person who ran this command can use it."),
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Leaderboard", style=discord.ButtonStyle.primary)
    async def leaderboard_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = await self.cog._build_leaderboard_view(interaction.guild, interaction.user.id)
        await interaction.edit_original_response(embed=view.current, view=view, attachments=[])
        view.message = interaction.message

    @discord.ui.button(label="My Invites", style=discord.ButtonStyle.primary)
    async def my_invites_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        file, view, fallback_embed = await self.cog._build_card_response(interaction.guild, interaction.user, interaction.user.id)
        if file is not None:
            await interaction.edit_original_response(embed=None, attachments=[file], view=view)
        else:
            await interaction.edit_original_response(embed=fallback_embed, attachments=[], view=view)
        view.message = interaction.message

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        target = interaction.guild.get_member(self.target_id) or await interaction.guild.fetch_member(self.target_id)
        file, view, fallback_embed = await self.cog._build_card_response(interaction.guild, target, self.author_id)
        if file is not None:
            await interaction.edit_original_response(embed=None, attachments=[file], view=view)
        else:
            await interaction.edit_original_response(embed=fallback_embed, attachments=[], view=view)
        view.message = interaction.message


class InviteLeaderboardView(Paginator):
    """Paginated leaderboard (prev/next/page-count from Paginator) plus a
    My Invites / Refresh row underneath, matching the check-card panel."""

    def __init__(self, cog: "InviteTracker", pages: list[discord.Embed], author_id: int, *, timeout: float = 180):
        super().__init__(pages, author_id, timeout=timeout)
        self.cog = cog

        my_invites = discord.ui.Button(label="My Invites", style=discord.ButtonStyle.primary, row=1)
        my_invites.callback = self._my_invites
        self.add_item(my_invites)

        refresh = discord.ui.Button(label="Refresh", style=discord.ButtonStyle.secondary, row=1)
        refresh.callback = self._refresh
        self.add_item(refresh)

    async def _my_invites(self, interaction: discord.Interaction):
        await interaction.response.defer()
        file, view, fallback_embed = await self.cog._build_card_response(interaction.guild, interaction.user, interaction.user.id)
        if file is not None:
            await interaction.edit_original_response(embed=None, attachments=[file], view=view)
        else:
            await interaction.edit_original_response(embed=fallback_embed, attachments=[], view=view)
        view.message = interaction.message

    async def _refresh(self, interaction: discord.Interaction):
        pages = self.cog._build_leaderboard_pages(interaction.guild)
        self.pages = pages
        self.index = min(self.index, len(pages) - 1)
        self._sync_labels()
        await interaction.response.edit_message(embed=self.current, view=self)


class InviteTracker(commands.Cog):
    """Advanced invite tracking: figures out who invited whom, splits
    invites into regular / leave / fake / bonus / vanity / unknown buckets,
    and exposes a leaderboard — similar to InviteManager/Vanity bots.

    Requires the bot to have Manage Server (to read invite uses) and the
    Members privileged intent (already enabled in bot.py).
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        invite_tracker_db.setup_database()
        # guild_id -> {code: uses}
        self._uses_cache = defaultdict(dict)
        # guild_id -> {code: inviter_id}
        self._inviter_cache = defaultdict(dict)
        # guild_id -> deque[(code, inviter_id, monotonic_deleted_at)]
        self._recently_deleted = defaultdict(deque)

    # ── Cache management ─────────────────────────────────────────────────

    async def _refresh_cache(self, guild: discord.Guild):
        if not guild.me.guild_permissions.manage_guild:
            return
        try:
            invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return
        self._uses_cache[guild.id] = {inv.code: (inv.uses or 0) for inv in invites}
        self._inviter_cache[guild.id] = {
            inv.code: (inv.inviter.id if inv.inviter else None) for inv in invites
        }

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            invite_tracker_db.setup_database()
            await self._refresh_cache(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._refresh_cache(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        self._uses_cache[invite.guild.id][invite.code] = invite.uses or 0
        self._inviter_cache[invite.guild.id][invite.code] = invite.inviter.id if invite.inviter else None

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        guild_id = invite.guild.id
        inviter_id = self._inviter_cache.get(guild_id, {}).pop(invite.code, None)
        self._uses_cache.get(guild_id, {}).pop(invite.code, None)
        if inviter_id is not None:
            self._recently_deleted[guild_id].append((invite.code, inviter_id, time.monotonic()))

    def _pop_recently_deleted(self, guild_id):
        bucket = self._recently_deleted[guild_id]
        cutoff = time.monotonic() - DELETED_INVITE_GRACE_SECONDS
        while bucket and bucket[0][2] < cutoff:
            bucket.popleft()
        if bucket:
            return bucket.popleft()  # oldest pending deletion = most likely match
        return None

    # ── Attribution ──────────────────────────────────────────────────────
    # (unchanged from the previous version — this logic is already correct
    # and wasn't part of the UI ask, so it's untouched below.)

    async def _attribute_join(self, member: discord.Member):
        """Returns (inviter_id, code, join_type)."""
        guild = member.guild

        if guild.me.guild_permissions.manage_guild:
            try:
                current = await guild.invites()
            except (discord.Forbidden, discord.HTTPException):
                current = None
        else:
            current = None

        if current is not None:
            before = self._uses_cache.get(guild.id, {})
            increased = [
                inv for inv in current
                if (inv.uses or 0) > before.get(inv.code, 0)
            ]
            self._uses_cache[guild.id] = {inv.code: (inv.uses or 0) for inv in current}
            self._inviter_cache[guild.id] = {
                inv.code: (inv.inviter.id if inv.inviter else None) for inv in current
            }
            if len(increased) == 1:
                inv = increased[0]
                return (inv.inviter.id if inv.inviter else None), inv.code, "regular"
            elif len(increased) > 1:
                return None, None, "unknown"

        recently_deleted = self._pop_recently_deleted(guild.id)
        if recently_deleted is not None:
            code, inviter_id, _ = recently_deleted
            return inviter_id, code, "regular"

        if guild.vanity_url_code:
            try:
                vanity = await guild.vanity_invite()
                if vanity is not None:
                    return None, guild.vanity_url_code, "vanity"
            except (discord.Forbidden, discord.HTTPException):
                return None, guild.vanity_url_code, "vanity"

        return None, None, "unknown"

    # ── Listeners ────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        settings = invite_tracker_db.get_settings(member.guild.id)
        if not settings["enabled"]:
            return

        inviter_id, code, join_type = await self._attribute_join(member)

        account_age_days = (datetime.now(timezone.utc) - member.created_at).days
        is_fake = account_age_days < settings["fake_account_age_days"]
        if is_fake and join_type == "regular":
            join_type = "fake"

        invite_tracker_db.record_join(member.guild.id, member.id, inviter_id, code, join_type, int(time.time()))
        await self._log_join(member, inviter_id, code, join_type, account_age_days)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        settings = invite_tracker_db.get_settings(member.guild.id)
        if not settings["enabled"]:
            return

        closed = invite_tracker_db.record_leave(member.guild.id, member.id, int(time.time()))
        if closed and closed["inviter_id"] and closed["join_type"] == "regular":
            await self._log_leave(member, closed["inviter_id"])

    # ── Logging ──────────────────────────────────────────────────────────

    async def _log_channel(self, guild: discord.Guild):
        settings = invite_tracker_db.get_settings(guild.id)
        channel_id = settings["log_channel_id"]
        if not channel_id:
            return None
        return guild.get_channel(channel_id)

    async def _log_join(self, member, inviter_id, code, join_type, account_age_days):
        channel = await self._log_channel(member.guild)
        if channel is None:
            return

        if join_type == "vanity":
            desc = f"{member.mention} joined using the **vanity URL**."
        elif inviter_id is None:
            desc = f"{member.mention} joined but the invite used couldn't be determined."
        else:
            stats = invite_tracker_db.get_stats(member.guild.id, inviter_id)
            tag = ' ' + E('q_report') + ' **flagged as a likely fake/alt account**' if join_type == "fake" else ""
            desc = (
                f"{member.mention} joined using **{code}**, invited by <@{inviter_id}>.{tag}\n"
                f"<@{inviter_id}> now has **{stats['total']}** effective invites "
                f"({stats['regular']} regular, {stats['leaves']} left, {stats['fake']} fake, {stats['bonus']} bonus)."
            )

        embed = embeds.invites("Member Joined", desc)
        embed.set_footer(text=f"Gogeta Sentinel • Account created {account_age_days} day(s) ago")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _log_leave(self, member, inviter_id):
        channel = await self._log_channel(member.guild)
        if channel is None:
            return
        stats = invite_tracker_db.get_stats(member.guild.id, inviter_id)
        embed = embeds.warning(
            "Member Left",
            f"{member.mention} left. They were invited by <@{inviter_id}>, who now has "
            f"**{stats['total']}** effective invites ({stats['leaves']} left total).",
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    # ── Card / leaderboard builders (shared by slash commands + buttons) ──

    async def _build_card_response(self, guild: discord.Guild, member: discord.Member, viewer_id: int):
        """Returns (discord.File, InviteCardView) for the given member's
        stat card, as seen by viewer_id (whoever gets author-lock on the
        resulting view's buttons)."""
        stats = invite_tracker_db.get_stats(guild.id, member.id)
        rank, total_tracked = invite_tracker_db.get_rank(guild.id, member.id)
        settings = invite_tracker_db.get_settings(guild.id)

        recent_raw = invite_tracker_db.get_recent_activity(guild.id, member.id, limit=5)
        recent = []
        for event in recent_raw:
            target_member = guild.get_member(event["member_id"])
            name = target_member.display_name if target_member else f"User {event['member_id']}"
            recent.append({"name": name, "type": event["type"], "at": event["at"]})

        view = InviteCardView(self, viewer_id, member.id)
        try:
            buf = await render_stat_card(member, stats, rank, total_tracked, bool(settings["enabled"]), recent)
            return discord.File(buf, filename="invite_stats.png"), view, None
        except Exception as exc:
            # Keep invite tracking usable even if the host's Pillow build is broken.
            fallback_description = "\n".join((
                f"**Rank:** {f'#{rank}' if rank else 'Unranked'} / {total_tracked}",
                f"**Effective invites:** {stats['total']}",
                f"**Regular:** {stats['regular']}  •  **Left:** {stats['leaves']}",
                f"**Fake:** {stats['fake']}  •  **Bonus:** {stats['bonus']}",
                f"**Tracking:** {'Enabled' if settings['enabled'] else 'Disabled'}",
                "*Image card unavailable; showing text stats instead.*",
            ))
            fallback = embeds.invites(f"Invite Stats — {member.display_name}", fallback_description)
            print(f"[InviteTracker] Image card fallback: {type(exc).__name__}: {exc}")
            return None, view, fallback

    def _build_leaderboard_pages(self, guild: discord.Guild, limit: int = 25) -> list[discord.Embed]:
        board = invite_tracker_db.get_leaderboard(guild.id, limit)
        if not board:
            return [embeds.empty_state("Invite Leaderboard", "No invites tracked yet.")]

        entries = []
        for i, (user_id, stats) in enumerate(board, start=1):
            member = guild.get_member(user_id)
            name = member.mention if member else f"<@{user_id}>"
            rank_label = RANK_MEDALS.get(i, f"**#{i}**")
            entries.append(
                f"{rank_label} {name} — **{stats['total']}** effective "
                f"({stats['regular']} regular, {stats['leaves']} left, {stats['fake']} fake, {stats['bonus']} bonus)"
            )

        pages = []
        for page_entries in chunk(entries, LEADERBOARD_PAGE_SIZE):
            embed = embeds.invites("Invite Leaderboard", "\n".join(page_entries))
            embed.set_footer(text=f"Gogeta Sentinel • {len(board)} tracked user(s)")
            pages.append(embed)
        return pages

    async def _build_leaderboard_view(self, guild: discord.Guild, author_id: int) -> InviteLeaderboardView:
        pages = self._build_leaderboard_pages(guild)
        return InviteLeaderboardView(self, pages, author_id)

    # ── Commands ─────────────────────────────────────────────────────────

    invites_group = app_commands.Group(name="invites", description="Check invite stats.")
    config_group = app_commands.Group(name="invites-config", description="Configure invite tracking.")

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return (
            interaction.guild is not None
            and isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.administrator
        )

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        if not self._is_admin(interaction):
            await interaction.response.send_message(embed=embeds.permission_denied("You must be an administrator to use this."), ephemeral=True)
            return False
        return True

    @invites_group.command(name="check", description="Show a member's invite stats.")
    @app_commands.describe(member="Whose stats to show (defaults to you).")
    async def check(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        await interaction.response.defer()
        file, view, fallback_embed = await self._build_card_response(interaction.guild, member, interaction.user.id)
        if file is not None:
            message = await interaction.followup.send(file=file, view=view)
        else:
            message = await interaction.followup.send(embed=fallback_embed, view=view)
        view.message = message

    @invites_group.command(name="leaderboard", description="Show the top inviters in this server.")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = await self._build_leaderboard_view(interaction.guild, interaction.user.id)
        message = await interaction.followup.send(embed=view.current, view=view)
        view.message = message

    @config_group.command(name="enable", description="Enable invite tracking for this server.")
    async def enable(self, interaction: discord.Interaction):
        if not await self._require_admin(interaction):
            return
        invite_tracker_db.set_enabled(interaction.guild.id, True)
        await self._refresh_cache(interaction.guild)
        await interaction.response.send_message(embed=embeds.success("Invite Tracking Enabled", "Now tracking joins and leaves."))

    @config_group.command(name="disable", description="Disable invite tracking for this server.")
    async def disable(self, interaction: discord.Interaction):
        if not await self._require_admin(interaction):
            return
        invite_tracker_db.set_enabled(interaction.guild.id, False)
        await interaction.response.send_message(embed=embeds.warning("Invite Tracking Disabled", "No longer tracking joins and leaves."))

    @config_group.command(name="logchannel", description="Set the channel invite tracking posts join/leave logs to.")
    async def logchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not await self._require_admin(interaction):
            return
        invite_tracker_db.set_log_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(embed=embeds.success("Log Channel Set", f"Invite logs will now post in {channel.mention}."))

    @config_group.command(name="fake-age", description="Set how new (in days) an account must be to get flagged as fake.")
    async def fake_age(self, interaction: discord.Interaction, days: app_commands.Range[int, 0, 90]):
        if not await self._require_admin(interaction):
            return
        invite_tracker_db.set_fake_account_age(interaction.guild.id, days)
        await interaction.response.send_message(embed=embeds.success("Fake-Age Threshold Updated", f"Accounts younger than **{days}** day(s) old will now be flagged as fake joins."))

    @config_group.command(name="add", description="Manually grant bonus invites to a member.")
    async def add_bonus(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 10000]):
        if not await self._require_admin(interaction):
            return
        new_total = invite_tracker_db.adjust_bonus(interaction.guild.id, member.id, amount)
        await interaction.response.send_message(embed=embeds.success("Bonus Invites Granted", f"Gave {member.mention} **{amount}** bonus invite(s). Bonus total: **{new_total}**."))

    @config_group.command(name="remove", description="Remove bonus invites from a member.")
    async def remove_bonus(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 10000]):
        if not await self._require_admin(interaction):
            return
        new_total = invite_tracker_db.adjust_bonus(interaction.guild.id, member.id, -amount)
        await interaction.response.send_message(embed=embeds.success("Bonus Invites Removed", f"Removed **{amount}** bonus invite(s) from {member.mention}. Bonus total: **{new_total}**."))

    @config_group.command(name="reset", description="Wipe a member's invite stats.")
    async def reset(self, interaction: discord.Interaction, member: discord.Member):
        if not await self._require_admin(interaction):
            return
        invite_tracker_db.reset_user(interaction.guild.id, member.id)
        await interaction.response.send_message(embed=embeds.success("Stats Cleared", f"Cleared {member.mention}'s invite stats."))


async def setup(bot: commands.Bot):
    cog = InviteTracker(bot)
    await bot.add_cog(cog)
