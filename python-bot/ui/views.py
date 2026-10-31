# Credits: gogeta_gg
"""
Shared View primitives.

BaseView: every interactive panel in the bot should subclass this so the
"only the person who opened this panel can click it" rule (Phase:
INTERACTION SECURITY) is enforced in exactly one place instead of
re-implemented per-cog.
"""

import discord
from .emoji import E, bind_view_emojis

from . import embeds


class BaseView(discord.ui.View):
    """
    Locks all children to the user who triggered the interaction that
    created this view, unless allow_any_user=True is explicitly passed
    (e.g. public leaderboard navigation).
    """

    def __init__(self, author_id: int | None = None, *, timeout: float = 180, allow_any_user: bool = False):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.allow_any_user = allow_any_user
        self.message: discord.Message | None = None
        bind_view_emojis(self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.allow_any_user or self.author_id is None:
            return True
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            embed=embeds.permission_denied("Only the person who opened this panel can use it."),
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


class ConfirmView(BaseView):
    """
    Generic yes/no confirmation. Use for destructive actions (bans,
    disabling every protection module at once, deleting an application,
    etc). `result` is set to True/False/None(timeout) once resolved and
    `done` is set so callers can await it via wait().
    """

    def __init__(self, author_id: int, *, confirm_label="Confirm", cancel_label="Cancel", danger=True, timeout=60):
        super().__init__(author_id=author_id, timeout=timeout)
        self.result: bool | None = None
        confirm_style = discord.ButtonStyle.danger if danger else discord.ButtonStyle.success
        self.confirm_btn.label = confirm_label
        self.confirm_btn.style = confirm_style
        self.cancel_btn.label = cancel_label
        bind_view_emojis(self)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = False
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()


class BackButton(discord.ui.Button):
    """Drop-in back button. `on_back` is an async callback: (interaction) -> None."""

    def __init__(self, on_back, *, row: int | None = None):
        super().__init__(label="Back", style=discord.ButtonStyle.secondary, row=row)
        self._on_back = on_back

    async def callback(self, interaction: discord.Interaction):
        await self._on_back(interaction)
