# Credits: gogeta_gg
from ui.emoji import E
import discord
from discord.ext import commands
from discord import app_commands

from . import tickets_db, apply_db
from .tickets_view import TicketPanelView, TicketCloseView
from ui import embeds as ui_embeds


class Tickets(commands.Cog):
    """Ticket system — Support / Reward / Staff Application, each with their
    own category and staff role. Staff-application tickets automatically
    embed the exact main Staff Applications panel so applying works
    identically whether opened from a ticket or the main panel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        tickets_db.setup_database()
        # Re-register persistent views so buttons on old messages keep
        # working after a bot restart.
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(TicketCloseView())

    @commands.hybrid_group(name="ticket", description="Configure and deploy the ticket system.")
    async def ticket_group(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ticket_group.command(name="setup", description="Configure the category and staff role for one ticket type.")
    @app_commands.describe(
        type="Which ticket type to configure.",
        category="Where new tickets of this type are created.",
        staff_role="Role that can see tickets of this type, besides the opener.",
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="Support", value="support"),
        app_commands.Choice(name="Reward", value="reward"),
        app_commands.Choice(name="Staff Application", value="staff_app"),
    ])
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def ticket_setup(
        self,
        ctx: commands.Context,
        type: app_commands.Choice[str],
        category: discord.CategoryChannel,
        staff_role: discord.Role,
    ):
        ticket_type = type.value
        tickets_db.set_type_category(ctx.guild.id, ticket_type, category.id)
        tickets_db.set_type_staff_role(ctx.guild.id, ticket_type, staff_role.id)

        extra_note = ""
        if ticket_type == "staff_app":
            settings_ok = False
            try:
                from . import apply_db
                settings = apply_db.get_settings(ctx.guild.id)
                settings_ok = bool(settings and settings["review_channel_id"] and settings["grant_role_id"])
            except Exception:
                pass
            if not settings_ok:
                extra_note = (
                    "\n\n" + E("q_error") + " Staff applications themselves aren't configured yet — "
                    "run `/apply_setup` and `/apply_questions` too, or Staff Application tickets will "
                    "open but the embedded application form won't work yet."
                )

        embed = ui_embeds.success(
            f"{tickets_db.TYPE_LABELS[ticket_type]} Tickets Configured",
            f"**Category:** {category.mention}\n**Staff role:** {staff_role.mention}{extra_note}",
        )
        await ctx.send(embed=embed, ephemeral=True)

    @ticket_group.command(name="panel", description="Post the 3-button ticket panel (Support / Reward / Staff Application) in a channel.")
    @app_commands.describe(channel="Where to post the ticket panel.", title="Optional custom title.", description="Optional custom description.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def ticket_panel(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        title: str = None,
        description: str = None,
    ):
        configs = tickets_db.get_all_type_configs(ctx.guild.id)
        missing = [tickets_db.TYPE_LABELS[t] for t in tickets_db.TYPES if not configs.get(t, {}).get("category_id")]
        if missing:
            await ctx.send(
                embed=ui_embeds.error(
                    "Ticket Types Not Configured",
                    f"Run `/ticket setup` for: **{', '.join(missing)}** before posting the panel.",
                ),
                ephemeral=True,
            )
            return

        embed = ui_embeds.premium(
            title or E("q_ticket") + " OPEN A TICKET",
            description or (
                "Choose the option below that matches what you need.\n\n"
                f"{E('q_ticket')} **Support** — general help or questions\n"
                f"{E('q_sparkle')} **Reward** — claim a reward or prize\n"
                f"{E('q_admin')} **Staff Application** — apply to join the team\n\n"
                "A private channel will be created for you."
            ),
            discord.Color.from_rgb(88, 164, 242),
            icon=E("q_ticket"),
            footer_label="Tickets",
        )
        await channel.send(embed=embed, view=TicketPanelView())
        await ctx.send(f"{E('q_success')} Ticket panel posted in {channel.mention}.", ephemeral=True)

    @commands.hybrid_command(name="close", description="Close the current ticket.")
    @commands.guild_only()
    async def close_ticket(self, ctx: commands.Context):
        """Close the ticket channel this command is used in."""
        ticket = tickets_db.get_ticket_by_channel(ctx.channel.id)
        if ticket is None:
            await ctx.send(f"{E('q_error')} This command can only be used inside an active ticket.", ephemeral=True)
            return
        if ticket["status"] != "open":
            await ctx.send(f"{E('q_error')} This ticket is already closed.", ephemeral=True)
            return

        member = ctx.author if isinstance(ctx.author, discord.Member) else None
        is_opener = ctx.author.id == ticket["opener_id"]
        is_staff = bool(member and member.guild_permissions.manage_guild)
        if not (is_opener or is_staff):
            await ctx.send(f"{E('q_error')} You don't have permission to close this ticket.", ephemeral=True)
            return

        if ticket["ticket_type"] == "staff_app" and ticket.get("application_id"):
            # The existing button handles the application-specific pending check.
            # Keep the command conservative when an application ticket is still pending.
            try:
                application = apply_db.get_application(ticket["application_id"])
                if application and application["status"] == "pending":
                    await ctx.send(
                        f"{E('q_error')} This staff application is still pending review. It must be **approved** or **denied** before this ticket can be closed.",
                        ephemeral=True,
                    )
                    return
            except Exception:
                pass

        await ctx.send(embed=ui_embeds.premium(
            "Closing Ticket",
            "This ticket will be deleted in 5 seconds…",
            discord.Color.orange(),
            icon=E("q_ticket"),
            footer_label="Tickets",
        ))
        tickets_db.close_ticket(ticket["id"], ctx.author.id)
        self.bot.dispatch("ticket_closed", ctx.channel, ticket)

        try:
            await ctx.channel.edit(name=f"closed-{ctx.channel.name}"[:100])
            for target in list(ctx.channel.overwrites.keys()):
                if isinstance(target, (discord.Member, discord.Role)) and target != ctx.guild.me:
                    await ctx.channel.set_permissions(target, overwrite=None)
        except discord.HTTPException:
            pass

        import asyncio
        await asyncio.sleep(5)
        try:
            await ctx.channel.delete(reason=f"Ticket closed by {ctx.author}")
        except discord.HTTPException:
            pass

    @ticket_group.command(name="settings", description="View the current ticket configuration.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def ticket_settings(self, ctx: commands.Context):
        configs = tickets_db.get_all_type_configs(ctx.guild.id)
        embed = ui_embeds.premium(E("q_admin") + " Ticket Settings", "", discord.Color.blurple(), icon=E("q_admin"), footer_label="Tickets")
        for ticket_type in tickets_db.TYPES:
            cfg = configs.get(ticket_type, {})
            category = ctx.guild.get_channel(cfg.get("category_id")) if cfg.get("category_id") else None
            role = ctx.guild.get_role(cfg.get("staff_role_id")) if cfg.get("staff_role_id") else None
            embed.add_field(
                name=tickets_db.TYPE_LABELS[ticket_type],
                value=f"**Category:** {category.mention if category else 'Not set'}\n**Staff role:** {role.mention if role else 'Not set'}",
                inline=True,
            )
        await ctx.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
