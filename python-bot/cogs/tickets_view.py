# Credits: gogeta_gg
"""Ticket panel and channel views.

Three buttons — Support / Reward / Staff Application — each create a
private channel in that type's configured category, visible to the
opener plus that type's configured staff role.

Opening a Staff Application ticket additionally pastes the exact same
main Staff Applications panel (embed + ApplyButtonView) used by
/apply_panel into the new channel, so applying inside a ticket is
identical to applying from the main panel — same questions, same
wizard, same review/approval flow, same grant-role logic.
"""
from ui.emoji import E, bind_view_emojis
import discord

from . import tickets_db, apply_db
from .apply_view import ApplyButtonView, build_apply_panel_embed
from ui import embeds as ui_embeds

TYPE_EMOJI = {
    "support": "q_ticket",
    "reward": "q_sparkle",
    "staff_app": "q_admin",
}


def _ticket_card(title, description, color=discord.Color.blurple()):
    embed = ui_embeds.premium(title, description, color, icon=E("q_ticket"), footer_label="Tickets")
    return embed


async def _create_ticket_channel(guild: discord.Guild, opener: discord.Member, ticket_type: str, type_config: dict) -> discord.TextChannel:
    category = guild.get_channel(type_config["category_id"]) if type_config and type_config.get("category_id") else None
    staff_role = guild.get_role(type_config["staff_role_id"]) if type_config and type_config.get("staff_role_id") else None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        opener: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_permissions=True, read_message_history=True),
    }
    if staff_role is not None:
        overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True)

    safe_name = "".join(c for c in opener.name.lower() if c.isalnum() or c in "-_")[:20] or str(opener.id)
    channel_name = f"{ticket_type.replace('_', '-')}-{safe_name}"

    channel = await guild.create_text_channel(
        name=channel_name,
        category=category if isinstance(category, discord.CategoryChannel) else None,
        overwrites=overwrites,
        reason=f"Ticket opened by {opener} ({opener.id})",
    )
    return channel


class TicketCloseView(discord.ui.View):
    """Persistent Close button attached to every ticket channel."""

    def __init__(self):
        super().__init__(timeout=None)
        bind_view_emojis(self)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message(E('q_error') + ' Something went wrong. Please try again.', ephemeral=True)
            except discord.HTTPException:
                pass
        print(f"[TicketCloseView] error in {item}: {type(error).__name__}: {error}")

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = tickets_db.get_ticket_by_channel(interaction.channel_id)
        if ticket is None:
            await interaction.response.send_message(E('q_error') + " Couldn't find this ticket in the database.", ephemeral=True)
            return
        if ticket["status"] != "open":
            await interaction.response.send_message(E('q_error') + ' This ticket is already closed.', ephemeral=True)
            return

        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        is_opener = interaction.user.id == ticket["opener_id"]
        is_staff = bool(member and member.guild_permissions.manage_guild)
        if not (is_opener or is_staff):
            await interaction.response.send_message(E('q_error') + " You don't have permission to close this ticket.", ephemeral=True)
            return

        if ticket["ticket_type"] == "staff_app" and ticket.get("application_id"):
            app = apply_db.get_application(ticket["application_id"])
            if app and app["status"] == "pending":
                await interaction.response.send_message(
                    E('q_error') + ' This staff application is still pending review. It must be **approved** or '
                    '**denied** from the review channel before this ticket can be closed.',
                    ephemeral=True,
                )
                return

        await interaction.response.send_message(embed=_ticket_card("Closing Ticket", "This ticket will be deleted in 5 seconds…", discord.Color.orange()))
        tickets_db.close_ticket(ticket["id"], interaction.user.id)
        interaction.client.dispatch("ticket_closed", interaction.channel, ticket)

        try:
            await interaction.channel.edit(name=f"closed-{interaction.channel.name}"[:100])
            for target in list(interaction.channel.overwrites.keys()):
                if isinstance(target, (discord.Member, discord.Role)) and target != interaction.guild.me:
                    await interaction.channel.set_permissions(target, overwrite=None)
        except discord.HTTPException:
            pass

        import asyncio
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")
        except discord.HTTPException:
            pass


