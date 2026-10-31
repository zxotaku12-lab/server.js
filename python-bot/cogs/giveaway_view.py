# Credits: gogeta_gg
from ui.emoji import E, bind_view_emojis
import discord
from . import giveaway_db
from ui import embeds as ui_embeds


class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        bind_view_emojis(self)

    @discord.ui.button(
        label="Enter",
        style=discord.ButtonStyle.success,
        custom_id="giveaway_enter"
    )
    async def enter(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        message_id = interaction.message.id
        user_id = interaction.user.id

        if giveaway_db.is_giveaway_ended(message_id):
            await interaction.response.send_message(
                E('q_error') + ' This giveaway has already ended.',
                ephemeral=True
            )
            return

        success = giveaway_db.add_entry(message_id, user_id)

        if success:
            await interaction.response.send_message(
                E('q_success') + ' You have successfully entered the giveaway!',
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                E('q_error') + ' You have already entered this giveaway.',
                ephemeral=True
            )

    @discord.ui.button(
        label="Participants",
        style=discord.ButtonStyle.primary,
        custom_id="giveaway_participants"
    )
    async def participants(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        message_id = interaction.message.id
        entries = giveaway_db.get_entries(message_id)

        if not entries:
            await interaction.response.send_message(
                "No participants yet.",
                ephemeral=True
            )
            return

        lines = []

        for user_id in entries:
            member = interaction.guild.get_member(user_id)

            if member:
                multiplier = giveaway_db.get_bonus_entries(
                    interaction.guild.id,
                    [role.id for role in member.roles]
                )

                entry_text = "Entry" if multiplier == 1 else "Entries"

                lines.append(
                    f"{member.mention} — {E('q_ticket')} **{multiplier} {entry_text}**"
                )

        embed = ui_embeds.giveaway("Giveaway Participants", "\n".join(lines))

        embed.set_footer(
            text=f"Total Participants: {len(entries)}"
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )
