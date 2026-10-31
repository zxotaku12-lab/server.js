# Credits: gogeta_gg
from ui.emoji import E
import discord
from discord.ext import tasks
from datetime import datetime, timezone

import activity
from ui import embeds as ui_embeds

# ===========================
# CONFIGURATION
# ===========================

# Server-wide defaults. Per-role overrides (set via /inactivity_role_thresholds)
# take priority over these when a member holds a configured role.
WARNING_DAYS = 7
STAFF_NOTIFY_DAYS = 10

# Warning/staff channels and staff-ping role are no longer hardcoded here —
# each guild configures its own via /inactivity_set_channels and
# /inactivity_staff_ping_role, stored in activity.py's inactivity_settings
# table and looked up per-guild during the scan.


class InactivityChecker:

    def __init__(self, client):
        self.client = client
        self.enabled = False

    def stop_tracking(self):
        self.enabled = False
        print(E('q_error') + ' Inactivity tracking disabled.')

    def start_tracking(self):
        self.enabled = True

        if not self.check_members.is_running():
            self.check_members.start()

        print(E('q_success') + ' Inactivity tracking started')

    def status(self):
        return self.enabled

    @tasks.loop(hours=24)
    async def check_members(self):
        if not self.enabled:
            return

        members = await activity.get_all_members()
        now = datetime.now(timezone.utc)

        warned_count = 0

        # Channels and role configs are per-guild now (no more single
        # hardcoded pair shared across every server the bot is in), so we
        # cache each guild's lookups the first time we see that guild_id
        # in this pass instead of hitting the DB again for every member.
        guild_cache = {}

        for guild_id, user_id, last_activity, warned, staff_notified in members:

            if not self.enabled:
                print(E('q_error') + ' Inactivity tracking stopped mid-scan.')
                return

            if guild_id not in guild_cache:
                guild_cache[guild_id] = await self._load_guild_config(guild_id)

            config = guild_cache[guild_id]
            if config is None:
                # Warning/staff channels haven't been set up for this guild yet
                # (see /inactivity_set_channels) — skip it, not the whole scan.
                continue

            # One bad row (unparsable timestamp, member who left mid-scan,
            # a failed API call, etc.) must never take the whole daily scan
            # down with it — everyone else still needs to be checked.
            try:
                result = await self._check_one_member(
                    guild_id, user_id, last_activity, warned, staff_notified,
                    now, config,
                )
            except Exception as e:
                print(f"{E('q_error')} Inactivity check failed for user {user_id} in guild {guild_id}: {type(e).__name__}: {e}")
                continue

            if result == "warned":
                warned_count += 1

        print(f"{E('q_success')} Inactivity scan complete. warned={warned_count} (kicking is manual-only — see $inactivity_kick_run)")

    async def _load_guild_config(self, guild_id):
        """Resolves everything check_members needs for one guild: the
        warning/staff channel objects, the staff ping role, and the list of
        per-role overrides. Returns None if the guild hasn't configured its
        warning/staff channels yet (nothing to send to, so it's skipped)."""
        warning_channel_id, staff_channel_id = await activity.get_channels(guild_id)

        if warning_channel_id is None or staff_channel_id is None:
            print(f"{E('q_error')} Inactivity checker: guild {guild_id} has no warning/staff channel configured — "
                  f"run /inactivity_set_channels there. Skipping.")
            return None

        warning_channel = self.client.get_channel(warning_channel_id)
        staff_channel = self.client.get_channel(staff_channel_id)

        if warning_channel is None or staff_channel is None:
            print(f"{E('q_error')} Inactivity checker: configured warning/staff channel for guild {guild_id} "
                  f"not found (bad ID or bot no longer has access). Skipping.")
            return None

        staff_ping_role_id = await activity.get_staff_ping_role(guild_id)
        role_configs = await activity.get_role_configs(guild_id)

        return {
            "warning_channel": warning_channel,
            "staff_channel": staff_channel,
            "staff_ping_role_id": staff_ping_role_id,
            "role_configs": role_configs,
        }

    def _resolve_role_settings(self, member, role_configs):
        """Combines a member's roles with the guild's per-role inactivity
        overrides. Returns (exempt, warning_days, kick_days) where
        warning_days/kick_days are None if no role override applies (caller
        should fall back to the server-wide default in that case).

        If the member holds any role marked exempt, they're fully exempt —
        no warning, no staff notification, no kick — regardless of any
        other role's thresholds.

        If multiple non-exempt roles set custom thresholds, the most
        lenient (longest grace period) wins, so a member never gets
        penalized by the strictest of several roles they happen to hold.
        """
        if not role_configs:
            return False, None, None

        member_role_ids = {r.id for r in member.roles}
        warning_days = None
        kick_days = None

        for role_id, exempt, role_warning_days, role_kick_days in role_configs:
            if role_id not in member_role_ids:
                continue

            if exempt:
                return True, None, None

            if role_warning_days is not None:
                warning_days = role_warning_days if warning_days is None else max(warning_days, role_warning_days)
            if role_kick_days is not None:
                kick_days = role_kick_days if kick_days is None else max(kick_days, role_kick_days)

        return False, warning_days, kick_days

    async def _check_one_member(
        self, guild_id, user_id, last_activity_raw, warned, staff_notified,
        now, config,
    ):
        """Returns "warned" or None depending on what action (if any) was taken.
        Never kicks — kicking only happens via run_kick_now(), triggered
        explicitly by the $inactivity_kick_run command in a single guild."""
        try:
            last_activity = datetime.fromisoformat(last_activity_raw)
        except (TypeError, ValueError):
            return None

        # last_activity is always stored in UTC (see activity.update_activity),
        # but guard against naive datetimes from old/bad rows so the
        # subtraction below can't crash.
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)

        inactive_days = (now - last_activity).days

        guild = self.client.get_guild(guild_id)
        if guild is None:
            return None

        member = guild.get_member(user_id)
        if member is None:
            return None

        exempt, role_warning_days, _ = self._resolve_role_settings(member, config["role_configs"])
        if exempt:
            return None

        warning_days = role_warning_days if role_warning_days is not None else WARNING_DAYS
        # Staff notification stays anchored relative to the warning threshold
        # (same 3-day gap as the defaults) so a role's longer grace period
        # also pushes back when staff get pinged, instead of staff getting
        # notified about someone before their own warning window is even up.
        staff_notify_days = warning_days + (STAFF_NOTIFY_DAYS - WARNING_DAYS)

        warning_channel = config["warning_channel"]
        staff_channel = config["staff_channel"]
        staff_ping_role_id = config["staff_ping_role_id"]

        did_warn_this_pass = False

        # --------------------------
        # WARNING (role-specific threshold if configured, else default)
        # --------------------------
        if inactive_days >= warning_days and warned == 0:
            embed = ui_embeds.premium(
                "Inactivity Warning",
                description=(
                    f"{member.mention}\n\n"
                    f"You haven't sent a message in **{inactive_days} days**.\n\n"
                    f"Please become active within the next **3 days** "
                    f"to remain an active member of **{guild.name}**."
                ),
                color=ui_embeds.Color.WARNING,
                icon=E('q_error'),
                footer_label="Inactivity Warning System",
            )

            await warning_channel.send(content=member.mention, embed=embed)
            await activity.mark_warned(guild_id, user_id)
            did_warn_this_pass = True

        # --------------------------
        # STAFF NOTIFICATION (role-specific threshold if configured, else default)
        # --------------------------
        if inactive_days >= staff_notify_days and staff_notified == 0:
            embed = ui_embeds.premium(
                "Inactive Member",
                description=(
                    f"{member.mention} has been inactive for "
                    f"**{inactive_days} days**.\n\n"
                    "They ignored their inactivity warning.\n"
                    "Please review them manually."
                ),
                color=ui_embeds.Color.ERROR,
                icon=E('q_emergency'),
                footer_label="Staff Notification",
            )

            ping_content = None
            if staff_ping_role_id is not None:
                role = guild.get_role(staff_ping_role_id)
                if role is not None:
                    ping_content = role.mention

            await staff_channel.send(content=ping_content, embed=embed)
            await activity.mark_staff_notified(guild_id, user_id)

        if did_warn_this_pass:
            return "warned"

        return None

    async def run_kick_now(self, guild: discord.Guild):
        """Manually kick members of ONE guild who have exceeded that guild's
        configured inactivity threshold ($inactivity_kick_days). This is the
        only place a kick is ever issued — there is no scheduled/automatic
        kicking anywhere else. Only members of the given guild are touched;
        every other guild is completely unaffected until its own admin runs
        this command there.

        Returns (kicked, skipped):
          kicked  -> list of (member, inactive_days)
          skipped -> list of (member, inactive_days, reason)
        """
        kick_after_days, _ = await activity.get_kick_settings(guild.id)
        role_configs = await activity.get_role_configs(guild.id)
        now = datetime.now(timezone.utc)
        rows = await activity.get_guild_members(guild.id)

        kicked = []
        skipped = []

        for user_id, last_activity_raw in rows:
            try:
                last_activity = datetime.fromisoformat(last_activity_raw)
            except (TypeError, ValueError):
                continue

            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)

            inactive_days = (now - last_activity).days

            member = guild.get_member(user_id)
            if member is None:
                continue

            exempt, _, role_kick_days = self._resolve_role_settings(member, role_configs)
            if exempt:
                continue

            effective_kick_days = role_kick_days if role_kick_days is not None else kick_after_days
            if inactive_days < effective_kick_days:
                continue

            if guild.me is None:
                skipped.append((member, inactive_days, "bot has no member object in guild"))
                continue

            if member == guild.owner:
                skipped.append((member, inactive_days, "server owner"))
                continue

            if member.top_role >= guild.me.top_role:
                skipped.append((member, inactive_days, "role too high for bot to kick"))
                continue

            try:
                await member.kick(reason=f"Manual inactivity kick — inactive {inactive_days} days")
                await activity.remove_member(guild.id, user_id)
                kicked.append((member, inactive_days))
            except discord.Forbidden:
                skipped.append((member, inactive_days, "missing permission"))
            except Exception as e:
                skipped.append((member, inactive_days, f"{type(e).__name__}: {e}"))

        return kicked, skipped

    @check_members.before_loop
    async def before_check_members(self):
        await self.client.wait_until_ready()
        print(E('q_success') + ' Inactivity checker ready.')

    @check_members.error
    async def check_members_error(self, error):
        print(f"{E('q_error')} Inactivity task crashed: {type(error).__name__}: {error}")