class TicketPanelView(discord.ui.View):
    """The persistent 3-button panel: Support / Reward / Staff Application."""

    def __init__(self):
        super().__init__(timeout=None)
        bind_view_emojis(self)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message(E('q_error') + ' Something went wrong. Please try again.', ephemeral=True)
            except discord.HTTPException:
                pass
        print(f"[TicketPanelView] error in {item}: {type(error).__name__}: {error}")

    async def _open(self, interaction: discord.Interaction, ticket_type: str):
        guild = interaction.guild
        type_config = tickets_db.get_type_config(guild.id, ticket_type)
        if not type_config or not type_config.get("category_id"):
            await interaction.response.send_message(
                E('q_error') + f" {tickets_db.TYPE_LABELS[ticket_type]} tickets aren't fully configured yet. Please contact an admin.",
                ephemeral=True,
            )
            return

        if tickets_db.has_open_ticket(guild.id, interaction.user.id, ticket_type):
            await interaction.response.send_message(
                E("q_loading") + f" You already have an open {tickets_db.TYPE_LABELS[ticket_type].lower()} ticket. Please use that one.",
                ephemeral=True,
            )
            return

        if ticket_type == "staff_app":
            settings = apply_db.get_settings(guild.id)
            if not settings or not settings["enabled"]:
                await interaction.response.send_message(E('q_cross') + ' Staff applications are currently closed.', ephemeral=True)
                return
            if not settings["review_channel_id"] or not settings["grant_role_id"]:
                await interaction.response.send_message(E('q_error') + " Staff applications aren't fully configured yet. Please contact an admin.", ephemeral=True)
                return
            if settings["required_role_id"]:
                required_role = guild.get_role(settings["required_role_id"])
                if required_role and required_role not in interaction.user.roles:
                    await interaction.response.send_message(f"{E('q_error')} You need the {required_role.mention} role to apply.", ephemeral=True)
                    return
            if apply_db.has_pending_application(guild.id, interaction.user.id):
                await interaction.response.send_message(
                    E("q_loading") + " You already have a pending application. Please wait for it to be reviewed.",
                    ephemeral=True,
                )
                return

        await interaction.response.defer(ephemeral=True)

        ticket_id = tickets_db.create_ticket(guild.id, ticket_type, interaction.user.id)
        try:
            channel = await _create_ticket_channel(guild, interaction.user, ticket_type, type_config)
        except discord.Forbidden:
            await interaction.followup.send(E('q_error') + " I don't have permission to create channels in the configured category.", ephemeral=True)
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(f"{E('q_error')} Failed to create the ticket channel.\n`{exc}`", ephemeral=True)
            return

        tickets_db.set_ticket_channel(ticket_id, channel.id)

        intro = _ticket_card(
            f"{tickets_db.TYPE_LABELS[ticket_type]} Ticket",
            f"{interaction.user.mention} opened this ticket.\n\nA member of staff will be with you shortly.",
        )
        staff_role = guild.get_role(type_config["staff_role_id"]) if type_config.get("staff_role_id") else None
        await channel.send(
            content=f"{interaction.user.mention}" + (f" {staff_role.mention}" if staff_role else ""),
            embed=intro,
            view=TicketCloseView(),
        )

        interaction.client.dispatch("ticket_created", channel, interaction.user, ticket_type)

        if ticket_type == "staff_app":
            # Paste the exact main Staff Applications panel into the new
            # ticket — same embed, same ApplyButtonView, same questions and
            # review flow as /apply_panel. Nothing about the application
            # system itself is reimplemented here.
            await channel.send(embed=build_apply_panel_embed(), view=ApplyButtonView())

        await interaction.followup.send(embed=ui_embeds.success("Ticket Opened", f"Your ticket has been created: {channel.mention}"), ephemeral=True)

    @discord.ui.button(label="Support", style=discord.ButtonStyle.primary, custom_id="ticket_open_support")
    async def open_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open(interaction, "support")

    @discord.ui.button(label="Reward", style=discord.ButtonStyle.success, custom_id="ticket_open_reward")
    async def open_reward(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open(interaction, "reward")

    @discord.ui.button(label="Staff Application", style=discord.ButtonStyle.secondary, custom_id="ticket_open_staff_app")
    async def open_staff_app(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open(interaction, "staff_app")
