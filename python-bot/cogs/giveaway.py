# Credits: gogeta_gg
from ui.emoji import E
import re
import time
import discord

from discord.ext import commands
from discord import app_commands

from . import giveaway_db
from . import giveaway_utils
from .giveaway_view import GiveawayView
from ui import embeds as ui_embeds


def parse_duration(duration: str) -> int:
    """
    Converts:
        30m
        2h
        7d
        1w
    into seconds.
    """

    duration = duration.lower().strip()

    match = re.fullmatch(r"(\d+)([mhdw])", duration)

    if not match:
        raise ValueError("Invalid duration")

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "m":
        return value * 60

    if unit == "h":
        return value * 60 * 60

    if unit == "d":
        return value * 60 * 60 * 24

    if unit == "w":
        return value * 60 * 60 * 24 * 7

    raise ValueError("Invalid duration")


async def create_giveaway_message(
    *,
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    host: discord.Member | discord.User,
    prize: str,
    duration: str,
    winners: int,
    ping_role: discord.Role | None = None,
):
    """Create a giveaway using the same core flow as the Discord modal."""
    prize = str(prize).strip()
    if not prize:
        raise ValueError("Prize is required.")

    try:
        winner_count = int(winners)
    except (TypeError, ValueError):
        raise ValueError("Winners must be a number.")
    if winner_count < 1:
        winner_count = 1

    duration_seconds = parse_duration(str(duration))
    end_time = int(time.time()) + duration_seconds

    embed = ui_embeds.giveaway(
        "GIVEAWAY",
        description=(
            f"## {E('q_giveaway')} {prize}\n\n"
            f"**{E('q_owner')} Hosted by:** {host.mention}\n"
            f"**{E('q_trophy')} Winners:** **{winner_count}**\n"
            f"**{E('q_time')} Ends:** <t:{end_time}:R>\n"
            f"**{E('q_calendar')} End Time:** <t:{end_time}:F>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n" + E('q_celebrate') + " **Press the button below to enter!**"
        ),
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.set_footer(
        text=f"Hosted by {host}",
        icon_url=host.display_avatar.url,
    )

    content = ping_role.mention if ping_role else None
    allowed_mentions = discord.AllowedMentions(roles=True, users=True, everyone=False)
    message = await channel.send(
        content=content,
        embed=embed,
        view=GiveawayView(),
        allowed_mentions=allowed_mentions,
    )

    giveaway_db.create_giveaway(
        message_id=message.id,
        channel_id=channel.id,
        guild_id=guild.id,
        host_id=host.id,
        prize=prize,
        winners=winner_count,
        end_time=end_time,
    )
    return message, end_time, winner_count


class GiveawayModal(discord.ui.Modal, title="Create Giveaway"):

    prize = discord.ui.TextInput(
        label="Prize",
        placeholder="Discord Nitro",
        max_length=100,
        required=True
    )

    duration = discord.ui.TextInput(
        label="Duration",
        placeholder="30m, 2h, 7d, 1w",
        max_length=20,
        required=True
    )

    winners = discord.ui.TextInput(
        label="Number of Winners",
        placeholder="1",
        default="1",
        max_length=2,
        required=True
    )

    channel = discord.ui.TextInput(
        label="Channel (optional)",
        placeholder="Channel ID or #mention",
        required=False
    )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        channel = interaction.channel

        if self.channel.value:
            channel_input = (
                self.channel.value
                .replace("<#", "")
                .replace(">", "")
                .strip()
            )
            try:
                found = interaction.guild.get_channel(int(channel_input))
                if found:
                    channel = found
            except Exception:
                pass

        try:
            _, _, _ = await create_giveaway_message(
                guild=interaction.guild,
                channel=channel,
                host=interaction.user,
                prize=self.prize.value,
                duration=self.duration.value,
                winners=self.winners.value,
            )
        except ValueError as exc:
            message = str(exc)
            if "Invalid duration" in message:
                message = (
                    'Invalid duration.\n\nExamples:\n`30m`\n`2h`\n`7d`\n`1w`'
                )
            await interaction.response.send_message(
                E('q_error') + ' ' + message,
                ephemeral=True,
            )
            return
        except (discord.Forbidden, discord.HTTPException) as exc:
            await interaction.response.send_message(
                E('q_error') + f' Could not create the giveaway: `{exc}`',
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"{E('q_success')} Giveaway created successfully in {channel.mention}!",
            ephemeral=True,
        )

class Giveaway(commands.Cog):
    """Giveaway management commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        giveaway_db.setup_database()

    async def cog_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ):
        # Shared error handling for every hybrid command in this cog
        # (gbonusrole add/remove/list, greroll). gstart stays on its own
        # dedicated app-command error handler below since it can't be a
        # hybrid command (modals require a slash interaction).
        original = getattr(error, "original", error)

        if isinstance(original, (commands.MissingPermissions, app_commands.MissingPermissions)):
            msg = f"{E('q_error')} You need **{', '.join(original.missing_permissions)}** permission to use this command."
        elif isinstance(original, commands.BadArgument):
            msg = f"{E('q_error')} {original}"
        else:
            msg = f"{E('q_error')} Something went wrong: `{original}`"

        await ctx.send(msg, ephemeral=True)

    def build_weighted_entries(
        self,
        guild: discord.Guild,
        giveaway
    ):
        return giveaway_utils.build_weighted_entries(guild, giveaway)

    def pick_weighted_winners(
        self,
        guild: discord.Guild,
        giveaway
    ):
        return giveaway_utils.pick_weighted_winners(guild, giveaway)

    @commands.hybrid_group(
        name="gbonusrole",
        description="Manage giveaway bonus entry roles."
    )
    async def bonusrole(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @bonusrole.command(
        name="add",
        description="Give a role bonus giveaway entries."
    )
    @commands.has_permissions(
        manage_guild=True
    )
    async def bonusrole_add(
        self,
        ctx: commands.Context,
        role: discord.Role,
        entries: app_commands.Range[int, 2, 100]
    ):
        giveaway_db.add_bonus_role(
            ctx.guild.id,
            role.id,
            entries
        )

        embed = ui_embeds.success(
            "Bonus Role Added",
            description=(
                f"**Role:** {role.mention}\n"
                f"**Bonus Entries:** **{entries}x**"
            ),
        )

        await ctx.send(
            embed=embed,
            ephemeral=True
        )

    @bonusrole.command(
        name="remove",
        description="Remove a giveaway bonus role."
    )
    @commands.has_permissions(
        manage_guild=True
    )
    async def bonusrole_remove(
        self,
        ctx: commands.Context,
        role: discord.Role
    ):
        giveaway_db.remove_bonus_role(
            ctx.guild.id,
            role.id
        )

        embed = ui_embeds.success(
            "Bonus Role Removed",
            description=(
                f"{role.mention} will no longer receive "
                "bonus giveaway entries."
            ),
        )

        await ctx.send(
            embed=embed,
            ephemeral=True
        )

    @bonusrole.command(
        name="list",
        description="View all giveaway bonus roles."
    )
    @commands.has_permissions(
        manage_guild=True
    )
    async def bonusrole_list(
        self,
        ctx: commands.Context
    ):
        rows = giveaway_db.get_bonus_roles(
            ctx.guild.id
        )

        if not rows:
            await ctx.send(
                E('q_error') + ' No bonus roles have been configured.',
                ephemeral=True
            )
            return

        description = ""

        for row in rows:
            description += (
                f"<@&{row['role_id']}> • "
                f"**{row['entries']}x** entries\n"
            )

        embed = ui_embeds.giveaway("Giveaway Bonus Roles", description)

        embed.set_footer(
            text=f"{len(rows)} bonus role(s) configured"
        )

        await ctx.send(
            embed=embed,
            ephemeral=True
        )

    @commands.command(name="gstart")
    @commands.has_permissions(manage_guild=True)
    async def gstart(self, ctx):

        await ctx.send(
            "Please use **/gstart**.\n"
            "Discord modals only work with slash commands."
        )

    @app_commands.command(
        name="gstart",
        description="Create a giveaway"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def slash_gstart(
        self,
        interaction: discord.Interaction
    ):

        await interaction.response.send_modal(
            GiveawayModal()
        )

    @slash_gstart.error
    async def slash_gstart_error(
        self,
        interaction: discord.Interaction,
        error
    ):

        if isinstance(
            error,
            app_commands.MissingPermissions
        ):

            if interaction.response.is_done():

                await interaction.followup.send(
                    E('q_error') + ' You need **Manage Server** permission to use this command.',
                    ephemeral=True
                )

            else:

                await interaction.response.send_message(
                    E('q_error') + ' You need **Manage Server** permission to use this command.',
                    ephemeral=True
                )

    @commands.hybrid_command(
        name="greroll",
        description="Reroll a giveaway winner."
    )
    @app_commands.describe(message_id="The giveaway's message ID.")
    @commands.has_permissions(
        manage_guild=True
    )
    async def greroll(
        self,
        ctx: commands.Context,
        message_id: str
    ):
        try:
            giveaway = giveaway_db.get_giveaway(
                int(message_id)
            )
        except ValueError:
            await ctx.send(
                E('q_error') + " That doesn't look like a valid message ID.",
                ephemeral=True
            )
            return

        if giveaway is None:
            await ctx.send(
                E('q_error') + ' Giveaway not found.',
                ephemeral=True
            )
            return

        guild = ctx.guild

        winners = self.pick_weighted_winners(
            guild,
            giveaway
        )

        if not winners:
            await ctx.send(
                E('q_error') + ' No participants found.',
                ephemeral=True
            )
            return

        winner_mentions = ", ".join(
            f"<@{user_id}>"
            for user_id in winners
        )

        channel = self.bot.get_channel(
            giveaway["channel_id"]
        )

        if channel:
            await channel.send(
                f"{E('q_sync')} **Giveaway Rerolled!**\n\n"
                f"{E('q_celebrate')} Congratulations {winner_mentions}!\n"
                f"You won **{giveaway['prize']}**!"
            )

        await ctx.send(
            E('q_success') + ' Giveaway rerolled successfully.',
            ephemeral=True
        )

async def setup(bot):
    await bot.add_cog(Giveaway(bot))
