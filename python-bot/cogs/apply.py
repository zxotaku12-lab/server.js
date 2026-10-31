# Credits: gogeta_gg
from ui.emoji import E
import discord
from discord.ext import commands
from discord import app_commands

from . import apply_db
from .apply_view import ApplyButtonView, ApplicationReviewView, build_apply_panel_embed
from ui import embeds as ui_embeds


def apply_embed(title, description, color=discord.Color.blurple()):
    return ui_embeds.application(title, description)


class Apply(commands.Cog):
    """Staff application system — apply via button, approve/deny with auto role grant."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        apply_db.setup_database()
        # Re-register persistent views so buttons on old messages keep
        # working after a bot restart.
        self.bot.add_view(ApplyButtonView())
        self.bot.add_view(ApplicationReviewView())

    # ── Setup / configuration ──────────────────────────────────────────

    @commands.hybrid_command(
        name="apply_setup",
        description="Configure the staff application system.",
    )
    @app_commands.describe(
        review_channel="Where new applications get posted for staff to review.",
        grant_role="The role automatically granted when an application is approved.",
        required_role="Optional — a role members must already have to apply.",
        approval_channel="Optional — where an announcement is posted when someone's approved.",
    )
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def apply_setup(
        self,
        ctx: commands.Context,
        review_channel: discord.TextChannel,
        grant_role: discord.Role,
        required_role: discord.Role = None,
        approval_channel: discord.TextChannel = None,
    ):
        if grant_role >= ctx.guild.me.top_role:
            await ctx.send(
                E('q_error') + " I can't grant a role that's higher than or equal to my own top role. "
                "Move my role above it in Server Settings → Roles.",
                ephemeral=True,
            )
            return

        apply_db.set_review_channel(ctx.guild.id, review_channel.id)
        apply_db.set_grant_role(ctx.guild.id, grant_role.id)
        apply_db.set_required_role(ctx.guild.id, required_role.id if required_role else None)
        if approval_channel:
            apply_db.set_approval_channel(ctx.guild.id, approval_channel.id)

        embed = apply_embed(
            E('q_success') + ' Staff Applications Configured',
            f"**Review channel:** {review_channel.mention}\n"
            f"**Role granted on approval:** {grant_role.mention}\n"
            f"**Required role to apply:** {required_role.mention if required_role else 'None'}\n"
            f"**Approval announcements:** {approval_channel.mention if approval_channel else 'Not set'}\n\n"
            f"Next: use `/apply_questions` to customize the form (optional), "
            f"then `/apply_panel` to post the Apply button.",
            discord.Color.green(),
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="apply_approval_channel",
        description="Set or clear the channel where approval announcements are posted.",
    )
    @app_commands.describe(channel="Leave empty to turn off approval announcements.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def apply_approval_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        apply_db.set_approval_channel(ctx.guild.id, channel.id if channel else None)
        if channel:
            await ctx.send(f"{E('q_success')} Approval announcements will now be posted in {channel.mention}.")
        else:
            await ctx.send(E('q_success') + ' Approval announcements are now turned off.')

    @commands.hybrid_command(
        name="apply_questions",
        description="Set the questions applicants are asked (up to 5).",
    )
    @app_commands.describe(
        question1="First question (required).",
        question2="Second question.",
        question3="Third question.",
        question4="Fourth question.",
        question5="Fifth question.",
    )
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def apply_questions(
        self,
        ctx: commands.Context,
        question1: str,
        question2: str = None,
        question3: str = None,
        question4: str = None,
        question5: str = None,
    ):
        questions = [q for q in [question1, question2, question3, question4, question5] if q]
        apply_db.set_questions(ctx.guild.id, questions)

        numbered = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
        embed = apply_embed(E('q_success') + ' Application Questions Updated', numbered, discord.Color.green())
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="apply_panel",
        description="Post the Apply button panel in a channel.",
    )
    @app_commands.describe(
        channel="Where to post the Apply panel.",
        title="Optional custom title.",
        description="Optional custom description.",
    )
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def apply_panel(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        title: str = None,
        description: str = None,
    ):
        settings = apply_db.get_settings(ctx.guild.id)
        if not settings or not settings["review_channel_id"] or not settings["grant_role_id"]:
            await ctx.send(
                E('q_error') + ' Run `/apply_setup` first to configure a review channel and grant role.',
                ephemeral=True,
            )
            return

        embed = build_apply_panel_embed(title, description)
        await channel.send(embed=embed, view=ApplyButtonView())
        await ctx.send(f"{E('q_success')} Application panel posted in {channel.mention}.", ephemeral=True)

    @commands.hybrid_command(
        name="apply_toggle",
        description="Open or close staff applications.",
    )
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def apply_toggle(self, ctx: commands.Context):
        settings = apply_db.get_settings(ctx.guild.id)
        if not settings:
            await ctx.send(E('q_error') + ' Run `/apply_setup` first.', ephemeral=True)
            return

        new_state = not settings["enabled"]
        apply_db.set_enabled(ctx.guild.id, new_state)
        await ctx.send(
            E('q_online') + ' Applications are now **open**.' if new_state else E('q_offline') + ' Applications are now **closed**.'
        )

    @commands.hybrid_command(
        name="apply_settings",
        description="View the current staff application configuration.",
    )
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def apply_settings(self, ctx: commands.Context):
        settings = apply_db.get_settings(ctx.guild.id)
        if not settings:
            await ctx.send(E('q_error') + " Staff applications haven't been set up yet. Run `/apply_setup`.", ephemeral=True)
            return

        review_channel = ctx.guild.get_channel(settings["review_channel_id"]) if settings["review_channel_id"] else None
        grant_role = ctx.guild.get_role(settings["grant_role_id"]) if settings["grant_role_id"] else None
        required_role = ctx.guild.get_role(settings["required_role_id"]) if settings["required_role_id"] else None
        approval_channel = ctx.guild.get_channel(settings["approval_channel_id"]) if settings.get("approval_channel_id") else None
        questions = "\n".join(f"{i+1}. {q}" for i, q in enumerate(settings["questions"]))

        embed = apply_embed(E('q_admin') + ' Staff Application Settings', "", discord.Color.blurple())
        embed.add_field(name="Status", value=E('q_online') + ' Open' if settings["enabled"] else E('q_offline') + ' Closed', inline=True)
        embed.add_field(name="Review Channel", value=review_channel.mention if review_channel else "Not set", inline=True)
        embed.add_field(name="Grants Role", value=grant_role.mention if grant_role else "Not set", inline=True)
        embed.add_field(name="Required Role", value=required_role.mention if required_role else "None", inline=True)
        embed.add_field(name="Approval Announcements", value=approval_channel.mention if approval_channel else "Off", inline=True)
        embed.add_field(name="Questions", value=questions or "None set", inline=False)

        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        name="apply_status",
        description="Check the status of your most recent staff application.",
    )
    @commands.guild_only()
    async def apply_status(self, ctx: commands.Context):
        app = apply_db.get_latest_application(ctx.guild.id, ctx.author.id)
        if app is None:
            await ctx.send("You haven't submitted a staff application in this server.", ephemeral=True)
            return

        status_map = {
            "pending": (E("q_loading") + " Pending review", discord.Color.gold()),
            "approved": (E('q_success') + ' Approved', discord.Color.green()),
            "denied": (E('q_error') + ' Denied', discord.Color.red()),
        }
        label, color = status_map.get(app["status"], ("Unknown", discord.Color.blurple()))

        embed = apply_embed(f"Your Application #{app['id']}", "", color)
        embed.add_field(name="Status", value=label, inline=False)
        if app["status"] == "denied" and app["reason"]:
            embed.add_field(name="Reason", value=app["reason"], inline=False)

        await ctx.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Apply(bot))
